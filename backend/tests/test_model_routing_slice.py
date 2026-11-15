import json

import httpx
import pytest

from app.model_routing import CloudAdapter, ModelResult, ModelRouter, redact_sensitive


def test_cloud_adapter_is_not_created_without_explicit_enable_and_key(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "")
    assert ModelRouter().cloud is None


def test_sensitive_values_are_redacted_before_cloud_request():
    value = "contact alice@example.com, token=SECRET_VALUE and phone 13812345678"
    redacted = redact_sensitive(value)
    assert "alice@example.com" not in redacted
    assert "SECRET_VALUE" not in redacted
    assert "13812345678" not in redacted


def test_local_first_cloud_fallback_records_call_and_never_logs_key(monkeypatch):
    from app.config import settings
    from app.db import SessionLocal
    from app.models import ModelCallLog

    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "SECRET_VALUE")
    monkeypatch.setattr(settings, "daily_cloud_call_limit", 20)
    monkeypatch.setattr(settings, "daily_cost_limit", 2.0)
    router = ModelRouter()
    router.local.structured_log = lambda text: (_ for _ in ()).throw(RuntimeError("offline"))

    def handler(*args, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer SECRET_VALUE"
        assert "SECRET_VALUE" not in json.dumps(kwargs["json"])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"topics": ["T"], "duration_minutes": None, "outputs": [], "understood": [], "unresolved_questions": [], "self_assessment": None})}}]})

    monkeypatch.setattr(httpx, "post", handler)
    result = router.parse_daily_log("学习 T")
    assert result.success and result.provider == "zhiapi"
    with SessionLocal() as db:
        row = db.query(ModelCallLog).order_by(ModelCallLog.id.desc()).first()
        assert row and row.provider == "zhiapi" and row.success


def test_cloud_budget_blocks_calls(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "key")
    monkeypatch.setattr(settings, "daily_cloud_call_limit", 0)
    router = ModelRouter()
    router.local.structured_log = lambda text: (_ for _ in ()).throw(RuntimeError("offline"))
    result = router.parse_daily_log("普通学习记录")
    assert result.success
    assert result.provider == "deterministic"
    assert result.fallback_used is True
    assert result.route_reason == "daily_log_deterministic_fallback"
    assert "deterministic fallback" in (result.error or "").lower()
    monkeypatch.setattr(settings, "daily_cloud_call_limit", 20)


def test_cache_returns_same_result_without_second_provider_call(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "cloud_model_enabled", False)
    router = ModelRouter()
    calls = []
    router.local.structured_log = lambda text: calls.append(text) or type("R", (), {"success": True, "data": {"topics": ["x"]}, "provider": "ollama", "model_name": "local", "error": None, "duration_ms": 1})()
    assert router.parse_daily_log("same") .data == {"topics": ["x"]}
    assert router.parse_daily_log("same").data == {"topics": ["x"]}
    assert len(calls) == 1


def test_risk_classification_keeps_sensitive_input_local(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "key")
    router = ModelRouter()
    assert router.classify_risk("SECRET_FIELD token=abc") == "high"
    assert router.should_use_cloud("SECRET_FIELD token=abc") is False
    assert router.should_use_cloud("学习 Python") is True


