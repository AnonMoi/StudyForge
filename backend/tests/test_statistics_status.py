from datetime import date

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_completed_task_is_counted_in_analytics_summary():
    task = client.post(
        "/api/tasks",
        json={"title": "统计完成任务", "due_date": date.today().isoformat()},
    ).json()
    client.post(f"/api/tasks/{task['id']}/verify", json={"target_status": "completed", "evidence": "统计测试输出已完成"})

    summary = client.get("/api/analytics/summary")

    assert summary.status_code == 200
    assert summary.json()["completed_tasks"] == 1


def test_mastered_legacy_status_is_still_counted():
    task = client.post("/api/tasks", json={"title": "历史 mastered 任务"}).json()
    client.post(f"/api/tasks/{task['id']}/verify", json={"target_status": "mastered", "evidence": "独立完成并讲解"})

    assert client.get("/api/analytics/summary").json()["completed_tasks"] == 1


def test_pending_task_is_not_counted_as_completed():
    client.post("/api/tasks", json={"title": "待完成任务"})

    summary = client.get("/api/analytics/summary").json()
    assert summary["completed_tasks"] == 0
    assert summary["task_status_counts"]["not_started"] >= 1


def test_needs_review_and_pending_verification_are_not_counted_as_completed():
    review_task = client.post("/api/tasks", json={"title": "需要复习任务"}).json()
    pending_task = client.post("/api/tasks", json={"title": "待验收任务"}).json()
    client.patch(f"/api/tasks/{review_task['id']}", json={"status": "in_progress"})
    client.patch(f"/api/tasks/{review_task['id']}", json={"status": "pending_verification"})
    client.post(
        f"/api/tasks/{review_task['id']}/verify",
        json={"target_status": "needs_review", "evidence": "证据"},
    )
    client.patch(f"/api/tasks/{pending_task['id']}", json={"status": "in_progress"})
    client.patch(f"/api/tasks/{pending_task['id']}", json={"status": "pending_verification"})

    summary = client.get("/api/analytics/summary").json()
    assert summary["completed_tasks"] == 0
    assert summary["task_status_counts"]["needs_review"] >= 1
    assert summary["task_status_counts"]["pending_verification"] >= 1
