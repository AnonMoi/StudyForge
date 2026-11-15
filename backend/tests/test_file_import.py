from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_authorized_directory_can_be_created_and_listed(tmp_path: Path):
    client = TestClient(app)
    response = client.post("/api/authorized-directories", json={"path": str(tmp_path), "label": "教材"})
    assert response.status_code == 201
    item = response.json()
    assert item["path"] == str(tmp_path.resolve())
    assert item["active"] is True
    assert client.get("/api/authorized-directories").json()[0]["id"] == item["id"]


def test_authorization_rejects_missing_and_file_paths(tmp_path: Path):
    client = TestClient(app)
    assert client.post("/api/authorized-directories", json={"path": str(tmp_path / "missing")}).status_code == 400
    file_path = tmp_path / "file.txt"
    file_path.write_text("x")
    assert client.post("/api/authorized-directories", json={"path": str(file_path)}).status_code == 400


def test_scan_only_imports_whitelisted_non_secret_files_and_hashes(tmp_path: Path):
    (tmp_path / "ok.md").write_text("hello", encoding="utf-8")
    (tmp_path / "bad.exe").write_text("no", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (tmp_path / "private.pem").write_text("key", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "nested.md").write_text("no", encoding="utf-8")
    client = TestClient(app)
    auth = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    response = client.post(f"/api/authorized-directories/{auth['id']}/scan")
    assert response.status_code == 200
    report = response.json()
    assert report["files_scanned"] == 1
    assert report["files"][0]["relative_path"] == "ok.md"
    assert len(report["files"][0]["sha256"]) == 64
    assert report["excluded"]["unsupported_extension"] >= 1
    assert report["excluded"]["secret"] >= 2
    assert report["excluded"]["excluded_directory"] >= 1


def test_scan_cannot_escape_authorized_directory_and_revoke_import(tmp_path: Path):
    outside = tmp_path.parent / "outside-secret.md"
    outside.write_text("outside", encoding="utf-8")
    client = TestClient(app)
    auth = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    assert client.post(f"/api/authorized-directories/{auth['id']}/scan", json={"path": "../outside-secret.md"}).status_code == 400
    (tmp_path / "inside.md").write_text("inside", encoding="utf-8")
    report = client.post(f"/api/authorized-directories/{auth['id']}/scan").json()
    assert report["import_id"]
    revoked = client.delete(f"/api/imports/{report['import_id']}")
    assert revoked.status_code == 204
    assert client.get(f"/api/imports/{report['import_id']}").status_code == 404


def test_revoking_authorization_prevents_scan(tmp_path: Path):
    client = TestClient(app)
    auth = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    assert client.delete(f"/api/authorized-directories/{auth['id']}").status_code == 204
    assert client.post(f"/api/authorized-directories/{auth['id']}/scan").status_code == 403


def test_scan_requires_authorization_for_path(tmp_path: Path):
    client = TestClient(app)
    assert client.post("/api/imports/scan", json={"path": str(tmp_path)}).status_code == 403
