from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.model_routing import ModelResult


client = TestClient(app)


def test_text_import_persists_content_and_searches(tmp_path: Path):
    document = tmp_path / "lesson.md"
    document.write_text("# FastAPI\n路由和依赖注入", encoding="utf-8")
    auth = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()

    report = client.post(f"/api/authorized-directories/{auth['id']}/scan").json()
    item = report["files"][0]
    assert item["content_status"] == "imported"
    assert "依赖注入" in item["content"]
    integrity = client.get("/api/imports/integrity")
    assert integrity.status_code == 200
    assert integrity.json()["counts"]["healthy"] == 1
    assert integrity.json()["files"][0]["content_exists"] is True

    results = client.get("/api/imports/search", params={"q": "依赖注入"})
    assert results.status_code == 200
    assert results.json()["matches"][0]["relative_path"] == "lesson.md"


def test_scanning_specific_file_does_not_scan_other_files(tmp_path: Path):
    (tmp_path / "first.md").write_text("first", encoding="utf-8")
    (tmp_path / "second.md").write_text("second", encoding="utf-8")
    auth = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()

    response = client.post(f"/api/authorized-directories/{auth['id']}/scan", json={"path": "first.md"})
    assert response.status_code == 200
    assert [item["relative_path"] for item in response.json()["files"]] == ["first.md"]


def test_confirm_import_creates_topics_and_source_note_idempotently(tmp_path: Path):
    document = tmp_path / "fastapi-basics.md"
    document.write_text("# FastAPI\n\n依赖注入让路由更容易测试。", encoding="utf-8")
    auth = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    report = client.post(f"/api/authorized-directories/{auth['id']}/scan").json()
    import_id = report["import_id"]

    preview = client.post(f"/api/imports/{import_id}/confirm", json={"confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["executed"] is False
    assert preview.json()["preview"][0]["suggested_topics"]

    confirmed = client.post(f"/api/imports/{import_id}/confirm", json={"confirmed": True})
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["confirmed_files"] == 1
    assert body["created_topics"] >= 1
    assert body["created_notes"] == 1
    imported_files = client.get(f"/api/imports/{import_id}/files").json()
    assert imported_files[0]["content_file_path"].startswith("imports/content/")
    assert imported_files[0]["index_status"] == "valid"
    assert body["topic_ids"]
    assert body["note_ids"]

    topics = client.get("/api/knowledge-topics").json()
    notes = client.get("/api/notes").json()
    assert any(topic["name"] == "FastAPI" for topic in topics)
    assert any(note["source_path"].endswith("fastapi-basics.md") for note in notes)

    repeated = client.post(f"/api/imports/{import_id}/confirm", json={"confirmed": True})
    assert repeated.status_code == 200
    assert repeated.json()["confirmed_files"] == 0
    assert repeated.json()["reused_files"] == 1
    assert len(client.get("/api/notes").json()) == 1


def test_cloud_analysis_requires_confirmation_and_sends_redacted_truncated_content(tmp_path: Path, monkeypatch):
    document = tmp_path / "lesson.md"
    document.write_text("token=SECRET_VALUE\n邮箱 test@example.com\n" + ("正文" * 70_000), encoding="utf-8")
    auth = client.post("/api/authorized-directories", json={"path": str(tmp_path), "cloud_transfer": True}).json()
    captured: dict[str, str] = {}

    preview = client.post(f"/api/authorized-directories/{auth['id']}/cloud-analysis", json={"path": "lesson.md", "prompt": "请总结", "confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    assert "绝对路径" in preview.json()["warning"]

    def fake_run_task(task_type: str, prompt: str, confirmed: bool = False):
        captured["task_type"] = task_type
        captured["prompt"] = prompt
        assert confirmed is True
        return ModelResult(True, None, "zhiapi", "cloud-test", text="已分析", route_reason="test")

    monkeypatch.setattr("app.file_import.model_router.run_task", fake_run_task)
    response = client.post(f"/api/authorized-directories/{auth['id']}/cloud-analysis", json={"path": "lesson.md", "prompt": "请总结", "confirmed": True})
    assert response.status_code == 200
    assert captured["task_type"] == "file_cloud_analysis"
    assert "SECRET_VALUE" not in captured["prompt"]
    assert "test@example.com" not in captured["prompt"]
    assert str(tmp_path) not in captured["prompt"]
    assert "[正文已按云端分析上限裁剪]" in captured["prompt"]
    assert response.json()["sent_content_length"] <= 120_000 + len("\\n[正文已按云端分析上限裁剪]")


def test_integrity_detects_changed_source_and_missing_layers(tmp_path: Path):
    document = tmp_path / "lesson.md"
    document.write_text("original", encoding="utf-8")
    auth = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    report = client.post(f"/api/authorized-directories/{auth['id']}/scan").json()
    integrity = client.get("/api/imports/integrity").json()
    assert integrity["counts"]["healthy"] == 1

    document.write_text("changed", encoding="utf-8")
    changed = client.get("/api/imports/integrity").json()
    assert changed["counts"]["stale"] == 1
    assert changed["files"][0]["source_changed"] is True

    from app.file_import import _storage_path
    row = changed["files"][0]
    db_path = _storage_path(client.get(f"/api/imports/{report['import_id']}/files").json()[0]["content_file_path"])
    db_path.unlink()
    missing = client.get("/api/imports/integrity").json()
    assert missing["counts"]["missing"] == 1
    assert missing["files"][0]["content_exists"] is False


def test_duplicate_directory_authorization_returns_conflict(tmp_path: Path):
    assert client.post("/api/authorized-directories", json={"path": str(tmp_path)}).status_code == 201
    duplicate = client.post("/api/authorized-directories", json={"path": str(tmp_path)})
    assert duplicate.status_code == 409


def test_revoked_directory_cannot_update_permissions(tmp_path: Path):
    auth = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    assert client.delete(f"/api/authorized-directories/{auth['id']}").status_code == 204
    response = client.patch(f"/api/authorized-directories/{auth['id']}/permissions", json={"cloud_transfer": True})
    assert response.status_code == 403


def test_confirm_import_can_generate_idempotent_tasks_and_reviews(tmp_path: Path):
    document = tmp_path / "python.md"
    document.write_text("# Python\n函数、列表和字典", encoding="utf-8")
    auth = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    report = client.post(f"/api/authorized-directories/{auth['id']}/scan").json()
    import_id = report["import_id"]

    result = client.post(f"/api/imports/{import_id}/confirm", json={"confirmed": True, "generate_tasks": True, "generate_reviews": True})
    assert result.status_code == 200
    body = result.json()
    assert body["created_tasks"] >= 1
    assert body["created_reviews"] >= 1
    assert client.get("/api/tasks").json()
    assert client.get("/api/reviews/due").json()

    repeated = client.post(f"/api/imports/{import_id}/confirm", json={"confirmed": True, "generate_tasks": True, "generate_reviews": True})
    assert repeated.status_code == 200
    assert repeated.json()["confirmed_files"] == 0
    assert len(client.get("/api/tasks").json()) == body["created_tasks"]
