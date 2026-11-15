from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    major: Mapped[str] = mapped_column(String(160), default="")
    grade: Mapped[str] = mapped_column(String(80), default="")
    long_term_goal: Mapped[str] = mapped_column(Text, default="")
    target_job_directions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    confirmed_skills: Mapped[list[Any]] = mapped_column(JSON, default=list)
    unverified_skills: Mapped[list[Any]] = mapped_column(JSON, default=list)
    weak_capabilities: Mapped[list[Any]] = mapped_column(JSON, default=list)
    learning_preferences: Mapped[list[Any]] = mapped_column(JSON, default=list)
    proactive_level: Mapped[str] = mapped_column(String(40), default="中主动")
    profile_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LearningGoal(Base):
    __tablename__ = "learning_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="active")
    priority: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    stages: Mapped[list[LearningStage]] = relationship(back_populates="goal", cascade="all, delete-orphan")


class LearningStage(Base):
    __tablename__ = "learning_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("learning_goals.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    capability_targets: Mapped[list[Any]] = mapped_column(JSON, default=list)
    prerequisites: Mapped[list[Any]] = mapped_column(JSON, default=list)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="active")

    goal: Mapped[LearningGoal] = relationship(back_populates="stages")
    tasks: Mapped[list[StudyTask]] = relationship(back_populates="stage")


