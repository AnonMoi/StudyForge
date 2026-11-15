from app import push_notifications
from app.main import settings


def test_push_channel_is_disabled_by_default_and_does_not_send(client):
    config = client.get("/api/push/config")
    assert config.status_code == 200
    assert config.json()["enabled"] is False
    preview = client.post("/api/push/test", json={"confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    blocked = client.post("/api/push/test", json={"confirmed": True})
    assert blocked.status_code == 409


def test_push_subscription_and_test_delivery_require_configured_vapid(monkeypatch, client):
    monkeypatch.setattr(push_notifications, "PUSH_DEPENDENCY_AVAILABLE", True)
    monkeypatch.setattr(settings, "web_push_enabled", True)
    monkeypatch.setattr(settings, "web_push_vapid_public_key", "public-key")
    monkeypatch.setattr(settings, "web_push_vapid_private_key", "private-key")
    monkeypatch.setattr(settings, "web_push_subject", "mailto:test@example.com")
    sent = []

    def fake_webpush(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(push_notifications, "webpush", fake_webpush)
    registered = client.post("/api/push/subscriptions", json={"endpoint": "https://push.example/subscription-1", "p256dh": "p" * 20, "auth": "a" * 8})
    assert registered.status_code == 200
    assert client.get("/api/push/config").json()["subscription_count"] == 1

    test_result = client.post("/api/push/test", json={"confirmed": True})
    assert test_result.status_code == 200
    assert test_result.json()["sent"] == 1
    assert len(sent) == 1
    assert "private-key" not in str(sent[0].get("data", ""))

    removed = client.request("DELETE", "/api/push/subscriptions", json={"endpoint": "https://push.example/subscription-1"})
    assert removed.status_code == 200
    assert removed.json()["removed"] is True


def test_push_subscription_rejects_non_https_even_when_enabled(monkeypatch, client):
    monkeypatch.setattr(settings, "web_push_enabled", True)
    monkeypatch.setattr(settings, "web_push_vapid_public_key", "public-key")
    monkeypatch.setattr(settings, "web_push_vapid_private_key", "private-key")
    response = client.post("/api/push/subscriptions", json={"endpoint": "http://push.example/subscription-1", "p256dh": "p" * 20, "auth": "a" * 8})
    assert response.status_code == 422


def test_push_config_exposes_optional_dependency_readiness(monkeypatch, client):
    monkeypatch.setattr(push_notifications, "PUSH_DEPENDENCY_AVAILABLE", False)
    monkeypatch.setattr(settings, "web_push_enabled", True)
    monkeypatch.setattr(settings, "web_push_vapid_public_key", "public-key")
    monkeypatch.setattr(settings, "web_push_vapid_private_key", "private-key")

    response = client.get("/api/push/config")

    assert response.status_code == 200
    assert response.json()["dependency_available"] is False
    assert response.json()["enabled"] is False
