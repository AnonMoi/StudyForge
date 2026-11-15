from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_agent_change_returns_preview_then_executes_create_task():
    preview = client.post("/api/agent/change", json={"operation": "create_task", "payload": {"title": "Agent 创建的任务"}})
    assert preview.status_code == 200
    assert preview.json()["success"] is True
    assert preview.json()["executed"] is False
    assert preview.json()["preview"]["title"] == "Agent 创建的任务"
    assert "impact" in preview.json()["preview"]
    assert preview.json()["preview"]["impact"]["requires_confirmation"] is True

    executed = client.post("/api/agent/change", json={"operation": "create_task", "payload": {"title": "Agent 创建的任务"}, "confirmed": True})
    assert executed.status_code == 200
    assert executed.json()["executed"] is True
    assert executed.json()["result"]["source"] == "agent"
    assert executed.json()["batch_id"]


def test_agent_change_previews_and_executes_completion():
    task = client.post("/api/tasks", json={"title": "待完成任务"}).json()
    preview = client.post("/api/agent/change", json={"operation": "complete_task", "payload": {"task_id": task["id"]}}).json()
    assert preview["executed"] is False
    assert preview["preview"]["to_status"] == "completed"

    executed = client.post("/api/agent/change", json={"operation": "complete_task", "payload": {"task_id": task["id"], "evidence": "完成输出已提交"}, "confirmed": True}).json()
    assert executed["executed"] is True
    assert executed["result"]["status"] == "completed"
    assert executed["batch_id"]