class StudyTask(Base):
    __tablename__ = "study_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("learning_stages.id", ondelete="SET NULL"), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="not_started")
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="user")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("learning_projects.id", ondelete="SET NULL"), nullable=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_topics.id", ondelete="SET NULL"), nullable=True)
    week_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    task_type: Mapped[str] = mapped_column(String(40), default="practice")
    expected_outcome: Mapped[str] = mapped_column(Text, default="")
    agent_feedback: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    stage: Mapped[LearningStage | None] = relationship(back_populates="tasks")
    verifications: Mapped[list[TaskVerification]] = relationship(back_populates="task", cascade="all, delete-orphan")
    time_entries: Mapped[list[TaskTimeEntry]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskTimeEntry(Base):
    __tablename__ = "task_time_entries"
    __table_args__ = (
        Index(
            "uq_task_time_entries_active_task",
            "task_id",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("study_tasks.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    task: Mapped[StudyTask] = relationship(back_populates="time_entries")


class TaskVerification(Base):
    __tablename__ = "task_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("study_tasks.id", ondelete="CASCADE"))
    target_status: Mapped[str] = mapped_column(String(40))
    evidence: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[StudyTask] = relationship(back_populates="verifications")


class WeeklyPlan(Base):
    __tablename__ = "weekly_plans"
    __table_args__ = (UniqueConstraint("week_key", name="uq_weekly_plans_week_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_key: Mapped[str] = mapped_column(String(20))
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("learning_goals.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("learning_projects.id", ondelete="SET NULL"), nullable=True)
    objective: Mapped[str] = mapped_column(Text, default="")
    expected_outputs: Mapped[list[Any]] = mapped_column(JSON, default=list)
    reflection: Mapped[str] = mapped_column(Text, default="")
    blockers: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BlogDraft(Base):
    __tablename__ = "blog_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_note_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"))
    source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text, default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    generation_mode: Mapped[str] = mapped_column(String(30), default="deterministic")
    model_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KnowledgeGraphLayout(Base):
    __tablename__ = "knowledge_graph_layouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_positions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    zoom: Mapped[float] = mapped_column(Float, default=1.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ReportFeedback(Base):
    __tablename__ = "report_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("learning_reports.id", ondelete="CASCADE"))
    feedback_type: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")
    proposed_change: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningReport(Base):
    __tablename__ = "learning_reports"
    __table_args__ = (
        Index("ix_learning_reports_period", "report_type", "period_start", "period_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_type: Mapped[str] = mapped_column(String(30))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("learning_stages.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list[Any]] = mapped_column(JSON, default=list)
    achievements: Mapped[list[Any]] = mapped_column(JSON, default=list)
    unfinished_items: Mapped[list[Any]] = mapped_column(JSON, default=list)
    weak_points: Mapped[list[Any]] = mapped_column(JSON, default=list)
    recommendations: Mapped[list[Any]] = mapped_column(JSON, default=list)
    proposed_changes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="generated")
    generation_mode: Mapped[str] = mapped_column(String(30), default="deterministic")
    model_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    fallback_used: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DailyLog(Base):
    __tablename__ = "daily_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    log_date: Mapped[date] = mapped_column(Date, default=date.today)
    raw_text: Mapped[str] = mapped_column(Text)
    extracted_topics: Mapped[list[Any]] = mapped_column(JSON, default=list)
    extracted_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_outputs: Mapped[list[Any]] = mapped_column(JSON, default=list)
    understood_content: Mapped[list[Any]] = mapped_column(JSON, default=list)
    unresolved_questions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    completed_tasks: Mapped[list[Any]] = mapped_column(JSON, default=list)
    resolved_questions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    next_steps: Mapped[list[Any]] = mapped_column(JSON, default=list)
    self_assessment: Mapped[str | None] = mapped_column(String(80), nullable=True)
    structured_status: Mapped[str] = mapped_column(String(40), default="pending_review")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    reviews: Mapped[list[DailyLogReview]] = relationship(back_populates="daily_log", cascade="all, delete-orphan")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("learning_projects.id", ondelete="SET NULL"), nullable=True)
    topic_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    note_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # Keep model suggestions separate from the values the learner explicitly confirmed.
    ai_extracted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confirmed_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    field_sources: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)


class DailyLogReview(Base):
    __tablename__ = "daily_log_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    daily_log_id: Mapped[int] = mapped_column(ForeignKey("daily_logs.id", ondelete="CASCADE"))
    review_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="pending")
    quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=1)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_topics.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    daily_log: Mapped[DailyLog] = relationship(back_populates="reviews")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningProject(Base):
    __tablename__ = "learning_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="active")
    path: Mapped[str] = mapped_column(String(1024), default="")
    repository_url: Mapped[str] = mapped_column(String(2048), default="")
    technologies: Mapped[list[Any]] = mapped_column(JSON, default=list)
    authorized_directory_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skills: Mapped[list[Any]] = mapped_column(JSON, default=list)
    outcomes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    milestones: Mapped[list[Any]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProjectMilestone(Base):
    __tablename__ = "project_milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("learning_projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CapabilityProfile(Base):
    __tablename__ = "capability_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    last_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CapabilityEvidence(Base):
    __tablename__ = "capability_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capability_id: Mapped[int] = mapped_column(ForeignKey("capability_profiles.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CapabilityAssessment(Base):
    __tablename__ = "capability_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capability_id: Mapped[int] = mapped_column(ForeignKey("capability_profiles.id", ondelete="CASCADE"))
    previous_level: Mapped[float] = mapped_column(Float, default=0.0)
    new_level: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_snapshot: Mapped[list[Any]] = mapped_column(JSON, default=list)
    trigger: Mapped[str] = mapped_column(String(40), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PracticeExercise(Base):
    __tablename__ = "practice_exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    exercise_type: Mapped[str] = mapped_column(String(30))
    prompt: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[str] = mapped_column(String(30), default="medium")
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_topics.id", ondelete="SET NULL"), nullable=True)
    validation_spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    hints: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PracticeAttempt(Base):
    __tablename__ = "practice_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("practice_exercises.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(Text, default="")
    query: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="failed")
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback: Mapped[str] = mapped_column(Text, default="")
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CodeRun(Base):
    __tablename__ = "code_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercise_id: Mapped[int | None] = mapped_column(ForeignKey("practice_exercises.id", ondelete="SET NULL"), nullable=True)
    code: Mapped[str] = mapped_column(Text)
    stdin: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="failed")
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelCallLog(Base):
    __tablename__ = "model_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_type: Mapped[str] = mapped_column(String(80))
    risk_level: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(40))
    model_name: Mapped[str] = mapped_column(String(120))
    upgraded: Mapped[bool] = mapped_column(default=False)
    input_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(nullable=True)
    billing_source: Mapped[str | None] = mapped_column(String(40), default="estimated_rate", nullable=True)
    success: Mapped[bool] = mapped_column(default=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    route_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    fallback_used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderBillSync(Base):
    __tablename__ = "provider_bill_syncs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    source_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    bill_import_id: Mapped[int | None] = mapped_column(ForeignKey("provider_bill_imports.id", ondelete="SET NULL"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderBillImport(Base):
    __tablename__ = "provider_bill_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_name: Mapped[str] = mapped_column(String(240), default="manual")
    currency: Mapped[str] = mapped_column(String(12), default="CNY")
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    matched_amount: Mapped[float] = mapped_column(Float, default=0.0)
    unmatched_amount: Mapped[float] = mapped_column(Float, default=0.0)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, default=0)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BackupSnapshot(Base):
    __tablename__ = "backup_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(200), default="手动快照")
    source: Mapped[str] = mapped_column(String(40), default="local")
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BackupMergeBatch(Base):
    __tablename__ = "backup_merge_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(40), default="completed")
    patches: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RestoreBatch(Base):
    __tablename__ = "restore_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("backup_snapshots.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="completed")
    requested_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    restored_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    skipped_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_ids: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentPlanProposal(Base):
    __tablename__ = "agent_plan_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    reason: Mapped[str] = mapped_column(Text, default="")
    signal_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    changes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    impact: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentChangeBatch(Base):
    __tablename__ = "agent_change_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="executed")
    changes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    before_data: Mapped[list[Any]] = mapped_column(JSON, default=list)
    after_data: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewCard(Base):
    __tablename__ = "review_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text, default="")
    hint: Mapped[str] = mapped_column(Text, default="")
    card_type: Mapped[str] = mapped_column(String(40), default="qa")
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_topics.id", ondelete="SET NULL"), nullable=True)
    source_note_id: Mapped[int | None] = mapped_column(ForeignKey("notes.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active")
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error_note: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date] = mapped_column(Date, default=date.today)
    interval_days: Mapped[int] = mapped_column(Integer, default=1)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    last_quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    history: Mapped[list[ReviewHistory]] = relationship(back_populates="card", cascade="all, delete-orphan")


