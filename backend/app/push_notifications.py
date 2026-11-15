"""Optional Web Push delivery for reminders.

The channel is disabled by default. Subscription metadata is local application
state; private VAPID material is read only from environment configuration.
"""

from __future__ import annotations

import json
import logging
from hashlib import sha256
from typing import Any

try:
    from pywebpush import WebPushException, webpush
    PUSH_DEPENDENCY_AVAILABLE = True
except (ImportError, OSError):
    # Web Push is opt-in. A missing or unreadable optional package must not
    # prevent the local-first workstation from starting with push disabled.
    PUSH_DEPENDENCY_AVAILABLE = False

    class WebPushException(Exception):
        pass

    def webpush(**kwargs: Any) -> None:
        raise RuntimeError("pywebpush dependency is unavailable")
from sqlalchemy.orm import Session

from .config import settings
from .file_import import ApplicationState

logger = logging.getLogger("learning_workstation.push")
SUBSCRIPTIONS_KEY = "web_push_subscriptions"
DELIVERIES_KEY = "web_push_deliveries"
MAX_DELIVERIES = 500


def _state(db: Session, key: str, default: dict[str, Any]) -> ApplicationState:
    state = db.get(ApplicationState, key)
    if state is None:
        state = ApplicationState(key=key, value=default)
        db.add(state)
        db.flush()
    if not isinstance(state.value, dict):
        state.value = default
    return state


def _fingerprint(endpoint: str) -> str:
    return sha256(endpoint.encode("utf-8")).hexdigest()


def normalize_subscription(payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(payload.get("endpoint", "")).strip()
    p256dh = str(payload.get("p256dh", "")).strip()
    auth = str(payload.get("auth", "")).strip()
    if not endpoint.startswith("https://"):
        raise ValueError("推送订阅 endpoint 必须使用 HTTPS")
    if len(endpoint) > 2048 or len(p256dh) < 20 or len(auth) < 8:
        raise ValueError("推送订阅字段无效")
    return {
        "id": _fingerprint(endpoint),
        "endpoint": endpoint,
        "p256dh": p256dh,
        "auth": auth,
        "expiration_time": payload.get("expiration_time"),
    }


def list_push_subscriptions(db: Session) -> list[dict[str, Any]]:
    state = _state(db, SUBSCRIPTIONS_KEY, {"items": []})
    items = state.value.get("items", [])
    return [dict(item) for item in items if isinstance(item, dict) and item.get("endpoint")]


def upsert_push_subscription(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    item = normalize_subscription(payload)
    state = _state(db, SUBSCRIPTIONS_KEY, {"items": []})
    items = [dict(row) for row in state.value.get("items", []) if isinstance(row, dict)]
    items = [row for row in items if row.get("id") != item["id"]]
    items.append(item)
    state.value = {"items": items[-20:]}
    db.commit()
    return item


def remove_push_subscription(db: Session, endpoint: str) -> bool:
    target = _fingerprint(endpoint)
    state = _state(db, SUBSCRIPTIONS_KEY, {"items": []})
    items = [dict(row) for row in state.value.get("items", []) if isinstance(row, dict)]
    remaining = [row for row in items if row.get("id") != target]
    changed = len(remaining) != len(items)
    if changed:
        state.value = {"items": remaining}
        db.commit()
    return changed


def _send(subscription: dict[str, Any], payload: dict[str, Any]) -> str:
    webpush(
        subscription_info={
            "endpoint": subscription["endpoint"],
            "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
        },
        data=json.dumps(payload, ensure_ascii=False),
        vapid_private_key=settings.web_push_vapid_private_key,
        vapid_claims={"sub": settings.web_push_subject},
        ttl=settings.web_push_ttl_seconds,
    )
    return "sent"


def deliver_pending_reminders(db: Session, reminders: list[dict[str, Any]]) -> dict[str, int | bool]:
    if not PUSH_DEPENDENCY_AVAILABLE or not settings.web_push_enabled or not settings.web_push_vapid_public_key or not settings.web_push_vapid_private_key:
        return {"enabled": False, "sent": 0, "failed": 0, "expired": 0}
    subscriptions = list_push_subscriptions(db)
    if not subscriptions:
        return {"enabled": True, "sent": 0, "failed": 0, "expired": 0}
    delivery_state = _state(db, DELIVERIES_KEY, {"ids": []})
    delivered = {str(item) for item in delivery_state.value.get("ids", [])}
    sent = failed = expired = 0
    for reminder in reminders:
        reminder_id = str(reminder.get("id", ""))
        if not reminder_id or reminder.get("status") != "pending" or reminder_id in delivered:
            continue
        payload = {"title": str(reminder.get("title", "学习提醒")), "body": str(reminder.get("detail", "")), "tag": f"learning-reminder-{reminder_id}", "url": "/"}
        delivered_one = False
        for subscription in subscriptions:
            try:
                _send(subscription, payload)
                sent += 1
                delivered_one = True
            except WebPushException as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code in {404, 410}:
                    remove_push_subscription(db, subscription["endpoint"])
                    expired += 1
                else:
                    failed += 1
                    logger.warning("web push delivery failed status=%s", status_code)
            except Exception:
                failed += 1
                logger.exception("web push delivery failed")
        if delivered_one:
            delivered.add(reminder_id)
    delivery_state.value = {"ids": list(delivered)[-MAX_DELIVERIES:]}
    db.commit()
    return {"enabled": True, "sent": sent, "failed": failed, "expired": expired}


def send_test_notification(db: Session) -> dict[str, int | bool]:
    if not PUSH_DEPENDENCY_AVAILABLE:
        return {"enabled": False, "sent": 0, "failed": 0, "expired": 0}
    subscriptions = list_push_subscriptions(db)
    sent = failed = expired = 0
    payload = {"title": "学习工作站后台推送测试", "body": "后台推送通道已连通。", "tag": "learning-workstation-push-test", "url": "/"}
    for subscription in subscriptions:
        try:
            _send(subscription, payload)
            sent += 1
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in {404, 410}:
                remove_push_subscription(db, subscription["endpoint"])
                expired += 1
            else:
                failed += 1
                logger.warning("web push test failed status=%s", status_code)
        except Exception:
            failed += 1
            logger.exception("web push test failed")
    return {"enabled": True, "sent": sent, "failed": failed, "expired": expired}


__all__ = ["DELIVERIES_KEY", "SUBSCRIPTIONS_KEY", "deliver_pending_reminders", "list_push_subscriptions", "normalize_subscription", "remove_push_subscription", "send_test_notification", "upsert_push_subscription"]
