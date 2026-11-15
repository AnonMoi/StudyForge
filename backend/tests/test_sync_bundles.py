import json

from app.sync_service import create_sync_bundle


PASSPHRASE = "local-sync-passphrase-2026"


def test_sync_preview_does_not_write_and_apply_is_append_only(client):
    backup = {
        "goals": [{"id": 901, "title": "跨设备同步目标", "description": "只追加", "priority": 4, "status": "active"}],
    }
    bundle = create_sync_bundle(backup, PASSPHRASE, {"goals": 1})

    preview = client.post("/api/sync/preview", json={"bundle": bundle, "passphrase": PASSPHRASE})
    assert preview.status_code == 200
    assert preview.json()["preview"]["goals"] == 1
    assert preview.json()["requires_confirmation"] is True
    assert client.get("/api/goals").json() == []

    applied = client.post("/api/sync/apply", json={"bundle": bundle, "passphrase": PASSPHRASE, "confirmed": True})
    assert applied.status_code == 200
    assert applied.json()["sync_applied"] is True
    assert applied.json()["restored_counts"]["goals"] == 1
    assert client.get("/api/goals").json()[0]["title"] == "跨设备同步目标"

    repeated = client.post("/api/sync/apply", json={"bundle": bundle, "passphrase": PASSPHRASE, "confirmed": True})
    assert repeated.status_code == 200
    assert repeated.json()["restored_counts"]["goals"] == 0
    assert repeated.json()["skipped_counts"]["goals"] == 1


def test_sync_bundle_requires_correct_passphrase_and_integrity(client):
    bundle = create_sync_bundle({"goals": []}, PASSPHRASE, {"goals": 0})
    wrong_password = client.post("/api/sync/preview", json={"bundle": bundle, "passphrase": "wrong-passphrase-2026"})
    assert wrong_password.status_code == 422

    tampered = {**bundle, "ciphertext": bundle["ciphertext"][:-2] + "aa"}
    invalid = client.post("/api/sync/preview", json={"bundle": tampered, "passphrase": PASSPHRASE})
    assert invalid.status_code == 422


def test_sync_export_returns_encrypted_bundle_without_plaintext_payload(client):
    response = client.post("/api/sync/export", json={"passphrase": PASSPHRASE})
    assert response.status_code == 200
    body = response.json()
    assert body["bundle"]["format"] == "learning-workstation-sync-v1"
    assert body["bundle"]["ciphertext"]
    assert "跨设备同步目标" not in json.dumps(body, ensure_ascii=False)
