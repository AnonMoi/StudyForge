from datetime import date, timedelta


def test_weekly_plan_create_update_and_summary(client):
    week_key = date.today() - timedelta(days=date.today().weekday())
    created = client.post("/api/weekly-plans", json={"week_key": week_key.isoformat(), "objective": "完成本周学习闭环", "expected_outputs": ["一份总结", "一次练习"]})
    assert created.status_code == 201
    assert created.json()["objective"] == "完成本周学习闭环"

    duplicate = client.post("/api/weekly-plans", json={"week_key": week_key.isoformat()})
    assert duplicate.status_code == 409

    updated = client.patch(f"/api/weekly-plans/{created.json()['id']}", json={"reflection": "完成了主要实践", "blockers": "时间不足"})
    assert updated.status_code == 200
    assert updated.json()["reflection"] == "完成了主要实践"

    task = client.post("/api/tasks", json={"title": "本周任务", "week_key": week_key.isoformat(), "estimated_minutes": 45})
    assert task.status_code == 201
    client.patch(f"/api/tasks/{task.json()['id']}", json={"status": "pending_verification", "actual_minutes": 40})
    client.post(f"/api/tasks/{task.json()['id']}/verify", json={"target_status": "completed", "evidence": "本周产出已提交", "actual_minutes": 40})

    summary = client.get(f"/api/weekly-plans/{week_key.isoformat()}/summary")
    assert summary.status_code == 200
    assert summary.json()["task_count"] == 1
    assert summary.json()["completed_count"] == 1
    assert summary.json()["completion_rate"] == 100.0
    assert summary.json()["estimated_minutes"] == 45
    assert summary.json()["actual_minutes"] == 40


def test_weekly_plan_missing_returns_not_found(client):
    response = client.get("/api/weekly-plans/2099-01-03")
    assert response.status_code == 404
