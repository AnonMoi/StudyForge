from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class UserProfileUpdate(BaseModel):
    major: str = Field(default="", max_length=160)
    grade: str = Field(default="", max_length=80)
    long_term_goal: str = Field(default="", max_length=5000)
    target_job_directions: list[str] = Field(default_factory=list, max_length=20)
    confirmed_skills: list[str] = Field(default_factory=list, max_length=100)
    unverified_skills: list[str] = Field(default_factory=list, max_length=100)
    weak_capabilities: list[str] = Field(default_factory=list, max_length=100)
    learning_preferences: list[str] = Field(default_factory=list, max_length=20)
    proactive_level: str = Field(default="中主动", max_length=40)


class UserProfileRead(UserProfileUpdate):
    id: int
    profile_confirmed: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SetupInitializeRequest(BaseModel):
    profile: UserProfileUpdate
    create_initial_plan: bool = True
    confirmed: bool = False


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    priority: int = Field(default=3, ge=1, le=5)


class GoalRead(GoalCreate):
    id: int
    status: str

    model_config = {"from_attributes": True}


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    status: str | None = None


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: str = "active"
    path: str = Field(default="", max_length=1024)
    repository_url: str = Field(default="", max_length=2048)
    technologies: list[str] = []
    authorized_directory_id: int | None = None
    skills: list[str] = []
    outcomes: list[str] = []
    milestones: list[dict[str, Any]] = []


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = None
    path: str | None = Field(default=None, max_length=1024)
    repository_url: str | None = Field(default=None, max_length=2048)
    technologies: list[str] | None = None
    authorized_directory_id: int | None = None
    skills: list[str] | None = None
    outcomes: list[str] | None = None
    milestones: list[dict[str, Any]] | None = None


class ProjectRead(ProjectCreate):
    id: int
    model_config = {"from_attributes": True}


class ProjectMilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=5000)
    status: str = Field(default="pending", pattern="^(pending|in_progress|completed|blocked)$")
    due_date: date | None = None
    order_index: int = Field(default=0, ge=0)
    evidence: str = Field(default="", max_length=10000)


class ProjectMilestoneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(default=None, pattern="^(pending|in_progress|completed|blocked)$")
    due_date: date | None = None
    order_index: int | None = Field(default=None, ge=0)
    evidence: str | None = Field(default=None, max_length=10000)


class ProjectMilestoneRead(ProjectMilestoneCreate):
    id: int
    project_id: int
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PracticeExerciseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    exercise_type: str = Field(pattern="^(algorithm|sql)$")
    prompt: str = Field(default="", max_length=20000)
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    topic_id: int | None = None
    validation_spec: dict[str, Any] = Field(default_factory=dict)
    hints: list[str] = Field(default_factory=list, max_length=20)


class PracticeExerciseRead(PracticeExerciseCreate):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PracticeAttemptCreate(BaseModel):
    code: str = Field(default="", max_length=30000)
    query: str = Field(default="", max_length=20000)
    answer: str = Field(default="", max_length=12000)


class PracticeAttemptRead(PracticeAttemptCreate):
    id: int
    exercise_id: int
    status: str
    passed: bool
    score: float | None = None
    feedback: str
    stdout: str
    stderr: str
    duration_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CodeRunCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30000)
    stdin: str = Field(default="", max_length=12000)
    timeout_seconds: int = Field(default=3, ge=1, le=5)
    confirmed: bool = False


class CodeRunRead(BaseModel):
    id: int
    exercise_id: int | None = None
    status: str
    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: int
    policy: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class CapabilityAssessmentRead(BaseModel):
    id: int
    capability_id: int
    previous_level: float
    new_level: float
    evidence_count: int
    evidence_snapshot: list[Any]
    trigger: str
    created_at: datetime

    model_config = {"from_attributes": True}


class StageCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    capability_targets: list[str] = []
    prerequisites: list[str] = []
    order_index: int = Field(default=0, ge=0)


class StageRead(StageCreate):
    id: int
    goal_id: int
    status: str

    model_config = {"from_attributes": True}


class StageUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    capability_targets: list[str] | None = None
    prerequisites: list[str] | None = None
    order_index: int | None = Field(default=None, ge=0)
    status: str | None = None


