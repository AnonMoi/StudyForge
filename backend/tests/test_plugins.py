import json

from app.model_routing import ModelResult


def manifest():
    return {
        "id": "focus-tools",
        "name": "专注工具",
        "version": "1.0.0",
        "description": "用于学习材料整理。",
        "permissions": ["model_task"],
        "commands": [{
            "id": "summarize",
            "title": "整理摘要",
            "description": "整理输入内容",
            "task_type": "summarize",
            "prompt_template": "请整理：{{input}}",
        }],
    }


def test_invalid_plugin_manifest_is_rejected(client):
    response = client.post("/api/plugins/install", json={"manifest": {"id": "Bad ID"}})
    assert response.status_code == 422


def test_plugin_install_preview_does_not_write(client):
    preview = client.post("/api/plugins/install", json={"manifest": manifest()})
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    assert client.get("/api/plugins").json() == []


def test_plugin_install_toggle_and_delete_follow_confirmation(client):
    installed = client.post("/api/plugins/install", json={"manifest": manifest(), "confirmed": True})
    assert installed.status_code == 200
    assert installed.json()["plugin"]["enabled"] is True
    assert client.get("/api/plugins").json()[0]["manifest"]["id"] == "focus-tools"

    disabled = client.patch("/api/plugins/focus-tools", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["plugin"]["enabled"] is False

    preview = client.request("DELETE", "/api/plugins/focus-tools", json={"confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    assert client.get("/api/plugins").json()

    deleted = client.request("DELETE", "/api/plugins/focus-tools", json={"confirmed": True})
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get("/api/plugins").json() == []


def test_plugin_command_requires_confirmation_and_uses_router(client, monkeypatch):
    assert client.post("/api/plugins/install", json={"manifest": manifest(), "confirmed": True}).status_code == 200
    calls = []

    def fake_run_task(task_type, prompt, confirmed=False):
        calls.append((task_type, prompt, confirmed))
        return ModelResult(True, {"kind": "summary"}, "local", "test-model", text="完成摘要")

    monkeypatch.setattr("app.main.router.run_task", fake_run_task)
    secret_input = "包含用户输入的内容，不应写入审计"
    preview = client.post(
        "/api/plugins/focus-tools/commands/summarize/run",
        json={"user_input": secret_input, "confirmed": False},
    )
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    assert calls == []

    result = client.post(
        "/api/plugins/focus-tools/commands/summarize/run",
        json={"user_input": secret_input, "confirmed": True},
    )
    assert result.status_code == 200
    assert result.json()["success"] is True
    assert calls == [("summarize", f"请整理：{secret_input}", True)]

    audit_text = json.dumps(client.get("/api/audits").json(), ensure_ascii=False)
    assert secret_input not in audit_text


def test_disabled_plugin_command_is_not_runnable(client):
    assert client.post("/api/plugins/install", json={"manifest": manifest(), "confirmed": True}).status_code == 200
    assert client.patch("/api/plugins/focus-tools", json={"enabled": False}).status_code == 200
    response = client.post("/api/plugins/focus-tools/commands/summarize/run", json={"confirmed": False})
    assert response.status_code == 409
