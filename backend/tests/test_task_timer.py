def test_task_timer_supports_start_pause_resume_stop_and_accumulates(client):
    task = client.post("/api/tasks", json={"title": "计时任务"}).json()
    task_id = task["id"]

    started = client.post(f"/api/tasks/{task_id}/timer/start")
    assert started.status_code == 200
    assert started.json()["state"] == "running"
    assert started.json()["active_entry_id"] is not None

    duplicate_start = client.post(f"/api/tasks/{task_id}/timer/start")
    assert duplicate_start.status_code == 409

    paused = client.post(f"/api/tasks/{task_id}/timer/pause")
    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"
    assert paused.json()["active_entry_id"] is None

    duplicate_pause = client.post(f"/api/tasks/{task_id}/timer/pause")
    assert duplicate_pause.status_code == 409

    resumed = client.post(f"/api/tasks/{task_id}/timer/resume")
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "running"

    stopped = client.post(f"/api/tasks/{task_id}/timer/stop")
    assert stopped.status_code == 200
    assert stopped.json()["state"] == "stopped"
    assert stopped.json()["active_entry_id"] is None

    duplicate_stop = client.post(f"/api/tasks/{task_id}/timer/stop")
    assert duplicate_stop.status_code == 409

    entries = client.get(f"/api/tasks/{task_id}/time-entries")
    assert entries.status_code == 200
    assert len(entries.json()) == 2
    assert {entry["status"] for entry in entries.json()} == {"stopped"}
    assert stopped.json()["accumulated_seconds"] >= 0
    assert client.get("/api/tasks").json()[0]["actual_minutes"] == stopped.json()["actual_minutes"]


def test_task_timer_restores_running_state_from_database(client, db_session):
    task = client.post("/api/tasks", json={"title": "恢复计时任务"}).json()
    task_id = task["id"]
    started = client.post(f"/api/tasks/{task_id}/timer/start").json()
    entry_id = started["active_entry_id"]

    state = client.get(f"/api/tasks/{task_id}/timer")
    assert state.status_code == 200
    assert state.json()["state"] == "running"
    assert state.json()["active_entry_id"] == entry_id

    # A second endpoint call observes the same server-side timer, without relying on browser state.
    refreshed = client.get(f"/api/tasks/{task_id}/timer").json()
    assert refreshed["active_entry_id"] == entry_id
    assert refreshed["accumulated_seconds"] >= refreshed["elapsed_seconds"]


def test_task_timer_requires_valid_operation_order_and_cascades_on_delete(client):
    task = client.post("/api/tasks", json={"title": "操作顺序任务"}).json()
    task_id = task["id"]
    assert client.post(f"/api/tasks/{task_id}/timer/pause").status_code == 409
    assert client.post(f"/api/tasks/{task_id}/timer/resume").status_code == 409
    assert client.post(f"/api/tasks/{task_id}/timer/stop").status_code == 409

    client.post(f"/api/tasks/{task_id}/timer/start")
    client.post(f"/api/tasks/{task_id}/timer/stop")
    assert client.delete(f"/api/tasks/{task_id}").status_code == 204
    assert client.get(f"/api/tasks/{task_id}/time-entries").status_code == 404


def test_task_timer_backup_and_restore_is_idempotent(client):
    task = client.post("/api/tasks", json={"title": "计时备份任务"}).json()
    task_id = task["id"]
    client.post(f"/api/tasks/{task_id}/timer/start")
    client.post(f"/api/tasks/{task_id}/timer/stop")

    backup = client.get("/api/backup/json").json()
    assert len(backup["task_time_entries"]) == 1
    assert backup["task_time_entries"][0]["task_id"] == task_id

    restored = client.post("/api/backup/restore", json={"backup": backup, "confirmed": True})
    assert restored.status_code == 200
    assert restored.json()["skipped_counts"]["task_time_entries"] == 1


def test_task_timer_backup_merge_and_revert_skip_foreign_key(client):
    task = client.post("/api/tasks", json={"title": "计时合并任务"}).json()
    task_id = task["id"]
    client.post(f"/api/tasks/{task_id}/timer/start")
    client.post(f"/api/tasks/{task_id}/timer/stop")
    entry = client.get(f"/api/tasks/{task_id}/time-entries").json()[0]
    backup = {"task_time_entries": [{**entry, "duration_seconds": entry["duration_seconds"] + 1, "task_id": task_id}]}

    preview = client.post("/api/backup/merge", json={"backup": backup, "confirmed": False})
    assert preview.status_code == 200
    patch = preview.json()["preview"]["patches"][0]
    assert "task_id" not in patch["fields"]

    merged = client.post("/api/backup/merge", json={"backup": backup, "confirmed": True})
    assert merged.status_code == 200
    assert merged.json()["affected_records"] == 1
    assert client.get(f"/api/tasks/{task_id}/time-entries").json()[0]["duration_seconds"] == entry["duration_seconds"] + 1

    reverted = client.post(f"/api/backup/merge-batches/{merged.json()['merge_batch_id']}/revert", json={"confirmed": True})
    assert reverted.status_code == 200
    assert reverted.json()["reverted_fields"] >= 1
    assert client.get(f"/api/tasks/{task_id}/time-entries").json()[0]["duration_seconds"] == entry["duration_seconds"]


def test_task_timer_is_included_in_analytics_and_weekly_summary(client):
    task = client.post("/api/tasks", json={"title": "计时统计任务", "week_key": "2026-08-10"}).json()
    task_id = task["id"]
    client.post(f"/api/tasks/{task_id}/timer/start")
    client.post(f"/api/tasks/{task_id}/timer/stop")
    analytics = client.get("/api/analytics/summary").json()
    assert "task_status_counts" in analytics
    weekly = client.get("/api/weekly-plans/2026-08-10/summary")
    assert weekly.status_code == 200
    assert weekly.json()["actual_minutes"] >= 0
