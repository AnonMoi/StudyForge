from app import main, native_notifications


def test_native_notifications_are_disabled_by_default(client):
    status = client.get("/api/native-notifications/status")
    assert status.status_code == 200
    assert status.json()["enabled"] is False
    preview = client.post("/api/native-notifications/test", json={"confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    blocked = client.post("/api/native-notifications/test", json={"confirmed": True})
    assert blocked.status_code == 409


def test_native_notification_test_requires_enabled_supported_adapter(monkeypatch, client):
    monkeypatch.setattr(main.settings, "native_notifications_enabled", True)
    monkeypatch.setattr(main, "is_native_notifications_available", lambda: True)
    sent = []
    monkeypatch.setattr(main, "send_test_native_notification", lambda: sent.append(True) or {"enabled": True, "available": True, "sent": 1, "failed": 0})

    preview = client.post("/api/native-notifications/test", json={"confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    result = client.post("/api/native-notifications/test", json={"confirmed": True})
    assert result.status_code == 200
    assert result.json()["sent"] == 1
    assert sent == [True]


def test_settings_cannot_enable_native_notifications_when_unavailable(monkeypatch, client):
    monkeypatch.setattr(main, "is_native_notifications_available", lambda: False)
    response = client.put("/api/settings", json={"native_notifications_enabled": True})
    assert response.status_code == 409


def test_native_reminder_delivery_is_idempotent(monkeypatch, db_session):
    monkeypatch.setattr(native_notifications.settings, "native_notifications_enabled", True)
    monkeypatch.setattr(native_notifications, "is_native_notifications_available", lambda: True)
    sent = []
    monkeypatch.setattr(native_notifications, "send_native_notification", lambda title, body: sent.append((title, body)) or {"status": "sent"})
    reminder = {"id": "reminder-1", "status": "pending", "title": "复习", "detail": "完成复习"}

    first = native_notifications.deliver_pending_native_reminders(db_session, [reminder])
    second = native_notifications.deliver_pending_native_reminders(db_session, [reminder])
    assert first["sent"] == 1
    assert second["sent"] == 0
    assert sent == [("复习", "完成复习")]


def test_native_windows_adapter_encodes_content_and_does_not_use_shell(monkeypatch):
    monkeypatch.setattr(native_notifications, "IS_WINDOWS", True)
    monkeypatch.setattr(native_notifications, "_powershell_path", lambda: "powershell.exe")
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(native_notifications.subprocess, "run", fake_run)
    result = native_notifications.send_native_notification("标题", "包含 & $(危险字符)")
    assert result["status"] == "sent"
    assert calls[0][0][:5] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden"]
    assert calls[0][1]["check"] is True
    assert calls[0][1]["capture_output"] is True
    assert "shell" not in calls[0][1]