TASK_STATUSES = ("not_started", "in_progress", "pending_verification", "completed", "needs_review", "mastered", "paused", "adjusted")
TASK_EDITABLE_STATUSES = ("not_started", "in_progress", "pending_verification", "paused", "adjusted")
TASK_STATUS_PATTERN = "^(not_started|in_progress|pending_verification|paused|adjusted)$"


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    stage_id: int | None = None
    priority: int = Field(default=3, ge=1, le=5)
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440)
    actual_minutes: int | None = Field(default=None, ge=0, le=1440)
    status: str = Field(default="not_started", pattern=TASK_STATUS_PATTERN)
    acceptance_criteria: str = Field(default="", max_length=10000)
    due_date: date | None = None
    source: str = "user"
    project_id: int | None = None
    topic_id: int | None = None
    week_key: str | None = Field(default=None, max_length=20)
    task_type: str = Field(default="practice", max_length=40)
    expected_outcome: str = Field(default="", max_length=5000)
    agent_feedback: str = Field(default="", max_length=5000)


class TaskRead(TaskCreate):
    id: int
    completed_at: datetime | None = None
    last_verified_at: datetime | None = None
    next_review_date: date | None = None
    status: str = Field(pattern="^(not_started|in_progress|pending_verification|completed|needs_review|mastered|paused|adjusted)$")

    model_config = {"from_attributes": True}


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    stage_id: int | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440)
    actual_minutes: int | None = Field(default=None, ge=0, le=1440)
    status: str | None = Field(default=None, pattern=TASK_STATUS_PATTERN)
    acceptance_criteria: str | None = Field(default=None, max_length=10000)
    due_date: date | None = None
    project_id: int | None = None
    topic_id: int | None = None
    week_key: str | None = Field(default=None, max_length=20)
    task_type: str | None = Field(default=None, max_length=40)
    expected_outcome: str | None = Field(default=None, max_length=5000)
    agent_feedback: str | None = Field(default=None, max_length=5000)


class TaskImpactPreviewRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    stage_id: int | None = None
    topic_id: int | None = None
    project_id: int | None = None
    due_date: date | None = None
    week_key: str | None = Field(default=None, max_length=20)
    estimated_minutes: int = Field(default=30, ge=1, le=1440)
    task_type: str = Field(default="practice", max_length=40)


class TaskImpactPreviewRead(BaseModel):
    title: str
    relation: dict[str, Any]
    prerequisites: list[str]
    schedule_impact: dict[str, Any]
    impact_level: str
    recommendations: list[str]
    requires_confirmation: bool = True


class TaskVerificationCreate(BaseModel):
    target_status: str = Field(pattern="^(completed|needs_review|mastered)$")
    evidence: str = Field(min_length=1, max_length=12000)
    note: str = Field(default="", max_length=5000)
    actual_minutes: int | None = Field(default=None, ge=0, le=1440)


class TaskVerificationRead(TaskVerificationCreate):
    id: int
    task_id: int
    verified_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class TopicVerificationCreate(BaseModel):
    verified_level: int = Field(ge=0, le=8)
    evidence: str = Field(min_length=1, max_length=12000)
    source_type: str = Field(default="user_verification", min_length=1, max_length=60)


class TaskTimeEntryRead(BaseModel):
    id: int
    task_id: int
    started_at: datetime
    paused_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskTimerRead(BaseModel):
    task_id: int
    state: str
    active_entry_id: int | None
    elapsed_seconds: int
    accumulated_seconds: int
    actual_minutes: int | None
    updated_at: datetime | None = None


class WeeklyPlanCreate(BaseModel):
    week_key: str = Field(min_length=1, max_length=20)
    goal_id: int | None = None
    project_id: int | None = None
    objective: str = Field(default="", max_length=5000)
    expected_outputs: list[str] = Field(default_factory=list, max_length=20)
    reflection: str = Field(default="", max_length=10000)
    blockers: str = Field(default="", max_length=5000)
    status: str = Field(default="draft", max_length=40)


class WeeklyPlanRead(WeeklyPlanCreate):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class WeeklyPlanUpdate(BaseModel):
    goal_id: int | None = None
    project_id: int | None = None
    objective: str | None = Field(default=None, max_length=5000)
    expected_outputs: list[str] | None = Field(default=None, max_length=20)
    reflection: str | None = Field(default=None, max_length=10000)
    blockers: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(default=None, max_length=40)


REPORT_TYPES = ("daily", "weekly", "stage", "bottleneck")


class ReportGenerateRequest(BaseModel):
    period_start: date | None = None
    period_end: date | None = None
    stage_id: int | None = None
    force_new_version: bool = False


