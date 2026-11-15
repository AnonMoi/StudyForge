from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_backup_snapshot_is_deduplicated_and_can_be_compared():
    first = client.post("/api/backup/snapshots", json={"label": "版本一"})
    assert first.status_code == 200
    snapshot = first.json()["snapshot"]
    duplicate = client.post("/api/backup/snapshots", json={"label": "重复版本"})
    assert duplicate.status_code == 200
    assert duplicate.json()["reused"] is True
    second = client.post("/api/backup/snapshots", json={"label": "版本二", "backup": {"goals": [{"title": "新增目标"}]}})
    assert second.status_code == 200
    second_id = second.json()["snapshot"]["id"]
    diff = client.get("/api/backup/diff", params={"left_id": snapshot["id"], "right_id": second_id})
    assert diff.status_code == 200
    assert diff.json()["diff"]["goals"]["added"] == 1


def test_restore_batch_can_be_previewed_and_reverted_without_touching_existing_data():
    existing = client.post("/api/goals", json={"title": "原有目标"}).json()
    preview = client.post("/api/backup/restore", json={"backup": {"goals": [{"title": "恢复目标"}]}, "confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["reversible"] is True
    restored = client.post("/api/backup/restore", json={"backup": {"goals": [{"title": "恢复目标"}]}, "confirmed": True})
    assert restored.status_code == 200
    batch_id = restored.json()["restore_batch_id"]
    assert restored.json()["created_ids"]["goals"]
    assert any(item["title"] == "恢复目标" for item in client.get("/api/goals").json())

    revert_preview = client.post(f"/api/backup/restore-batches/{batch_id}/revert", json={"confirmed": False})
    assert revert_preview.status_code == 200
    assert revert_preview.json()["requires_confirmation"] is True
    reverted = client.post(f"/api/backup/restore-batches/{batch_id}/revert", json={"confirmed": True})
    assert reverted.status_code == 200
    titles = {item["title"] for item in client.get("/api/goals").json()}
    assert titles == {existing["title"]}

    repeated = client.post(f"/api/backup/restore-batches/{batch_id}/revert", json={"confirmed": True})
    assert repeated.status_code == 200
    assert repeated.json()["already_reverted"] is True


def test_restore_revert_skips_a_record_modified_after_restore():
    restored = client.post("/api/backup/restore", json={"backup": {"goals": [{"title": "修改保护目标", "description": "初始描述"}]}, "confirmed": True})
    assert restored.status_code == 200
    batch_id = restored.json()["restore_batch_id"]
    goal_id = restored.json()["created_ids"]["goals"][0]
    updated = client.patch(f"/api/goals/{goal_id}", json={"description": "恢复后修改"})
    assert updated.status_code == 200

    reverted = client.post(f"/api/backup/restore-batches/{batch_id}/revert", json={"confirmed": True})
    assert reverted.status_code == 200
    assert reverted.json()["reverted"] is False
    assert reverted.json()["conflicts"][0]["entity_id"] == goal_id
    assert any(item["id"] == goal_id for item in client.get("/api/goals").json())


def test_full_backup_includes_task_verifications_and_restore_is_idempotent():
    task = client.post("/api/tasks", json={"title": "备份验收任务"}).json()
    client.post(
        f"/api/tasks/{task['id']}/verify",
        json={"target_status": "completed", "evidence": "专项测试通过", "note": "备份验证", "actual_minutes": 30},
    )
    backup = client.get("/api/backup/json").json()
    assert len(backup["task_verifications"]) == 1
    assert backup["task_verifications"][0]["evidence"] == "专项测试通过"
    assert backup["tasks"][0]["completed_at"] is not None

    restored = client.post("/api/backup/restore", json={"backup": backup, "confirmed": True})
    assert restored.status_code == 200
    assert restored.json()["restored_counts"]["task_verifications"] == 0
    assert restored.json()["skipped_counts"]["task_verifications"] == 1


def test_full_backup_includes_import_layers_chat_history_and_model_calls(tmp_path):
    from app.file_import import FileAnalysis, FileImport, ImportedFile
    from app.agent_models import ChatMessage
    from app.models import ModelCallLog
    from app.db import SessionLocal

    directory = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    db = SessionLocal()
    import_row = FileImport(directory_id=directory["id"], files=[{"relative_path": "lesson.md"}], files_scanned=1)
    db.add(import_row)
    db.flush()
    imported = ImportedFile(import_id=import_row.id, relative_path="lesson.md", original_path=str(tmp_path / "lesson.md"), sha256="a" * 64, size=12, content_status="imported", content="内容")
    db.add(imported)
    db.flush()
    db.add(FileAnalysis(imported_file_id=imported.id, provider="local_index", model_name="none", result={"topics": ["主题"]}, confirmed=True))
    db.add(ChatMessage(session_id="session-test", role="user", content="学习记录"))
    db.add(ModelCallLog(task_type="summary", risk_level="low", provider="ollama", model_name="local", success=True, token_source="estimated"))
    db.commit()

    backup = client.get("/api/backup/json")
    assert backup.status_code == 200
    data = backup.json()
    assert len(data["file_imports"]) == 1
    # File正文和分析结果不再进入 SQLite 备份 payload；备份仅保留分层存储引用。
    assert "content" not in data["imported_files"][0]
    assert data["file_analyses"][0]["result_file_path"] is None
    assert data["file_analyses"][0]["result_sha256"] is None
    assert data["chat_messages"][0]["session_id"] == "session-test"
    assert data["model_calls"][0]["token_source"] == "estimated"


def test_restore_extended_records_is_idempotent_and_reversible():
    backup = {
        "chat_messages": [{"session_id": "restore-session", "role": "assistant", "content": "恢复内容"}],
        "model_calls": [{"task_type": "restore-test", "risk_level": "low", "provider": "ollama", "model_name": "local", "success": True}],
    }
    preview = client.post("/api/backup/restore", json={"backup": backup, "confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["preview"]["chat_messages"] == 1
    restored = client.post("/api/backup/restore", json={"backup": backup, "confirmed": True})
    assert restored.status_code == 200
    assert restored.json()["restored_counts"]["chat_messages"] == 1
    batch_id = restored.json()["restore_batch_id"]
    repeated = client.post("/api/backup/restore", json={"backup": backup, "confirmed": True})
    assert repeated.status_code == 200
    assert repeated.json()["skipped_counts"]["chat_messages"] == 1
    reverted = client.post(f"/api/backup/restore-batches/{batch_id}/revert", json={"confirmed": True})
    assert reverted.status_code == 200
    assert reverted.json()["deleted_counts"]["chat_messages"] == 1


def test_field_level_diff_reports_record_and_field_changes():
    first = client.post("/api/backup/snapshots", json={"label": "旧版本", "backup": {"tasks": [{"id": 1, "title": "任务A", "priority": 3, "status": "not_started"}]}}).json()["snapshot"]
    second = client.post("/api/backup/snapshots", json={"label": "新版本", "backup": {"tasks": [{"id": 1, "title": "任务A", "priority": 5, "status": "completed"}]}}).json()["snapshot"]
    response = client.get("/api/backup/diff/fields", params={"left_id": first["id"], "right_id": second["id"]})
    assert response.status_code == 200
    data = response.json()
    changed = data["records"]["tasks"][0]
    assert changed["kind"] == "changed"
    fields = {item["field"]: item for item in changed["fields"]}
    assert fields["priority"]["before"] == 3 and fields["priority"]["after"] == 5
    assert data["summary"]["tasks"]["changed"] == 1


def test_merge_preview_requires_confirmation_and_merge_applies_only_backup_fields():
    client.post("/api/tasks", json={"title": "已有任务", "priority": 3, "status": "not_started"})
    task = client.get("/api/tasks").json()[0]
    backup = {"tasks": [{"id": task["id"], "title": "已有任务", "priority": 5, "status": "completed"}]}

    preview = client.post("/api/backup/merge", json={"backup": backup, "confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["applied"] is False
    assert preview.json()["requires_confirmation"] is True
    assert preview.json()["preview"]["affected_records"] == 1
    assert client.get("/api/tasks").json()[0]["priority"] == 3

    merged = client.post("/api/backup/merge", json={"backup": backup, "confirmed": True})
    assert merged.status_code == 200
    assert merged.json()["applied"] is True
    current = client.get("/api/tasks").json()[0]
    assert current["priority"] == 5 and current["status"] == "completed"
