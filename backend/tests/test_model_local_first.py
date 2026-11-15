import httpx
import pytest

from app.model_routing import ModelResult, ModelRouter


def test_medium_task_uses_local_success_without_cloud(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "SECRET_VALUE")
    router = ModelRouter()
    cloud_calls = []
    router.local.chat = lambda task_type, prompt: ModelResult(
        True, None, "ollama", "local", text="本地草稿", confidence=0.91
    )
    router.cloud._post = lambda *args, **kwargs: cloud_calls.append(kwargs) or httpx.Response(200, json={"choices": [{"message": {"content": "云端草稿"}}]})

    result = router.run_task("writing", "写一篇总结")

    assert result.provider == "ollama"
    assert result.text == "本地草稿"
    assert cloud_calls == []


def test_medium_task_upgrades_to_cloud_after_local_failure(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "SECRET_VALUE")
    router = ModelRouter()
    router.local.chat = lambda task_type, prompt: ModelResult(False, None, "ollama", "local", error="local unavailable")
    router.cloud._post = lambda *args, **kwargs: httpx.Response(200, json={"choices": [{"message": {"content": "云端草稿"}}]})

    result = router.run_task("writing", "写一篇总结")

    assert result.provider == "zhiapi"
    assert result.text == "云端草稿"


def test_medium_task_keeps_local_result_when_cloud_budget_is_exhausted(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "SECRET_VALUE")
    router = ModelRouter()
    router.local.chat = lambda task_type, prompt: ModelResult(False, None, "ollama", "local", error="local unavailable")
    monkeypatch.setattr(router, "_budget_available", lambda: False)

    result = router.run_task("writing", "写一篇总结")

    assert result.success is False
    assert result.provider == "ollama"
    assert "budget" in (result.error or "").lower()
    assert result.route_reason == "local_first_budget_blocked_local_unavailable"


def test_local_daily_log_success_is_not_blocked_by_cloud_budget(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "SECRET_VALUE")
    router = ModelRouter()
    local_result = ModelResult(True, {"topics": ["FastAPI"]}, "ollama", "local", confidence=0.95)
    router.local.structured_log = lambda text: local_result
    monkeypatch.setattr(router, "_budget_available", lambda: False)

    result = router.parse_daily_log("学习 FastAPI")

    assert result.success is True
    assert result.provider == "ollama"
    assert result.data == {"topics": ["FastAPI"]}


def test_cloud_adapter_exposes_unified_contract(monkeypatch):
    from app.model_routing import CloudAdapter
    adapter = CloudAdapter("SECRET_VALUE")
    for method in ("chat", "structured_output", "summarize", "classify", "analyze", "stream", "health_check"):
        assert callable(getattr(adapter, method))


def test_policy_marks_medium_tasks_local_first():
    policy = ModelRouter().task_policy("writing")
    assert policy["provider"] == "local_first"
    assert policy["fallback_provider"] == "cloud"
    assert policy["reason"]


def test_local_adapter_exposes_unified_contract():
    adapter = ModelRouter().local
    for method in ("chat", "structured_output", "summarize", "classify", "analyze", "stream", "health_check"):
        assert callable(getattr(adapter, method))


def test_route_reason_is_recorded_after_local_success(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", False)
    router = ModelRouter()
    router.local.chat = lambda task_type, prompt: ModelResult(True, None, "ollama", "local", text="结果", confidence=0.9)
    result = router.run_task("writing", "写作")
    assert result.route_reason == "local_first_local_success"


def test_low_confidence_local_result_stays_local(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "SECRET_VALUE")
    router = ModelRouter()
    router.local.chat = lambda task_type, prompt: ModelResult(True, None, "ollama", "local", text="短", confidence=0.2)
    router.cloud._post = lambda *args, **kwargs: httpx.Response(200, json={"choices": [{"message": {"content": "云端结果"}}]})
    result = router.run_task("writing", "写作")
    assert result.provider == "ollama"
    assert result.text == "短"


def test_cloud_disabled_medium_task_returns_local_failure_without_upload(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", False)
    monkeypatch.setattr(settings, "cloud_model_api_key", "")
    router = ModelRouter()
    router.local.chat = lambda task_type, prompt: ModelResult(False, None, "ollama", "local", error="offline")
    result = router.run_task("writing", "写作")
    assert result.success is False
    assert result.provider == "ollama"
    assert "local" in (result.error or "").lower()


def test_cloud_only_uses_cloud_for_low_risk_task_without_calling_local(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "model_routing_mode", "cloud_only")
    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "SECRET_VALUE")
    router = ModelRouter()
    local_calls = []
    router.local.chat = lambda *args, **kwargs: local_calls.append(args) or pytest.fail("local provider must not be called")
    router.cloud._post = lambda *args, **kwargs: httpx.Response(200, json={"choices": [{"message": {"content": "云端结果"}}]})

    result = router.run_task("daily_log", "整理今天的学习记录")

    assert result.success is True
    assert result.provider == "zhiapi"
    assert result.text == "云端结果"
    assert local_calls == []


def test_cloud_only_does_not_fallback_to_local_when_cloud_unavailable(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "model_routing_mode", "cloud_only")
    monkeypatch.setattr(settings, "cloud_model_enabled", False)
    monkeypatch.setattr(settings, "cloud_model_api_key", "")
    router = ModelRouter()
    router.local.chat = lambda *args, **kwargs: pytest.fail("local provider must not be called")

    result = router.run_task("summarize", "总结这段内容")

    assert result.success is False
    assert result.provider == "router"
    assert "cloud" in (result.error or "").lower()


def test_high_risk_policy_still_requires_confirmation():
    policy = ModelRouter().task_policy("code_review")
    assert policy["requires_confirmation"] is True
    assert policy["risk"] == "high"


def test_low_risk_policy_stays_local():
    policy = ModelRouter().task_policy("daily_log")
    assert policy["provider"] == "local"
    assert policy["requires_confirmation"] is False


def test_route_reason_survives_cloud_upgrade(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "SECRET_VALUE")
    router = ModelRouter()
    router.local.chat = lambda task_type, prompt: ModelResult(False, None, "ollama", "local", error="offline")
    router.cloud._post = lambda *args, **kwargs: httpx.Response(200, json={"choices": [{"message": {"content": "云端结果"}}]})
    result = router.run_task("writing", "写作")
    assert result.route_reason == "local_first_local_unavailable_cloud_fallback"