class ReportFeedbackCreate(BaseModel):
    feedback_type: str = Field(pattern="^(accepted|rejected|adjusted|helpful|not_helpful)$")
    note: str = Field(default="", max_length=5000)
    proposed_change: dict[str, Any] = Field(default_factory=dict)


class ReportFeedbackRead(ReportFeedbackCreate):
    id: int
    report_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    local_model_name: str | None = Field(default=None, min_length=0, max_length=120)
    cloud_model_name: str | None = Field(default=None, min_length=1, max_length=120)
    cloud_model_enabled: bool | None = None
    model_routing_mode: str | None = Field(default=None, pattern="^(local_only|local_first|cloud_confirmed|cloud_only)$")
    daily_cloud_call_limit: int | None = Field(default=None, ge=0, le=100000)
    daily_cost_limit: float | None = Field(default=None, ge=0, le=1000000)
    max_tokens_per_request: int | None = Field(default=None, ge=128, le=200000)
    local_confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    cloud_input_price_per_1k: float | None = Field(default=None, ge=0, le=100000)
    cloud_output_price_per_1k: float | None = Field(default=None, ge=0, le=100000)
    report_model_enhancement_enabled: bool | None = None
    native_notifications_enabled: bool | None = None


class ReportRead(BaseModel):
    id: int
    report_type: str
    period_start: date
    period_end: date
    stage_id: int | None = None
    title: str
    summary: str
    evidence: list[Any] = Field(default_factory=list)
    achievements: list[Any] = Field(default_factory=list)
    unfinished_items: list[Any] = Field(default_factory=list)
    weak_points: list[Any] = Field(default_factory=list)
    recommendations: list[Any] = Field(default_factory=list)
    proposed_changes: list[Any] = Field(default_factory=list)
    confidence: float
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    status: str
    generation_mode: str
    model_provider: str | None = None
    model_name: str | None = None
    retry_count: int = 0
    fallback_used: bool = False
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DailyLogCreate(BaseModel):
    raw_text: str = Field(min_length=1, max_length=20000)
    log_date: date | None = None
    extracted_topics: list[str] | None = None
    extracted_duration: int | None = Field(default=None, ge=0, le=1440)
    extracted_outputs: list[str] | None = None
    understood_content: list[str] | None = None
    unresolved_questions: list[str] | None = None
    completed_tasks: list[str] | None = None
    resolved_questions: list[str] | None = None
    next_steps: list[str] | None = None
    self_assessment: str | None = None
    project_id: int | None = None
    topic_ids: list[int] | None = None
    note_ids: list[int] | None = None
    confirm: bool = False
    ai_extracted: dict[str, Any] | None = None
    confirmed_fields: list[str] | None = None
    field_sources: dict[str, str] | None = None


class DailyLogUpdate(BaseModel):
    raw_text: str | None = Field(default=None, min_length=1, max_length=20000)
    extracted_topics: list[str] | None = None
    extracted_duration: int | None = Field(default=None, ge=0, le=1440)
    extracted_outputs: list[str] | None = None
    understood_content: list[str] | None = None
    unresolved_questions: list[str] | None = None
    completed_tasks: list[str] | None = None
    resolved_questions: list[str] | None = None
    next_steps: list[str] | None = None
    self_assessment: str | None = None
    project_id: int | None = None
    topic_ids: list[int] | None = None
    note_ids: list[int] | None = None
    ai_extracted: dict[str, Any] | None = None
    confirm: bool | None = None


class ReviewCreate(BaseModel):
    review_date: date
    note: str = ""
    topic_id: int | None = None


class ReviewScheduleRequest(BaseModel):
    lookahead_days: int = Field(default=7, ge=1, le=30)
    max_items: int = Field(default=20, ge=1, le=100)
    confirmed: bool = False


class ReviewUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=40)
    quality: int | None = Field(default=None, ge=0, le=5)
    topic_id: int | None = None


class BackupMergeSelection(BaseModel):
    entity_type: str = Field(min_length=1, max_length=80)
    match_key: str | int
    fields: list[str] = Field(min_length=1, max_length=100)


class BackupRestoreRequest(BaseModel):
    backup: dict[str, Any]
    confirmed: bool = False
    selections: list[BackupMergeSelection] = Field(default_factory=list, max_length=1000)


class SyncExportRequest(BaseModel):
    passphrase: str = Field(min_length=12, max_length=256)


