from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_analytics_returns_trends_topics_capabilities_and_usage():
    topic = client.post("/api/knowledge-topics", json={"name": "阶段七主题", "domain": "后端开发"}).json()
    task = client.post("/api/tasks", json={"title": "完成阶段七主题", "topic_id": topic["id"], "actual_minutes": 35}).json()
    client.post(f"/api/tasks/{task['id']}/verify", json={"target_status": "completed", "evidence": "阶段七主题实践输出", "actual_minutes": 35})
    client.post("/api/daily-logs", json={"raw_text": "完成阶段七主题", "confirm": True, "extracted_topics": ["后端开发"], "extracted_duration": 20, "extracted_outputs": ["统计"]})
    response = client.get("/api/analytics/summary?days=14")
    assert response.status_code == 200
    data = response.json()
    assert len(data["daily"]) == 14
    assert any(item["name"] == "阶段七主题" for item in data["topics"])
    assert {"actual_tokens", "estimated_tokens", "estimated_cost"}.issubset(data["model_calls"])


def test_field_diff_counts_unchanged_and_merge_selection_is_reversible():
    task = client.post("/api/tasks", json={"title": "可选择合并任务", "priority": 3}).json()
    backup = {"tasks": [{"id": task["id"], "title": task["title"], "priority": 5, "status": "completed"}]}
    preview = client.post("/api/backup/merge", json={"backup": backup, "confirmed": False}).json()
    patch = preview["preview"]["patches"][0]
    assert {"priority", "status"}.issubset({item["field"] for item in patch["conflicts"]})
    merged = client.post("/api/backup/merge", json={"backup": backup, "confirmed": True, "selections": [{"entity_type": "tasks", "match_key": task["id"], "fields": ["priority"]}]}).json()
    assert merged["applied"] is True
    assert merged["merge_batch_id"]
    current = next(item for item in client.get("/api/tasks").json() if item["id"] == task["id"])
    assert current["priority"] == 5 and current["status"] == "not_started"
    reverted = client.post(f"/api/backup/merge-batches/{merged['merge_batch_id']}/revert", json={"confirmed": True}).json()
    assert reverted["reverted"] is True
    current = next(item for item in client.get("/api/tasks").json() if item["id"] == task["id"])
    assert current["priority"] == 3
