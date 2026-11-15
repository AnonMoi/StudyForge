import json

import httpx
import pytest

from app.model_routing import ModelResult, ModelRouter, validate_structured_data


def test_validate_structured_data_accepts_daily_log_shape():
    data = validate_structured_data(
        {"topics": ["Python"], "duration_minutes": 30, "outputs": [], "understood": [], "unresolved_questions": [], "self_assessment": None},
        {"topics", "duration_minutes", "outputs", "understood", "unresolved_questions", "self_assessment"},
    )
    assert data["topics"] == ["Python"]


@pytest.mark.parametrize(
    "value",
    [None, [], {"topics": "Python"}, {"duration_minutes": True}, {"confidence": 1.2}, {"evidence": {}}],
)
def test_validate_structured_data_rejects_invalid_shapes(value):
    with pytest.raises(ValueError):
        validate_structured_data(value, {"topics"} if isinstance(value, dict) and "topics" not in value else None)


def test_parse_daily_log_retries_and_falls_back_deterministically(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", False)
    monkeypatch.setattr(settings, "cloud_model_api_key", "")
    monkeypatch.setattr(settings, "model_max_retries", 2)
    router = ModelRouter()
    attempts = []

    def fail(_text):
        attempts.append(True)
        return ModelResult(False, None, "ollama", "local", error="invalid JSON")

    router.local.structured_log = fail
    result = router.parse_daily_log("学习记录")

    assert len(attempts) == 3
    assert result.success is True
    assert result.provider == "deterministic"
    assert result.fallback_used is True
    assert result.retry_count == 2


def test_cloud_fallback_marks_observability(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "secret")
    monkeypatch.setattr(settings, "daily_cloud_call_limit", 20)
    monkeypatch.setattr(settings, "daily_cost_limit", 2.0)
    router = ModelRouter()
    router.local.structured_log = lambda _text: ModelResult(False, None, "ollama", "local", error="offline")

    def post(*_args, **kwargs):
        payload = {"topics": ["Python"], "duration_minutes": None, "outputs": [], "understood": [], "unresolved_questions": [], "self_assessment": None}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    router.cloud._post = post
    result = router.parse_daily_log("学习 Python")

    assert result.success is True
    assert result.fallback_used is True
    assert result.provider == "zhiapi"