def test_local_health_check_disables_ambient_proxy(monkeypatch):
    from app.model_routing import OllamaAdapter

    captured = {}

    def fake_get(*args, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert OllamaAdapter().health_check() is True
    assert captured["trust_env"] is False


def test_cloud_health_treats_unsupported_model_listing_as_reachable():
    adapter = CloudAdapter(
        "configured-key",
        post=lambda *args, **kwargs: httpx.Response(404, json={"error": "not found"}),
    )

    assert adapter.health_check() is True


def test_cloud_health_rejects_server_failure():
    adapter = CloudAdapter(
        "configured-key",
        post=lambda *args, **kwargs: httpx.Response(503, json={"error": "unavailable"}),
    )

    assert adapter.health_check() is False


def test_ollama_stream_chat_accepts_openai_sse_and_native_json_lines(monkeypatch):
    from app.model_routing import OllamaAdapter

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter(
                [
                    'data: {"choices":[{"delta":{"content":"OpenAI"}}]}',
                    'data: [DONE]',
                    '{"message":{"content":"原生"}}',
                    '{"response":"格式","done":true}',
                ]
            )

    def fake_stream(*args, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(httpx, "stream", fake_stream)

    chunks = list(OllamaAdapter().stream_chat("teaching", "解释流式响应"))

    assert chunks == ["OpenAI", "原生", "格式"]
    assert captured["json"]["stream"] is True
    assert captured["trust_env"] is False


@pytest.mark.asyncio
async def test_execute_stream_buffers_local_chunks_and_returns_request_result(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", False)
    router = ModelRouter()
    router.local.stream_chat = lambda task_type, prompt, **kwargs: iter(["第一段", "第二段"])
    recorded = []
    router._record = lambda result, *args, **kwargs: recorded.append(result)

    result = await router.execute_stream("teaching", "解释 HTTP", turn_id="buffered")

    assert result.text == "第一段第二段"
    assert result.turn_id == "buffered"
    assert recorded and recorded[0].route_reason == "local_stream_success"


@pytest.mark.asyncio
async def test_execute_stream_does_not_restart_local_after_partial_disconnect(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", False)
    monkeypatch.setattr(settings, "model_max_retries", 1)
    monkeypatch.setattr(settings, "model_retry_backoff_seconds", 0.0)
    router = ModelRouter()
    attempts = []

    def flaky_stream(task_type, prompt, **kwargs):
        attempts.append((task_type, prompt))
        if len(attempts) == 1:
            yield "第一段"
            raise httpx.ReadError("temporary disconnect")
        yield "第一段"
        yield "第二段"

    router.local.stream_chat = flaky_stream
    router._record = lambda *args, **kwargs: None

    result = await router.execute_stream("teaching", "解释 HTTP", turn_id="disconnect")

    assert result.text is None
    assert len(attempts) == 1
    assert result.route_reason == "cloud_disabled"


def test_teaching_returns_failure_when_models_are_unavailable(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", False)
    monkeypatch.setattr(settings, "cloud_model_api_key", "")
    monkeypatch.setattr(settings, "model_max_retries", 0)
    router = ModelRouter()
    router.local.chat = lambda task_type, prompt: ModelResult(
        False,
        None,
        "ollama",
        settings.local_model_name,
        error="offline",
    )
    recorded = []
    router._record = lambda result, *args, **kwargs: recorded.append(result)

    result = router.run_task("teaching", "用户问题：解释 HTTP")

    assert result.success is False
    assert result.provider == "ollama"
    assert result.route_reason == "local_first_cloud_unavailable"
    assert recorded and recorded[-1].provider == "ollama"


@pytest.mark.asyncio
async def test_execute_stream_returns_failure_when_no_fallback_is_available(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", False)
    monkeypatch.setattr(settings, "cloud_model_api_key", "")
    monkeypatch.setattr(settings, "model_max_retries", 0)
    router = ModelRouter()
    router.local.stream_chat = lambda task_type, prompt: (_ for _ in ()).throw(httpx.ConnectError("offline"))
    router.local.chat = lambda task_type, prompt: ModelResult(False, None, "ollama", settings.local_model_name, error="offline")
    router._record = lambda *args, **kwargs: None

    result = await router.execute_stream("teaching", "用户问题：什么是协程？", turn_id="no-fallback")

    assert result.text is None
    assert result.route_reason == "cloud_disabled"


def test_teaching_returns_failure_when_cloud_upgrade_is_blocked_by_budget(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "configured-for-test")
    monkeypatch.setattr(settings, "daily_cloud_call_limit", 0)
    monkeypatch.setattr(settings, "daily_cost_limit", 0.0)
    monkeypatch.setattr(settings, "model_max_retries", 0)
    router = ModelRouter()
    router.local.chat = lambda task_type, prompt: ModelResult(False, None, "ollama", settings.local_model_name, error="offline")
    router._record = lambda *args, **kwargs: None

    result = router.run_task("teaching", "用户问题：解释数据库事务")

    assert result.success is False
    assert result.provider == "ollama"
    assert result.route_reason == "local_first_budget_blocked_local_unavailable"
assert True
