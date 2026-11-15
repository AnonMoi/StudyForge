from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_setup_status_requires_explicit_completion(client: TestClient):
    status = client.get("/api/setup/status")
    assert status.status_code == 200
    assert status.json()["requires_onboarding"] is True
    completed = client.post("/api/setup/complete")
    assert completed.status_code == 200
    assert completed.json()["completed"] is True


def test_directory_scan_metadata_changes_and_acknowledgement(client: TestClient, tmp_path: Path):
    document = tmp_path / "lesson.md"
    document.write_text("one", encoding="utf-8")
    directory = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    assert directory["authorized_at"]
    assert directory["scan_enabled"] is True

    first = client.post(f"/api/authorized-directories/{directory['id']}/scan")
    assert first.status_code == 200
    assert first.json()["changes"] == []
    listed = client.get("/api/authorized-directories").json()[0]
    assert listed["last_scanned_at"]

    document.write_text("two", encoding="utf-8")
    (tmp_path / "new.md").write_text("new", encoding="utf-8")
    changed = client.post(f"/api/authorized-directories/{directory['id']}/scan").json()
    assert {item["change_type"] for item in changed["changes"]} == {"modified", "added"}
    alerts = client.get(f"/api/authorized-directories/{directory['id']}/changes").json()
    assert {item["relative_path"] for item in alerts} == {"lesson.md", "new.md"}

    acknowledged = client.post(f"/api/authorized-directories/{directory['id']}/changes/acknowledge")
    assert acknowledged.json()["acknowledged"] == 2
    assert client.get(f"/api/authorized-directories/{directory['id']}/changes").json() == []


def test_scan_can_be_disabled_and_revoke_is_audited(client: TestClient, tmp_path: Path):
    directory = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    disabled = client.patch(f"/api/authorized-directories/{directory['id']}/scan-settings", json={"scan_enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["scan_enabled"] is False
    assert client.post(f"/api/authorized-directories/{directory['id']}/scan").status_code == 403

    assert client.delete(f"/api/authorized-directories/{directory['id']}").status_code == 204
    revoked = client.get("/api/authorized-directories").json()[0]
    assert revoked["active"] is False
    assert revoked["scan_enabled"] is False
    assert revoked["revoked_at"]
    audits = client.get("/api/audits").json()
    assert any(row["entity_type"] == "authorized_directory" and row["action"] == "revoke" for row in audits)
