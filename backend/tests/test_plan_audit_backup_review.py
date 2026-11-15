from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_goal_stage_edit_delete_and_audit():
    goal = client.post("/api/goals", json={"title": "可编辑目标"}).json()
    updated_goal = client.patch(f"/api/goals/{goal['id']}", json={"title": "更新目标"})
    assert updated_goal.status_code == 200
    assert updated_goal.json()["title"] == "更新目标"
    stage = client.post(f"/api/goals/{goal['id']}/stages", json={"title": "阶段"}).json()
    updated_stage = client.patch(
        f"/api/stages/{stage['id']}",
        json={
            "title": "更新阶段",
            "capability_targets": ["Python 工程化"],
            "prerequisites": ["语法基础"],
        },
    )
    assert updated_stage.status_code == 200
    assert updated_stage.json()["title"] == "更新阶段"
    assert updated_stage.json()["capability_targets"] == ["Python 工程化"]
    assert updated_stage.json()["prerequisites"] == ["语法基础"]
    audits = client.get("/api/audits").json()
    assert any(item["entity_type"] == "goal" and item["action"] == "update" for item in audits)
    assert client.delete(f"/api/goals/{goal['id']}").status_code == 204


def test_backup_preview_and_confirmed_restore():
    client.post("/api/goals", json={"title": "备份目标"})
    backup = client.get("/api/backup/json").json()
    preview = client.post("/api/backup/restore", json={"backup": backup, "confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["restored"] is False
    restored = client.post("/api/backup/restore", json={"backup": backup, "confirmed": True})
    assert restored.status_code == 200
    assert restored.json()["restored"] is True
    assert restored.json()["goals"] >= 1


def test_due_reviews_endpoint_returns_due_review():
    log = client.post("/api/daily-logs", json={"raw_text": "复习 FastAPI", "confirm": True}).json()
    review = client.post(f"/api/daily-logs/{log['id']}/reviews", json={"review_date": date.today().isoformat(), "note": "今日复习"})
    assert review.status_code == 201
    due = client.get("/api/reviews/due").json()
    assert any(item["daily_log_id"] == log["id"] for item in due)
    assert client.patch(f"/api/reviews/{review.json()['id']}", json={"status": "completed"}).status_code == 200
    assert all(item["id"] != review.json()["id"] for item in client.get("/api/reviews/due").json())
