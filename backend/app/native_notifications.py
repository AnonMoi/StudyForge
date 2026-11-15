"""Optional Windows-native reminder notifications.

The adapter is intentionally opt-in and uses the built-in PowerShell/.NET
Windows Forms notification surface. No reminder text is logged or persisted
by this adapter; only reminder ids are retained to prevent duplicate delivery.
"""

from __future__ import annotations

import base64
import logging
import shutil
import subprocess
import sys
from typing import Any

from sqlalchemy.orm import Session

from .config import settings
from .file_import import ApplicationState

logger = logging.getLogger("learning_workstation.native_notifications")
DELIVERIES_KEY = "native_notification_deliveries"
MAX_DELIVERIES = 500
IS_WINDOWS = sys.platform == "win32"


class NativeNotificationError(RuntimeError):
    pass


def _powershell_path() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("pwsh.exe")


def is_native_notifications_available() -> bool:
    return IS_WINDOWS and _powershell_path() is not None


def _encode(value: str) -> str:
    return base64.b64encode(value.encode("utf-8", errors="replace")).decode("ascii")


def _script(title: str, body: str) -> str:
    title_b64 = _encode(title[:160])
    body_b64 = _encode(body[:1000])
    return f"""
$title = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{title_b64}'))
$body = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{body_b64}'))
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipTitle = $title
$notify.BalloonTipText = $body
$notify.Visible = $true
$notify.ShowBalloonTip(5000)
Start-Sleep -Milliseconds 5200
$notify.Dispose()
""".strip()


def send_native_notification(title: str, body: str) -> dict[str, str]:
    if not is_native_notifications_available():
        raise NativeNotificationError("当前系统不支持 Windows 原生通知或 PowerShell 不可用")
    executable = _powershell_path()
    if not executable:
        raise NativeNotificationError("PowerShell 不可用")
    encoded_script = base64.b64encode(_script(title, body).encode("utf-16le")).decode("ascii")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded_script],
            check=True,
            capture_output=True,
            timeout=8,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeNotificationError("Windows 原生通知发送失败") from exc
    return {"status": "sent"}


def _state(db: Session) -> ApplicationState:
    state = db.get(ApplicationState, DELIVERIES_KEY)
    if state is None:
        state = ApplicationState(key=DELIVERIES_KEY, value={"ids": []})
        db.add(state)
        db.flush()
    if not isinstance(state.value, dict):
        state.value = {"ids": []}
    return state


def _delivery_result(*, enabled: bool, available: bool, sent: int = 0, failed: int = 0) -> dict[str, int | bool]:
    return {"enabled": enabled, "available": available, "sent": sent, "failed": failed}


def deliver_pending_native_reminders(db: Session, reminders: list[dict[str, Any]]) -> dict[str, int | bool]:
    available = is_native_notifications_available()
    if not settings.native_notifications_enabled or not available:
        return _delivery_result(enabled=bool(settings.native_notifications_enabled), available=available)
    state = _state(db)
    delivered = {str(item) for item in state.value.get("ids", []) if item}
    sent = failed = 0
    for reminder in reminders:
        reminder_id = str(reminder.get("id", ""))
        if not reminder_id or reminder.get("status") != "pending" or reminder_id in delivered:
            continue
        try:
            send_native_notification(str(reminder.get("title", "学习提醒")), str(reminder.get("detail", "")))
            delivered.add(reminder_id)
            sent += 1
        except NativeNotificationError:
            failed += 1
            logger.warning("native notification delivery failed")
    state.value = {"ids": list(delivered)[-MAX_DELIVERIES:]}
    db.commit()
    return _delivery_result(enabled=True, available=True, sent=sent, failed=failed)


def send_test_native_notification() -> dict[str, int | bool]:
    if not is_native_notifications_available():
        return {"enabled": False, "available": False, "sent": 0, "failed": 0}
    try:
        send_native_notification("学习工作站原生通知测试", "Windows 原生通知通道已连通。")
    except NativeNotificationError:
        return {"enabled": True, "available": True, "sent": 0, "failed": 1}
    return {"enabled": True, "available": True, "sent": 1, "failed": 0}


__all__ = [
    "DELIVERIES_KEY",
    "NativeNotificationError",
    "deliver_pending_native_reminders",
    "is_native_notifications_available",
    "send_native_notification",
    "send_test_native_notification",
]