class SyncBundleRequest(BaseModel):
    bundle: dict[str, Any]
    passphrase: str = Field(min_length=12, max_length=256)
    confirmed: bool = False


class PushSubscriptionCreate(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2048)
    p256dh: str = Field(min_length=20, max_length=512)
    auth: str = Field(min_length=8, max_length=512)
    expiration_time: int | None = Field(default=None, ge=0)


class PushSubscriptionDelete(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2048)


class PushTestRequest(BaseModel):
    confirmed: bool = False


class CloudSyncRequest(BaseModel):
    passphrase: str = Field(min_length=12, max_length=256)
    confirmed: bool = False


class PluginInstallRequest(BaseModel):
    manifest: dict[str, Any]
    confirmed: bool = False


class PluginToggleRequest(BaseModel):
    enabled: bool


class PluginDeleteRequest(BaseModel):
    confirmed: bool = False


class PluginCommandRequest(BaseModel):
    user_input: str = Field(default="", max_length=4000)
    confirmed: bool = False


class ImportPermissionUpdate(BaseModel):
    local_analysis: bool | None = None
    cloud_transfer: bool | None = None
    write_access: bool | None = None
    excluded_extensions: list[str] | None = None


class ReviewRead(ReviewCreate):
    id: int
    daily_log_id: int
    status: str
    quality: int | None = None
    interval_days: int = 1
    ease_factor: float = 2.5
    repetitions: int = 0
    model_config = {"from_attributes": True}


class DailyLogRead(BaseModel):
    id: int
    log_date: date
    raw_text: str
    extracted_topics: list[Any] = Field(default_factory=list)
    extracted_duration: int | None
    extracted_outputs: list[Any] = Field(default_factory=list)
    understood_content: list[Any] = Field(default_factory=list)
    unresolved_questions: list[Any] = Field(default_factory=list)
    completed_tasks: list[Any] = Field(default_factory=list)
    resolved_questions: list[Any] = Field(default_factory=list)
    next_steps: list[Any] = Field(default_factory=list)
    self_assessment: str | None
    project_id: int | None = None
    topic_ids: list[int] | None = None
    note_ids: list[int] | None = None
    structured_status: str
    ai_extracted: dict[str, Any] = Field(default_factory=dict)
    confirmed_fields: list[str] = Field(default_factory=list)
    field_sources: dict[str, str] = Field(default_factory=dict)

    @field_validator("extracted_topics", "extracted_outputs", "understood_content", "unresolved_questions", "completed_tasks", "resolved_questions", "next_steps", "topic_ids", "note_ids", mode="before")
    @classmethod
    def normalize_legacy_null_lists(cls, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    model_config = {"from_attributes": True}


class ParseRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=20000)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    session_id: str = Field(default="default", min_length=1, max_length=120)
    persona: str = Field(default="study-coach", pattern="^(study-coach|anna)$")
    request_id: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息不能为空")
        return value


class AgentChatAction(BaseModel):
    operation: str = Field(pattern="^(create_note|create_task|create_topic)$")
    label: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentChatResponse(BaseModel):
    success: bool
    response: str | None = None
    error: str | None = None
    profile: str = "study-coach"
    session_id: str = "default"
    request_id: str | None = None
    turn_id: str | None = None
    provider: str | None = None
    model_name: str | None = None
    route_reason: str | None = None
    output_type: str = "suggestion"
    basis: list[str] = Field(default_factory=list)
    uncertainty: str = ""
    actions: list[AgentChatAction] = Field(default_factory=list)


class AgentTaskRequest(BaseModel):
    task_type: str = Field(min_length=1, max_length=60)
    prompt: str = Field(min_length=1, max_length=30000)
    confirmed: bool = False


class AgentTaskResponse(BaseModel):
    success: bool
    task_type: str
    provider: str
    model_name: str
    response: str | None = None
    data: dict[str, Any] | None = None
    error: str | None = None
    requires_confirmation: bool = False


class AgentChangeRequest(BaseModel):
    operation: str = Field(min_length=1, max_length=60)
    payload: dict[str, Any] = {}
    confirmed: bool = False


class AgentChangeResponse(BaseModel):
    success: bool
    operation: str
    preview: dict[str, Any]
    executed: bool = False
    result: dict[str, Any] | None = None
    batch_id: int | None = None
    error: str | None = None


