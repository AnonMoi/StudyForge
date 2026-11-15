from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_directory_permissions_are_independent_and_affect_scan(tmp_path: Path):
    (tmp_path / "one.md").write_text("one", encoding="utf-8")
    (tmp_path / "two.txt").write_text("two", encoding="utf-8")
    client = TestClient(app)
    item = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    updated = client.patch(f"/api/authorized-directories/{item['id']}/permissions", json={"cloud_transfer": True, "write_access": True, "excluded_extensions": [".txt"]})
    assert updated.status_code == 200
    assert updated.json()["cloud_transfer"] is True
    report = client.post(f"/api/authorized-directories/{item['id']}/scan").json()
    assert [entry["relative_path"] for entry in report["files"]] == ["one.md"]


def test_directory_rules_are_persisted_and_apply_to_scan(tmp_path: Path):
    (tmp_path / "keep.md").write_text("keep", encoding="utf-8")
    (tmp_path / "keep.py").write_text("print('keep')", encoding="utf-8")
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "skip.md").write_text("skip", encoding="utf-8")
    client = TestClient(app)
    item = client.post(
        "/api/authorized-directories",
        json={"path": str(tmp_path), "allowed_extensions": [".md", ".py"], "excluded_patterns": ["drafts"]},
    )
    assert item.status_code == 201
    assert item.json()["allowed_extensions"] == [".md", ".py"]
    assert item.json()["excluded_patterns"] == ["drafts"]
    report = client.post(f"/api/authorized-directories/{item.json()['id']}/scan").json()
    assert [entry["relative_path"] for entry in report["files"]] == ["keep.md", "keep.py"]
    assert report["excluded"]["excluded_pattern"] == 1


def test_directory_permissions_missing_directory_is_404(tmp_path: Path):
    client = TestClient(app)
    response = client.patch("/api/authorized-directories/999999/permissions", json={"cloud_transfer": True})
    assert response.status_code == 404


def test_restore_status_requires_confirmation():
    payload = TestClient(app).get("/api/backup/restore-status").json()
    assert payload["supported"] is True
    assert payload["requires_confirmation"] is True
    assert payload["strategy"] == "append"
