from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    folder: Mapped[str] = mapped_column(String(240), default="Inbox")
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    visibility: Mapped[str] = mapped_column(String(40), default="private")
    ai_review_status: Mapped[str] = mapped_column(String(40), default="not_reviewed")
    ai_review: Mapped[dict] = mapped_column(JSON, default=dict)
    linked_topic_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    linked_task_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    linked_project_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KnowledgeTopic(Base):
    __tablename__ = "knowledge_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    domain: Mapped[str] = mapped_column(String(80), default="待整理")
    definition: Mapped[str] = mapped_column(Text, default="")
    self_level: Mapped[str] = mapped_column(String(40), default="有印象")
    verified_level: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    prerequisites: Mapped[list[int]] = mapped_column(JSON, default=list)
    evidence: Mapped[list[dict]] = mapped_column(JSON, default=list)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KnowledgeTopicRelation(Base):
    __tablename__ = "knowledge_topic_relations"
    __table_args__ = (UniqueConstraint("source_topic_id", "target_topic_id", "relation_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_topic_id: Mapped[int] = mapped_column(ForeignKey("knowledge_topics.id", ondelete="CASCADE"))
    target_topic_id: Mapped[int] = mapped_column(ForeignKey("knowledge_topics.id", ondelete="CASCADE"))
    relation_type: Mapped[str] = mapped_column(String(40))


class NoteVersion(Base):
    __tablename__ = "note_versions"
    __table_args__ = (UniqueConstraint("note_id", "version_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    change_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