class AgentPlanProposalRequest(BaseModel):
    reason: str = "根据当前学习信号调整近期计划"
    lookahead_days: int = Field(default=7, ge=1, le=30)
    max_changes: int = Field(default=12, ge=1, le=50)


class AgentPlanProposalResponse(BaseModel):
    proposal_id: int
    status: str
    reason: str
    signal_summary: dict[str, Any]
    impact: dict[str, Any]
    changes: list[dict[str, Any]]
    requires_confirmation: bool = True
    executed: bool = False
    result: dict[str, Any] | None = None
    batch_id: int | None = None
    error: str | None = None


class AgentChangeRevertRequest(BaseModel):
    confirmed: bool = False


class ChatMessageRead(BaseModel):
    id: int
    session_id: str
    turn_id: str | None = None
    request_id: str | None = None
    persona: str | None = None
    role: str
    status: str = "completed"
    turn_status: str | None = None
    provider: str | None = None
    model_name: str | None = None
    route_reason: str | None = None
    failure_kind: str | None = None
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = ""
    summary: str = ""
    tags: list[str] = []
    folder: str = "Inbox"
    source_path: str | None = None
    visibility: str = "private"
    ai_review_status: str = "not_reviewed"
    ai_review: dict[str, Any] = Field(default_factory=dict)
    linked_topic_ids: list[int] = []
    linked_task_ids: list[int] = []
    linked_project_ids: list[int] = []
    status: str = "draft"


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    summary: str | None = None
    tags: list[str] | None = None
    folder: str | None = None
    source_path: str | None = None
    visibility: str | None = None
    ai_review_status: str | None = None
    ai_review: dict[str, Any] | None = None
    linked_topic_ids: list[int] | None = None
    linked_task_ids: list[int] | None = None
    linked_project_ids: list[int] | None = None
    status: str | None = None


class NoteRead(NoteCreate):
    id: int

    model_config = {"from_attributes": True}


class NoteAgentAnalyzeRequest(BaseModel):
    confirmed: bool = False
    apply_fields: list[str] = Field(default_factory=list)
    instruction: str = Field(default="检查笔记结构、技术风险、前置知识和复习价值", max_length=2000)


class NoteVersionRead(BaseModel):
    id: int
    note_id: int
    version_number: int
    title: str
    content: str
    summary: str
    tags: list[str]
    change_note: str
    created_at: datetime

    model_config = {"from_attributes": True}


class BlogDraftGenerateRequest(BaseModel):
    confirmed: bool = False
    instruction: str = Field(default="整理成适合发布前人工编辑的技术博客草稿", max_length=2000)


class BlogDraftRead(BaseModel):
    id: int
    source_note_id: int
    source_version: int | None
    title: str
    content: str
    excerpt: str
    status: str
    generation_mode: str
    model_provider: str | None
    model_name: str | None
    source_snapshot: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NoteVersionDiffHunk(BaseModel):
    kind: str
    before_start: int
    before_count: int
    after_start: int
    after_count: int
    before_lines: list[str]
    after_lines: list[str]


class NoteVersionDiff(BaseModel):
    note_id: int
    from_version: int
    to_version: int
    fields: dict[str, dict[str, Any]]
    content_diff: dict[str, Any] = Field(default_factory=dict)


class NoteVersionRestoreRequest(BaseModel):
    fields: list[str] = Field(default_factory=lambda: ["title", "content", "summary", "tags"], min_length=1)
    confirmed: bool = False


REVIEW_CARD_TYPES = ("qa", "code", "explain", "transfer")


class ReviewCardCreate(BaseModel):
    front: str = Field(min_length=1, max_length=5000)
    back: str = Field(default="", max_length=10000)
    hint: str = Field(default="", max_length=2000)
    card_type: str = Field(default="qa", pattern="^(qa|code|explain|transfer)$")
    topic_id: int | None = None
    source_note_id: int | None = None


class ReviewCardUpdate(BaseModel):
    front: str | None = Field(default=None, min_length=1, max_length=5000)
    back: str | None = Field(default=None, max_length=10000)
    hint: str | None = Field(default=None, max_length=2000)
    card_type: str | None = Field(default=None, pattern="^(qa|code|explain|transfer)$")
    topic_id: int | None = None
    source_note_id: int | None = None


class ReviewCardRead(ReviewCardCreate):
    id: int
    status: str
    error_type: str | None = None
    error_count: int = 0
    last_error_note: str = ""
    due_date: date
    interval_days: int
    ease_factor: float
    repetitions: int
    last_quality: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReviewCardAnswer(BaseModel):
    quality: int = Field(ge=0, le=5)
    error_type: str | None = Field(default=None, max_length=80)
    error_note: str = Field(default="", max_length=2000)


