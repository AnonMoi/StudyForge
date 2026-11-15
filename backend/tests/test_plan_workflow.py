from datetime import date

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_plan_workflow_creates_goal_stage_task_and_completes_task():
    goal = client.post("/api/goals", json={"title": "验收目标", "description": "完成学习闭环"})
    assert goal.status_code == 201
    goal_id = goal.json()["id"]

    stage = client.post(f"/api/goals/{goal_id}/stages", json={"title": "第一阶段", "order_index": 1})
    assert stage.status_code == 201
    stage_id = stage.json()["id"]

    task = client.post("/api/tasks", json={"title": "完成第一个任务", "stage_id": stage_id, "status": "not_started"})
    assert task.status_code == 201
    task_id = task.json()["id"]

    completed = client.post(f"/api/tasks/{task_id}/verify", json={"target_status": "completed", "evidence": "完成阶段实践并通过验收"})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert all(item["id"] != task_id for item in dashboard.json()["today_tasks"])


def test_completed_due_today_task_is_removed_from_dashboard_today_tasks():
    task = client.post("/api/tasks", json={"title": "今天完成", "due_date": date.today().isoformat()}).json()
    assert any(item["id"] == task["id"] for item in client.get("/api/dashboard").json()["today_tasks"])
    client.post(f"/api/tasks/{task['id']}/verify", json={"target_status": "completed", "evidence": "今日输出已保存"})
    dashboard_tasks = client.get("/api/dashboard").json()["today_tasks"]
    assert all(item["id"] != task["id"] for item in dashboard_tasks)


def test_plan_workflow_rejects_missing_stage():
    response = client.post("/api/tasks", json={"title": "孤儿任务", "stage_id": 999999})
    assert response.status_code == 404


def test_public_settings_never_expose_key_material(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_api_key", "")
    response = client.get("/api/settings/public")
    assert response.status_code == 200
    payload = response.json()
    assert "cloud_key" not in payload
    assert "cloud_key_configured" in payload
    assert all(not isinstance(value, str) or "sk-" not in value for value in payload.values())
