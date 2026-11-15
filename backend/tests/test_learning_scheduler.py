from datetime import date


def test_learning_reminders_cover_daily_weekly_and_stage_signals_and_are_idempotent(client):
    log = client.post(
        "/api/daily-logs",
        json={"raw_text": "准备验证提醒调度", "confirm": True},
    ).json()
    review = client.post(
        f"/api/daily-logs/{log['id']}/reviews",
        json={"review_date": date.today().isoformat(), "note": "检查关键概念"},
    )
    assert review.status_code == 201

    goal = client.post("/api/goals", json={"title": "提醒调度目标"}).json()
    stage = client.post(
        f"/api/goals/{goal['id']}/stages",
        json={"title": "提醒调度阶段"},
    ).json()
    task = client.post(
        "/api/tasks",
        json={"title": "待完成阶段任务", "stage_id": stage["id"], "due_date": date.today().isoformat()},
    )
    assert task.status_code == 201

    refreshed = client.post("/api/reminders/refresh")
    assert refreshed.status_code == 200
    reminders = refreshed.json()["reminders"]
    assert {item["reminder_type"] for item in reminders} == {"daily_review", "weekly_review", "stage_check"}
    assert all(item["status"] == "pending" for item in reminders)

    repeated = client.post("/api/reminders/refresh")
    assert repeated.status_code == 200
    assert len(repeated.json()["reminders"]) == len(reminders)
    assert {item["id"] for item in repeated.json()["reminders"]} == {item["id"] for item in reminders}

    acknowledged = client.post(f"/api/reminders/{reminders[0]['id']}/acknowledge")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "acknowledged"
    pending = client.get("/api/reminders").json()["reminders"]
    assert reminders[0]["id"] not in {item["id"] for item in pending}


def test_learning_reminders_do_not_create_records_without_source_signals(client):
    refreshed = client.post("/api/reminders/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["reminders"] == []
    assert client.get("/api/reviews/due").json() == []


def test_runtime_status_exposes_scheduler_health_without_secrets(client):
    response = client.get("/api/runtime/status")
    assert response.status_code == 200
    payload = response.json()
    assert {"scheduler", "api_workers"}.issubset(payload)
    assert {"state", "thread_alive", "interval_seconds", "last_tick_at", "last_error", "ticks"}.issubset(payload["scheduler"])
    assert "cloud_sync_password" not in str(payload)