class ReviewCardBulkAction(BaseModel):
    card_ids: list[int] = Field(min_length=1, max_length=200)
    action: str = Field(pattern="^(archive|restore|delete)$")


class ReviewHistoryRead(BaseModel):
    id: int
    card_id: int
    quality: int
    interval_before: int
    interval_after: int
    ease_before: float
    ease_after: float
    repetitions_before: int
    repetitions_after: int
    due_before: date
    due_after: date
    error_type: str | None = None
    error_note: str = ""
    reviewed_at: datetime

    model_config = {"from_attributes": True}


class ReviewStatsRead(BaseModel):
    total_cards: int
    active_cards: int
    due_cards: int
    archived_cards: int
    review_count: int
    average_quality: float | None = None
    mastered_cards: int


class TeachingSessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    topic_id: int | None = None
    task_id: int | None = None
    stage_id: int | None = None
    explanation: str = Field(default="", max_length=12000)


class TeachingAttemptCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    expected_answer: str = Field(default="", max_length=12000)
    rubric: list[str] = Field(default_factory=list, max_length=20)
    phase: str = Field(default="practice", max_length=40)
    topic_id: int | None = None
    task_id: int | None = None
    stage_id: int | None = None


class TeachingAnswerRequest(BaseModel):
    user_answer: str = Field(min_length=1, max_length=12000)


class TeachingGenerateRequest(BaseModel):
    instruction: str = Field(default="请先讲解主题，再给出一道由易到难的练习题。", max_length=4000)
    confirmed: bool = False


class TeachingSessionRead(BaseModel):
    id: int
    title: str
    topic_id: int | None
    task_id: int | None
    stage_id: int | None
    status: str
    explanation: str
    created_at: datetime
    updated_at: datetime
    attempts: list["TeachingAttemptRead"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TeachingAttemptRead(BaseModel):
    id: int
    session_id: int
    topic_id: int | None
    task_id: int | None
    stage_id: int | None
    phase: str
    prompt: str
    expected_answer: str
    rubric: list[Any]
    user_answer: str
    score: int | None
    error_type: str | None
    feedback: str
    recommendation: str
    evaluation_source: str
    evaluation_confidence: float | None
    evaluation_details: dict[str, Any] = Field(default_factory=dict)
    review_card_id: int | None
    created_at: datetime
    answered_at: datetime | None
    evaluated_at: datetime | None

    model_config = {"from_attributes": True}


class TopicCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    domain: str = "待整理"
    definition: str = ""
    self_level: str = "有印象"
    tags: list[str] = []
    prerequisites: list[int] = []


class TopicUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    domain: str | None = None
    definition: str | None = None
    self_level: str | None = None
    tags: list[str] | None = None
    prerequisites: list[int] | None = None


class TopicRead(TopicCreate):
    id: int
    verified_level: int = Field(default=0, ge=0, le=8)
    evidence: list[Any] = Field(default_factory=list)
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None

    model_config = {"from_attributes": True}


class GraphLayoutUpdate(BaseModel):
    node_positions: dict[str, dict[str, float]] = Field(default_factory=dict)
    zoom: float = Field(default=1.0, ge=0.6, le=1.8)


class TopicRelationCreate(BaseModel):
    target_topic_id: int
    relation_type: str = Field(min_length=1, max_length=40)


class TopicRelationRead(TopicRelationCreate):
    id: int
    source_topic_id: int

    model_config = {"from_attributes": True}


class DashboardRead(BaseModel):
    today_tasks: list[TaskRead]
    recent_logs: list[DailyLogRead]
    current_goal: GoalRead | None
    current_stage: StageRead | None
    weekly_minutes: int
    output_count: int
    pending_review_count: int
    due_reviews: list[ReviewRead] = []
    weak_capabilities: list[dict[str, Any]] = []
    active_projects: list[ProjectRead] = []
    recent_notes: list[NoteRead] = []
    agent_suggestions: list[dict[str, Any]] = []
    progress_signal: dict[str, Any] = {}


class SearchResultItem(BaseModel):
    id: int
    title: str
    subtitle: str = ""
    snippet: str = ""
    route: str
    kind: str


class GlobalSearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResultItem]
    grouped: dict[str, list[SearchResultItem]]
