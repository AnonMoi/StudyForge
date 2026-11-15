from datetime import date

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_global_search_covers_learning_entities_and_imported_files(tmp_path):
    document = tmp_path / "fastapi.md"
    document.write_text("# FastAPI\n依赖注入和路由测试", encoding="utf-8")
    directory = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    client.post("/api/authorized-directories/%s/scan" % directory["id"])
    client.post("/api/tasks", json={"title": "FastAPI 测试任务"})
    client.post("/api/daily-logs", json={"raw_text": "今天复习 FastAPI 依赖注入"})
    client.post("/api/notes", json={"title": "FastAPI 笔记", "content": "依赖注入"})
    client.post("/api/knowledge-topics", json={"name": "FastAPI", "domain": "后端开发"})
    client.post("/api/projects", json={"title": "FastAPI 学习项目"})

    response = client.get("/api/search", params={"q": "FastAPI", "limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 6
    assert {"tasks", "daily_logs", "notes", "topics", "projects", "imports"}.issubset(payload["grouped"])
    assert any(item["route"] == "knowledge" for item in payload["results"])
    assert any(item["title"] == "fastapi.md" for item in payload["grouped"]["imports"])


def test_dashboard_exposes_review_signals_projects_notes_capabilities_and_suggestions():
    project = client.post("/api/projects", json={"title": "进行中的项目", "status": "in_progress"}).json()
    note = client.post("/api/notes", json={"title": "最近笔记", "content": "记录"}).json()
    topic = client.post("/api/knowledge-topics", json={"name": "待复习主题", "verified_level": 1}).json()
    log = client.post("/api/daily-logs", json={"raw_text": "学习记录", "topic_ids": [topic["id"]]}).json()
    review = client.post(f"/api/daily-logs/{log['id']}/reviews", json={"review_date": date.today().isoformat(), "topic_id": topic["id"]})
    assert review.status_code == 201
    client.post("/api/capabilities/assess")

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert any(item["id"] == project["id"] for item in payload["active_projects"])
    assert any(item["id"] == note["id"] for item in payload["recent_notes"])
    assert any(item["id"] == review.json()["id"] for item in payload["due_reviews"])
    assert "agent_suggestions" in payload
    assert isinstance(payload["agent_suggestions"], list)