def test_agent_change_batch_can_revert_task_status_and_is_idempotent():
    task = client.post("/api/tasks", json={"title": "可撤销任务"}).json()
    executed = client.post("/api/agent/change", json={"operation": "complete_task", "payload": {"task_id": task["id"], "evidence": "完成输出已提交"}, "confirmed": True}).json()
    batch_id = executed["batch_id"]
    preview = client.post(f"/api/agent/change-batches/{batch_id}/revert", json={"confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["reverted"] is False
    reverted = client.post(f"/api/agent/change-batches/{batch_id}/revert", json={"confirmed": True})
    assert reverted.status_code == 200
    assert reverted.json()["reverted"] is True
    current = next(item for item in client.get("/api/tasks").json() if item["id"] == task["id"])
    assert current["status"] == "not_started"
    repeated = client.post(f"/api/agent/change-batches/{batch_id}/revert", json={"confirmed": True})
    assert repeated.status_code == 200
    assert repeated.json()["already_reverted"] is True


def test_agent_task_status_changes_follow_shared_transition_rules():
    task = client.post("/api/tasks", json={"title": "Agent 状态机任务"}).json()
    completed = client.post(
        "/api/agent/change",
        json={"operation": "complete_task", "payload": {"task_id": task["id"], "evidence": "完成输出已提交"}, "confirmed": True},
    )
    assert completed.status_code == 200
    assert completed.json()["result"]["completed_at"] is not None

    reopened = client.post(
        "/api/agent/change",
        json={"operation": "reopen_task", "payload": {"task_id": task["id"]}, "confirmed": True},
    )
    assert reopened.status_code == 200
    assert reopened.json()["result"]["status"] == "not_started"
    assert reopened.json()["result"]["completed_at"] is None

    invalid = client.post(
        "/api/agent/change",
        json={"operation": "bulk_update_tasks", "payload": {"task_ids": [task["id"]], "status": "needs_review"}, "confirmed": True},
    )
    assert invalid.status_code == 409


def test_agent_bulk_task_status_changes_validate_all_tasks_before_writing():
    first = client.post("/api/tasks", json={"title": "批量任务一"}).json()
    second = client.post("/api/tasks", json={"title": "批量任务二"}).json()
    client.patch(f"/api/tasks/{second['id']}", json={"status": "in_progress"})

    response = client.post(
        "/api/agent/change",
        json={
            "operation": "bulk_update_tasks",
            "payload": {"task_ids": [first["id"], second["id"]], "status": "completed"},
            "confirmed": True,
        },
    )
    assert response.status_code == 409
    tasks = {item["id"]: item for item in client.get("/api/tasks").json()}
    assert tasks[first["id"]]["status"] == "not_started"
    assert tasks[second["id"]]["status"] == "in_progress"


def test_agent_bulk_task_status_change_updates_completion_metadata():
    task = client.post("/api/tasks", json={"title": "批量完成任务"}).json()
    response = client.post(
        "/api/agent/change",
        json={
            "operation": "bulk_update_tasks",
            "payload": {"task_ids": [task["id"]], "status": "completed"},
            "confirmed": True,
        },
    )
    assert response.status_code == 409
    current = next(item for item in client.get("/api/tasks").json() if item["id"] == task["id"])
    assert current["status"] == "not_started"
    assert current["completed_at"] is None


def test_agent_create_project_returns_batch_and_revert_deletes_project():
    executed = client.post(
        "/api/agent/change",
        json={"operation": "create_project", "payload": {"title": "可撤销项目"}, "confirmed": True},
    )
    assert executed.status_code == 200
    data = executed.json()
    assert data["executed"] is True
    assert data["batch_id"]
    project_id = data["result"]["id"]

    reverted = client.post(f"/api/agent/change-batches/{data['batch_id']}/revert", json={"confirmed": True})
    assert reverted.status_code == 200
    assert reverted.json()["deleted_count"] == 1
    assert all(item["id"] != project_id for item in client.get("/api/projects").json())


def test_agent_create_review_returns_batch_and_revert_deletes_review():
    log = client.post("/api/daily-logs", json={"raw_text": "复习测试记录", "confirm": False}).json()
    executed = client.post(
        "/api/agent/change",
        json={
            "operation": "create_review",
            "payload": {"daily_log_id": log["id"], "review_date": "2026-08-13", "note": "Agent 复习"},
            "confirmed": True,
        },
    )
    assert executed.status_code == 200
    data = executed.json()
    assert data["executed"] is True
    assert data["batch_id"]
    review_id = data["result"]["id"]

    reverted = client.post(f"/api/agent/change-batches/{data['batch_id']}/revert", json={"confirmed": True})
    assert reverted.status_code == 200
    assert reverted.json()["deleted_count"] == 1
    assert all(item["id"] != review_id for item in client.get(f"/api/daily-logs/{log['id']}/reviews").json())


def test_agent_create_project_revert_skips_manually_modified_project():
    executed = client.post(
        "/api/agent/change",
        json={"operation": "create_project", "payload": {"title": "冲突项目"}, "confirmed": True},
    ).json()
    project_id = executed["result"]["id"]
    client.patch(f"/api/projects/{project_id}", json={"description": "手动修改"})

    reverted = client.post(f"/api/agent/change-batches/{executed['batch_id']}/revert", json={"confirmed": True})
    assert reverted.status_code == 200
    assert reverted.json()["reverted"] is False
    assert reverted.json()["conflicts"][0]["entity_id"] == project_id
    assert any(item["id"] == project_id for item in client.get("/api/projects").json())


def test_agent_change_rejects_unknown_operation():
    response = client.post("/api/agent/change", json={"operation": "delete_everything", "payload": {}})
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["executed"] is False


def test_agent_change_rejects_task_with_missing_stage():
    response = client.post("/api/agent/change", json={"operation": "create_task", "payload": {"title": "错误阶段任务", "stage_id": 999999}, "confirmed": True})
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["executed"] is False
    assert response.json()["error"] == "阶段不存在"


def test_plan_adjustment_proposes_without_writing_tasks_then_executes_confirmed_changes():
    task = client.post("/api/tasks", json={"title": "逾期任务", "due_date": "2020-01-01", "priority": 4, "estimated_minutes": 45}).json()
    proposal = client.post("/api/agent/plan-adjustment/propose", json={"reason": "本周复盘后调整"})
    assert proposal.status_code == 200
    data = proposal.json()
    assert data["status"] == "pending"
    assert data["requires_confirmation"] is True
    assert data["impact"]["affected_tasks"] == 1
    assert data["changes"][0]["task_id"] == task["id"]
    assert client.get("/api/tasks").json()[0]["due_date"] == "2020-01-01"

    rejected = client.post(f"/api/agent/plan-adjustment/{data['proposal_id']}/execute", json={"confirmed": False}).json()
    assert rejected["executed"] is False
    assert client.get("/api/tasks").json()[0]["due_date"] == "2020-01-01"

    executed = client.post(f"/api/agent/plan-adjustment/{data['proposal_id']}/execute", json={"confirmed": True})
    assert executed.status_code == 200
    executed_data = executed.json()
    assert executed_data["executed"] is True
    assert executed_data["result"]["applied"] == 1
    assert executed_data["batch_id"]
    assert client.get("/api/tasks").json()[0]["due_date"] != "2020-01-01"


def test_plan_adjustment_conflict_does_not_overwrite_manual_task_change():
    task = client.post("/api/tasks", json={"title": "会被手动修改的任务", "due_date": "2020-01-01"}).json()
    proposal = client.post("/api/agent/plan-adjustment/propose", json={}).json()
    client.patch(f"/api/tasks/{task['id']}", json={"due_date": "2020-01-02"})
    result = client.post(f"/api/agent/plan-adjustment/{proposal['proposal_id']}/execute", json={"confirmed": True}).json()
    assert result["executed"] is False
    assert result["result"]["skipped_count"] == 1
    current = next(item for item in client.get("/api/tasks").json() if item["id"] == task["id"])
    assert current["due_date"] == "2020-01-02"