class ReviewHistory(Base):
    __tablename__ = "review_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("review_cards.id", ondelete="CASCADE"))
    quality: Mapped[int] = mapped_column(Integer)
    interval_before: Mapped[int] = mapped_column(Integer, default=1)
    interval_after: Mapped[int] = mapped_column(Integer, default=1)
    ease_before: Mapped[float] = mapped_column(Float, default=2.5)
    ease_after: Mapped[float] = mapped_column(Float, default=2.5)
    repetitions_before: Mapped[int] = mapped_column(Integer, default=0)
    repetitions_after: Mapped[int] = mapped_column(Integer, default=0)
    due_before: Mapped[date] = mapped_column(Date)
    due_after: Mapped[date] = mapped_column(Date)
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    card: Mapped[ReviewCard] = relationship(back_populates="history")


class TeachingSession(Base):
    __tablename__ = "teaching_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_topics.id", ondelete="SET NULL"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("study_tasks.id", ondelete="SET NULL"), nullable=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("learning_stages.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active")
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    attempts: Mapped[list[TeachingAttempt]] = relationship(back_populates="session", cascade="all, delete-orphan")


class TeachingAttempt(Base):
    __tablename__ = "teaching_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("teaching_sessions.id", ondelete="CASCADE"))
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_topics.id", ondelete="SET NULL"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("study_tasks.id", ondelete="SET NULL"), nullable=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("learning_stages.id", ondelete="SET NULL"), nullable=True)
    phase: Mapped[str] = mapped_column(String(40), default="practice")
    prompt: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[str] = mapped_column(Text, default="")
    rubric: Mapped[list[Any]] = mapped_column(JSON, default=list)
    user_answer: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    feedback: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    evaluation_source: Mapped[str] = mapped_column(String(40), default="local_deterministic")
    evaluation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluation_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    review_card_id: Mapped[int | None] = mapped_column(ForeignKey("review_cards.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[TeachingSession] = relationship(back_populates="attempts")


__all__ = ["LearningGoal", "LearningStage", "StudyTask", "TaskTimeEntry", "TaskVerification", "WeeklyPlan", "BlogDraft", "LearningReport", "DailyLog", "DailyLogReview", "AuditLog", "LearningProject", "ProjectMilestone", "CapabilityProfile", "CapabilityEvidence", "CapabilityAssessment", "PracticeExercise", "PracticeAttempt", "CodeRun", "ModelCallLog", "ProviderBillSync", "ProviderBillImport", "BackupSnapshot", "BackupMergeBatch", "RestoreBatch", "AgentPlanProposal", "AgentChangeBatch", "ReviewCard", "ReviewHistory", "TeachingSession", "TeachingAttempt"]
