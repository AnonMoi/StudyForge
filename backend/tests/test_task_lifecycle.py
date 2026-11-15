from datetime import date


def test_task_statuses_and_verification_flow(client):
    task_response = client.post(
        "/api/tasks",
        json={
            "title": "生命周期任务",
            "status": "not_started",
            "acceptance_criteria": "输出测试结果",
        },
    )
    assert task_response.status_code == 201
    task = task_response.json()
    assert task["completed_at"] is None

    started = client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"})
    assert started.status_code == 200

    pending = client.patch(f"/api/tasks/{task['id']}", json={"status": "pending_verification"})
    assert pending.status_code == 200

    verified = client.post(
        f"/api/tasks/{task['id']}/verify",
        json={
            "target_status": "completed",
            "evidence": "pytest 通过 10 个测试",
            "note": "完成验收",
            "actual_minutes": 45,
        },
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "completed"
    assert verified.json()["actual_minutes"] == 45
    assert verified.json()["completed_at"] is not None
    assert verified.json()["last_verified_at"] is not None

    history = client.get(f"/api/tasks/{task['id']}/verifications")
    assert history.status_code == 200
    assert history.json()[0]["evidence"] == "pytest 通过 10 个测试"


def test_task_rejects_invalid_status_and_transition(client):
    invalid = client.post("/api/tasks", json={"title": "非法状态", "status": "blocked"})
    assert invalid.status_code == 422

    task = client.post("/api/tasks", json={"title": "非法跳转"}).json()
    response = client.patch(f"/api/tasks/{task['id']}", json={"status": "needs_review"})
    assert response.status_code == 422


def test_task_needs_review_sets_next_review_date(client):
    task = client.post("/api/tasks", json={"title": "复习任务", "status": "in_progress"}).json()
    pending = client.patch(f"/api/tasks/{task['id']}", json={"status": "pending_verification"})
    assert pending.status_code == 200
    response = client.post(
        f"/api/tasks/{task['id']}/verify",
        json={"target_status": "needs_review", "evidence": "能复现问题但仍有一个边界用例未覆盖"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "needs_review"
    assert response.json()["next_review_date"] == date.today().isoformat()


def test_weekly_summary_counts_mastered_tasks_as_completed(client):
    task = client.post(
        "/api/tasks",
        json={"title": "已掌握任务", "week_key": "2026-08-10", "status": "not_started"},
    ).json()
    client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"})
    client.patch(f"/api/tasks/{task['id']}", json={"status": "pending_verification"})
    verified = client.post(
        f"/api/tasks/{task['id']}/verify",
        json={"target_status": "mastered", "evidence": "独立完成并讲解"},
    )
    assert verified.status_code == 200
    summary = client.get("/api/weekly-plans/2026-08-10/summary")
    assert summary.status_code == 200
    assert summary.json()["completed_count"] == 1
