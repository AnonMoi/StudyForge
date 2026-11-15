import json

import httpx

from app.model_routing import ModelResult, ModelRouter


def test_task_policy_assigns_local_and_cloud_roles(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "SECRET_VALUE")
    router = ModelRouter()

    assert router.task_policy("daily_log")["provider"] == "local"
    assert router.task_policy("daily_log")["risk"] == "low"
    assert router.task_policy("daily_log")["requires_confirmation"] is False
    assert router.task_policy("daily_log")["reason"]
    for task_type, providers, risk, confirmation in [
        ("format_note", {"local"}, "low", False),
        ("learning_plan", {"local_first"}, "medium", False),
        ("writing", {"local_first"}, "medium", False),
        ("code_review", {"cloud"}, "high", True),
    ]:
        policy = router.task_policy(task_type)
        assert policy["provider"] in providers
        assert policy["risk"] == risk
        assert policy["requires_confirmation"] is confirmation
        assert policy["reason"]


def test_writing_task_uses_cloud_when_enabled(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", True)
    monkeypatch.setattr(settings, "cloud_model_api_key", "SECRET_VALUE")
    router = ModelRouter()
    router.local.chat = lambda task_type, prompt: ModelResult(False, None, "ollama", "local", error="local unavailable")

    def handler(*args, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer SECRET_VALUE"
        assert "SECRET_VALUE" not in json.dumps(kwargs["json"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "云端写作草稿"}}]})

    router.cloud._post = handler
    result = router.run_task("writing", "请把这段学习记录整理成一篇技术总结")

    assert result.success is True
    assert result.provider == "zhiapi"
    assert result.text == "云端写作草稿"


def test_writing_task_stays_local_when_cloud_is_disabled(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_enabled", False)
    monkeypatch.setattr(settings, "cloud_model_api_key", "")
    router = ModelRouter()
    router.local.chat = lambda task_type, prompt: ModelResult(False, None, "ollama", "local", error="offline")
    result = router.run_task("writing", "写一篇总结")

    assert result.success is False
    assert result.provider == "ollama"
    assert "local" in (result.error or "").lower()
