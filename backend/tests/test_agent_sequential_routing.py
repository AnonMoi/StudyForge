import httpx
import pytest

from app.config import settings
from app.model_routing import ModelResult, ModelRouter


class FakeCloud:
    provider = "cloud"

    def __init__(self, events, result=None):
        self.events = events
        self.result = result or ModelResult(True, None, "cloud", "test-cloud", text="云端完整回复")

    def chat(self, task_type, prompt, *, cancel_token=None):
        self.events.append("cloud:start")
        return self.result


def configured_router(monkeypatch, events):
    monkeypatch.setattr(settings, "model_routing_mode", "local_first")
    router = ModelRouter()
    router.cloud = FakeCloud(events)
    router._record = lambda *args, **kwargs: None
    router._budget_available = lambda: True
    return router


@pytest.mark.asyncio
async def test_local_success_finishes_before_cloud_is_considered(monkeypatch):
    events = []
    router = configured_router(monkeypatch, events)

    def local_stream(task_type, prompt, *, cancel_token=None):
        events.append("local:start")
        yield "本地"
        yield "完整回复"
        events.append("local:done")

    router.local.stream_chat = local_stream
    result = await router.execute_stream("teaching", "解释事务", turn_id="local-success")
    assert result.success is True
    assert result.text == "本地完整回复"
    assert result.provider == "ollama"
    assert events == ["local:start", "local:done"]
    assert [attempt.stage for attempt in result.attempts] == ["local"]


@pytest.mark.asyncio
async def test_timeout_then_cloud_is_strictly_sequential(monkeypatch):
    events = []
    router = configured_router(monkeypatch, events)

    def timed_out_stream(task_type, prompt, *, cancel_token=None):
        events.extend(["local:start", "local:timeout"])
        raise httpx.ReadTimeout("timed out")
        yield

    router.local.stream_chat = timed_out_stream
    result = await router.execute_stream("teaching", "解释事务", turn_id="fallback")
    assert result.text == "云端完整回复"
    assert events == ["local:start", "local:timeout", "cloud:start"]
    assert result.route_reason == "local_first_local_unavailable_cloud_fallback"
    assert [attempt.stage for attempt in result.attempts] == ["local", "cloud"]
    assert result.attempts[0].finished_at <= result.attempts[1].started_at


@pytest.mark.asyncio
async def test_partial_local_output_is_discarded_before_cloud_fallback(monkeypatch):
    events = []
    router = configured_router(monkeypatch, events)

    def interrupted_stream(task_type, prompt, *, cancel_token=None):
        events.append("local:start")
        yield "不应显示的半句"
        events.append("local:timeout")
        raise httpx.ReadTimeout("timed out")

    router.local.stream_chat = interrupted_stream
    result = await router.execute_stream("teaching", "解释事务", turn_id="discard-partial")
    assert result.text == "云端完整回复"
    assert "不应显示" not in (result.text or "")
    assert events == ["local:start", "local:timeout", "cloud:start"]


@pytest.mark.asyncio
async def test_malformed_local_response_does_not_upload_to_cloud(monkeypatch):
    events = []
    router = configured_router(monkeypatch, events)

    def malformed_stream(task_type, prompt, *, cancel_token=None):
        events.append("local:start")
        raise ValueError("malformed local payload")
        yield

    router.local.stream_chat = malformed_stream
    result = await router.execute_stream("teaching", "解释事务", turn_id="malformed")
    assert result.success is False
    assert result.failure_kind == "response_error"
    assert events == ["local:start"]


@pytest.mark.asyncio
async def test_both_paths_fail_produce_no_assistant_content(monkeypatch):
    events = []
    cloud_failure = ModelResult(False, None, "cloud", "test-cloud", error="cloud unavailable", failure_kind="unavailable")
    router = configured_router(monkeypatch, events)
    router.cloud = FakeCloud(events, cloud_failure)

    def unavailable_stream(task_type, prompt, *, cancel_token=None):
        events.append("local:start")
        raise httpx.ConnectError("offline")
        yield

    router.local.stream_chat = unavailable_stream
    result = await router.execute_stream("teaching", "解释事务", turn_id="both-fail")
    assert result.success is False
    assert result.text is None
    assert events == ["local:start", "cloud:start"]
