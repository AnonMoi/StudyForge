from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class ChatTurn(Base):
    __tablename__ = "chat_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    turn_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    persona: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    route_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("uq_chat_messages_turn_role", "turn_id", "role", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(120), ForeignKey("chat_turns.turn_id", ondelete="CASCADE"), nullable=True, index=True)
    persona: Mapped[str | None] = mapped_column(String(40), nullable=True)
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(24), default="completed")
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


__all__ = ["ChatMessage", "ChatTurn"]
