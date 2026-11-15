from __future__ import annotations

import logging
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .file_import import ApplicationState
from .models import DailyLogReview, LearningStage, ReviewCard, StudyTask, WeeklyPlan
from .native_notifications import deliver_pending_native_reminders
from .push_notifications import deliver_pending_reminders

logger = logging.getLogger("learning_workstation.scheduler")
REMINDER_STATE_KEY = "learning_reminders"
MAX_REMINDERS = 200
OPEN_TASK_STATUSES = {"not_started", "in_progress", "pending_verification", "blocked"}


def _week_key(value: date) -> str:
    iso = value.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _now_iso(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat()


def _state(db: Session) -> ApplicationState:
    state = db.get(ApplicationState, REMINDER_STATE_KEY)
    if state is None:
        state = ApplicationState(key=REMINDER_STATE_KEY, value={"items": []})
        db.add(state)
        db.flush()
    if not isinstance(state.value, dict):
        state.value = {"items": []}
    state.value.setdefault("items", [])
    return state


def _add_reminder(items: list[dict[str, Any]], *, dedupe_key: str, reminder_type: str, title: str, detail: str, source_type: str, source_id: int | None, today: date) -> None:
    if any(item.get("dedupe_key") == dedupe_key for item in items):
        return
    items.append({
        "id": uuid.uuid4().hex,
        "dedupe_key": dedupe_key,
        "reminder_type": reminder_type,
        "title": title,
        "detail": detail,
        "source_type": source_type,
        "source_id": source_id,
        "due_date": today.isoformat(),
        "status": "pending",
        "created_at": _now_iso(),
        "acknowledged_at": None,
    })


def refresh_learning_reminders(db: Session, today: date | None = None) -> list[dict[str, Any]]:
    today = today or date.today()
    with _REMINDER_LOCK:
        state = _state(db)
        items = [dict(item) for item in state.value.get("items", []) if isinstance(item, dict)]

        due_reviews = list(db.scalars(select(DailyLogReview).where(DailyLogReview.review_date <= today, DailyLogReview.status != "completed").limit(1)))
        due_cards = list(db.scalars(select(ReviewCard).where(ReviewCard.status == "active", ReviewCard.due_date <= today).limit(1)))
        if due_reviews or due_cards:
            source_type = "daily_log_review" if due_reviews else "review_card"
            source_id = due_reviews[0].id if due_reviews else due_cards[0].id
            _add_reminder(
                items,
                dedupe_key=f"daily-review:{today.isoformat()}",
                reminder_type="daily_review",
                title="今天有待复习内容",
                detail="完成到期复习并提交质量评分，保留可追踪的复习证据。",
                source_type=source_type,
                source_id=source_id,
                today=today,
            )

        open_tasks = list(db.scalars(select(StudyTask).where(StudyTask.status.in_(OPEN_TASK_STATUSES), StudyTask.stage_id.is_not(None))))
        active_stages = {stage.id: stage for stage in db.scalars(select(LearningStage).where(LearningStage.status == "active"))}
        for stage_id, stage in active_stages.items():
            stage_tasks = [task for task in open_tasks if task.stage_id == stage_id]
            if not stage_tasks:
                continue
            _add_reminder(
                items,
                dedupe_key=f"stage-check:{stage_id}:{today.isoformat()}",
                reminder_type="stage_check",
                title=f"检查阶段：{stage.title}",
                detail=f"当前阶段还有 {len(stage_tasks)} 项未完成任务，确认进度、阻塞和下一步证据。",
                source_type="learning_stage",
                source_id=stage_id,
                today=today,
            )

        if open_tasks:
            week_key = _week_key(today)
            weekly_plan = db.scalar(select(WeeklyPlan).where(WeeklyPlan.week_key == week_key))
            if weekly_plan is None:
                _add_reminder(
                    items,
                    dedupe_key=f"weekly-review:{week_key}",
                    reminder_type="weekly_review",
                    title="安排本周复盘",
                    detail="补充本周目标、有效产出、阻塞和下周行动，完成周计划闭环。",
                    source_type="weekly_plan",
                    source_id=None,
                    today=today,
                )

        items.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("id", ""))))
        state.value = {"items": items[-MAX_REMINDERS:]}
        db.commit()
        return [dict(item) for item in state.value["items"]]


def list_learning_reminders(db: Session, status: str | None = "pending", limit: int = 30) -> list[dict[str, Any]]:
    state = _state(db)
    items = [dict(item) for item in state.value.get("items", []) if isinstance(item, dict)]
    if status and status != "all":
        items = [item for item in items if item.get("status") == status]
    items.sort(key=lambda item: (str(item.get("due_date", "")), str(item.get("created_at", ""))), reverse=True)
    return items[: max(1, min(limit, 100))]


def acknowledge_learning_reminder(db: Session, reminder_id: str) -> dict[str, Any] | None:
    with _REMINDER_LOCK:
        state = _state(db)
        items = [dict(item) for item in state.value.get("items", []) if isinstance(item, dict)]
        for item in items:
            if item.get("id") != reminder_id:
                continue
            item["status"] = "acknowledged"
            item["acknowledged_at"] = _now_iso()
            state.value = {"items": items}
            db.commit()
            return dict(item)
    return None


_REMINDER_LOCK = threading.Lock()
_SCHEDULER_STATUS_LOCK = threading.Lock()
_SCHEDULER_STATUS: dict[str, Any] = {
    "state": "stopped",
    "started_at": None,
    "stopped_at": None,
    "last_tick_at": None,
    "last_error": None,
    "ticks": 0,
}


def _update_scheduler_status(**changes: Any) -> None:
    with _SCHEDULER_STATUS_LOCK:
        _SCHEDULER_STATUS.update(changes)


def scheduler_status() -> dict[str, Any]:
    """Return non-sensitive health information for the background scheduler."""
    with _SCHEDULER_STATUS_LOCK:
        return dict(_SCHEDULER_STATUS)


def run_learning_scheduler(stop_event: threading.Event, interval_seconds: int = 60) -> None:
    _update_scheduler_status(state="running", started_at=_now_iso(), stopped_at=None, last_error=None)
    try:
        while not stop_event.wait(max(5, interval_seconds)):
            try:
                with SessionLocal() as db:
                    reminders = refresh_learning_reminders(db)
                    deliver_pending_reminders(db, reminders)
                    deliver_pending_native_reminders(db, reminders)
                current = scheduler_status()
                _update_scheduler_status(last_tick_at=_now_iso(), last_error=None, ticks=int(current["ticks"]) + 1)
            except Exception as exc:
                _update_scheduler_status(last_tick_at=_now_iso(), last_error=str(exc)[:240])
                logger.exception("learning reminder scheduler tick failed")
    finally:
        _update_scheduler_status(state="stopped", stopped_at=_now_iso())


__all__ = [
    "acknowledge_learning_reminder",
    "list_learning_reminders",
    "refresh_learning_reminders",
    "run_learning_scheduler",
    "scheduler_status",
]
