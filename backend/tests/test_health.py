from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_reports_service_ready():
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "learning-workstation"


def test_model_health_reports_local_provider_without_exposing_key():
    response = TestClient(app).get("/api/models/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["local"]["provider"] == "ollama"
    assert "api_key" not in str(payload).lower()


def test_model_health_probes_enabled_cloud_provider_without_exposing_key(monkeypatch):
    from app import main

    class FakeCloud:
        def health_check(self):
            return True

    monkeypatch.setattr(main.settings, "cloud_model_enabled", True)
    monkeypatch.setattr(main.router, "cloud", FakeCloud())
    response = TestClient(app).get("/api/models/health")

    assert response.status_code == 200
    assert response.json()["cloud"]["enabled"] is True
    assert response.json()["cloud"]["available"] is True
    assert "api_key" not in str(response.json()).lower()


def test_model_health_distinguishes_enabled_cloud_without_credentials(monkeypatch):
    from app import main

    monkeypatch.setattr(main.settings, "cloud_model_enabled", True)
    monkeypatch.setattr(main.router, "cloud", None)
    response = TestClient(app).get("/api/models/health")

    assert response.status_code == 200
    assert response.json()["cloud"] == {
        "provider": "zhiapi",
        "model": main.settings.cloud_model_name,
        "enabled": True,
        "configured": False,
        "available": False,
    }


def test_empty_dashboard_is_readable():
    response = TestClient(app).get("/api/dashboard")

    assert response.status_code == 200
    assert response.json()["today_tasks"] == []
    assert response.json()["recent_logs"] == []


def test_create_goal_stage_and_task():
    client = TestClient(app)
    goal = client.post("/api/goals", json={"title": "夯实计算机基础", "description": "建立可迁移基础"})
    assert goal.status_code == 201
    stage = client.post(f"/api/goals/{goal.json()['id']}/stages", json={"title": "Python 工程化", "capability_targets": ["测试"]})
    assert stage.status_code == 201
    task = client.post("/api/tasks", json={"title": "为一个函数补测试", "stage_id": stage.json()["id"], "estimated_minutes": 45})
    assert task.status_code == 201
    assert task.json()["status"] == "not_started"


def test_daily_log_preserves_raw_text_when_model_is_unavailable():
    response = TestClient(app).post("/api/daily-logs", json={"raw_text": "今天学习了 HTTP 请求，花了 40 分钟。"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["raw_text"] == "今天学习了 HTTP 请求，花了 40 分钟。"
    assert payload["structured_status"] in {"pending_review", "parse_failed"}


def test_export_returns_json_payload():
    response = TestClient(app).get("/api/exports/json")

    assert response.status_code == 200
    payload = response.json()
    assert {"goals", "stages", "tasks", "daily_logs"}.issubset(payload)


def test_readable_exports_include_learning_content_in_markdown_txt_and_html(client):
    client.post("/api/goals", json={"title": "导出目标", "description": "可读导出"})
    client.post("/api/daily-logs", json={"raw_text": "完成了导出验收"})
    client.post("/api/notes", json={"title": "导出笔记", "content": "# 重点\n\n正文"})
    for file_format, media_type, expected in [
        ("markdown", "text/markdown", "# 学习工作站导出"),
        ("txt", "text/plain", "导出目标"),
        ("html", "text/html", "导出笔记"),
    ]:
        response = client.get(f"/api/exports/{file_format}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(media_type)
        assert expected in response.text


def test_notes_and_knowledge_topics_can_be_created_and_listed():
    client = TestClient(app)
    note = client.post("/api/notes", json={"title": "HTTP 请求笔记", "content": "请求由客户端发起。", "tags": ["网络"]})
    assert note.status_code == 201
    assert client.get("/api/notes").json()[0]["title"] == "HTTP 请求笔记"
    topic = client.post("/api/knowledge-topics", json={"name": "HTTP", "domain": "计算机网络"})
    assert topic.status_code == 201
    assert client.get("/api/knowledge-topics").json()[0]["name"] == "HTTP"


def test_task_can_be_updated_and_deleted():
    client = TestClient(app)
    created = client.post("/api/tasks", json={"title": "待更新任务", "estimated_minutes": 20})
    assert created.status_code == 201
    task_id = created.json()["id"]
    started = client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
    assert started.status_code == 200
    updated = client.patch(f"/api/tasks/{task_id}", json={"status": "pending_verification", "actual_minutes": 25})
    assert updated.status_code == 200
    verified = client.post(f"/api/tasks/{task_id}/verify", json={"target_status": "completed", "evidence": "专项测试通过", "actual_minutes": 25})
    assert verified.status_code == 200
    assert verified.json()["status"] == "completed"
    assert updated.json()["actual_minutes"] == 25
    deleted = client.delete(f"/api/tasks/{task_id}")
    assert deleted.status_code == 204
    assert all(item["id"] != task_id for item in client.get("/api/tasks").json())
