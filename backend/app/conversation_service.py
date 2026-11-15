from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .agent_models import ChatMessage, ChatTurn


class TurnConflictError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BeginTurnResult:
    turn: ChatTurn
    owns_execution: bool
    assistant_content: str | None = None


class ConversationService:
    """Canonical owner for durable interactive-chat turns and their messages."""

    def _existing_turn_result(
        self,
        db: Session,
        *,
        existing: ChatTurn,
        request_id: str,
        session_id: str,
        persona: str,
        message: str,
    ) -> BeginTurnResult:
        user = db.scalar(select(ChatMessage).where(ChatMessage.turn_id == request_id, ChatMessage.role == "user"))
        if user is None or existing.session_id != session_id or existing.persona != persona or user.content != message:
            raise TurnConflictError("REQUEST_ID_REUSED", "这个请求 ID 已用于另一条消息")
        if existing.status == "pending":
            raise TurnConflictError("TURN_RUNNING", "这条消息仍在处理中")
        if existing.status == "failed":
            raise TurnConflictError("TURN_FAILED", "这次处理已经失败，请使用新的请求 ID 重试")
        if existing.status == "cancelled":
            raise TurnConflictError("TURN_CANCELLED", "这次处理已取消，请使用新的请求 ID 重试")
        assistant = db.scalar(select(ChatMessage).where(ChatMessage.turn_id == request_id, ChatMessage.role == "assistant"))
        if existing.status != "completed" or assistant is None:
            raise TurnConflictError("TURN_INCOMPLETE", "已有请求状态不完整，请使用新的请求 ID")
        return BeginTurnResult(turn=existing, owns_execution=False, assistant_content=assistant.content)

    def begin_turn(self, db: Session, *, request_id: str, session_id: str, persona: str, message: str) -> BeginTurnResult:
        existing = db.scalar(select(ChatTurn).where(ChatTurn.turn_id == request_id))
        if existing is not None:
            return self._existing_turn_result(
                db,
                existing=existing,
                request_id=request_id,
                session_id=session_id,
                persona=persona,
                message=message,
            )
        turn = ChatTurn(turn_id=request_id, session_id=session_id, persona=persona, status="pending")
        db.add(turn)
        db.add(ChatMessage(
            session_id=session_id,
            turn_id=request_id,
            persona=persona,
            role="user",
            status="completed",
            content=message,
        ))
        try:
            db.commit()
            db.refresh(turn)
            return BeginTurnResult(turn=turn, owns_execution=True)
        except IntegrityError:
            db.rollback()

        existing = db.scalar(select(ChatTurn).where(ChatTurn.turn_id == request_id))
        if existing is None:
            raise TurnConflictError("TURN_CONFLICT", "请求身份发生冲突，请使用新的请求 ID")
        return self._existing_turn_result(
            db,
            existing=existing,
            request_id=request_id,
            session_id=session_id,
            persona=persona,
            message=message,
        )

    def complete_turn(self, db: Session, *, turn_id: str, response: str, provider: str | None = None, model_name: str | None = None, route_reason: str | None = None) -> bool:
        turn = db.scalar(select(ChatTurn).where(ChatTurn.turn_id == turn_id))
        if turn is None:
            raise RuntimeError("logical chat turn not found")
        completed_at = datetime.now(timezone.utc)
        transition = db.execute(
            update(ChatTurn)
            .where(ChatTurn.turn_id == turn_id, ChatTurn.status == "pending")
            .values(status="completed", completed_at=completed_at, provider=provider, model_name=model_name, route_reason=route_reason, failure_kind=None)
        )
        if transition.rowcount != 1:
            db.rollback()
            return False
        db.add(ChatMessage(
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            persona=turn.persona,
            role="assistant",
            status="completed",
            content=response,
        ))
        db.commit()
        return True

    def fail_turn(self, db: Session, *, turn_id: str, provider: str | None = None, model_name: str | None = None, route_reason: str | None = None, failure_kind: str | None = None) -> bool:
        transition = db.execute(
            update(ChatTurn)
            .where(ChatTurn.turn_id == turn_id, ChatTurn.status == "pending")
            .values(status="failed", completed_at=datetime.now(timezone.utc), provider=provider, model_name=model_name, route_reason=route_reason, failure_kind=failure_kind)
        )
        if transition.rowcount != 1:
            db.rollback()
            return False
        db.commit()
        return True

    def cancel_turn(self, db: Session, *, turn_id: str, route_reason: str = "client_cancelled") -> bool:
        transition = db.execute(
            update(ChatTurn)
            .where(ChatTurn.turn_id == turn_id, ChatTurn.status == "pending")
            .values(status="cancelled", completed_at=datetime.now(timezone.utc), route_reason=route_reason, failure_kind="cancelled")
        )
        if transition.rowcount != 1:
            db.rollback()
            return False
        db.commit()
        return True

    def completed_context_messages(self, db: Session, *, session_id: str, limit_turns: int = 6) -> list[ChatMessage]:
        turn_ids = list(db.scalars(
            select(ChatTurn.turn_id)
            .where(ChatTurn.session_id == session_id, ChatTurn.status == "completed")
            .order_by(ChatTurn.created_at.desc(), ChatTurn.id.desc())
            .limit(limit_turns)
        ))
        if not turn_ids:
            return []
        role_order = case((ChatMessage.role == "user", 0), else_=1)
        messages = list(db.scalars(
            select(ChatMessage)
            .join(ChatTurn, ChatTurn.turn_id == ChatMessage.turn_id)
            .where(ChatMessage.turn_id.in_(turn_ids))
            .order_by(ChatTurn.created_at, ChatTurn.id, role_order, ChatMessage.id)
        ))
        return messages

    def history_messages(self, db: Session, *, session_id: str) -> list[tuple[ChatMessage, ChatTurn | None]]:
        role_order = case((ChatMessage.role == "user", 0), else_=1)
        rows = db.execute(
            select(ChatMessage, ChatTurn)
            .outerjoin(ChatTurn, ChatTurn.turn_id == ChatMessage.turn_id)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatTurn.created_at, ChatTurn.id, ChatMessage.created_at, role_order, ChatMessage.id)
        ).all()
        return [(message, turn) for message, turn in rows]


conversation_service = ConversationService()


__all__ = ["BeginTurnResult", "ConversationService", "TurnConflictError", "conversation_service"]
