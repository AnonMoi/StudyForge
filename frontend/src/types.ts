export type Goal = {
  id: number;
  title: string;
  description: string;
  priority: number;
  status: string;
};

export type Stage = {
  id: number;
  goal_id: number;
  title: string;
  capability_targets: string[];
  prerequisites: string[];
  order_index: number;
  status: string;
};

export type WeeklyPlan = {
  id: number;
  week_key: string;
  goal_id: number | null;
  project_id: number | null;
  objective: string;
  expected_outputs: string[];
  reflection: string;
  blockers: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type WeeklySummary = {
  plan: WeeklyPlan | null;
  task_count: number;
  completed_count: number;
  completion_rate: number;
  estimated_minutes: number;
  actual_minutes: number;
  log_count: number;
  output_count: number;
  tasks: Task[];
};

export type TaskStatus = "not_started" | "in_progress" | "pending_verification" | "completed" | "needs_review" | "mastered" | "paused" | "adjusted";

export type Task = {
  id: number;
  title: string;
  description: string;
  stage_id: number | null;
  priority: number;
  estimated_minutes: number | null;
  actual_minutes: number | null;
  status: TaskStatus;
  acceptance_criteria: string;
  due_date: string | null;
  source: string;
  project_id: number | null;
  topic_id: number | null;
  week_key: string | null;
  task_type: string;
  expected_outcome: string;
  agent_feedback: string;
  completed_at: string | null;
  last_verified_at: string | null;
  next_review_date: string | null;
};

export type TaskImpactPreview = {
  title: string;
  relation: {
    goal: { id: number; title: string } | null;
    stage: { id: number; title: string } | null;
    topic: { id: number; name: string } | null;
    project: { id: number; title: string } | null;
  };
  prerequisites: string[];
  schedule_impact: {
    week_key: string;
    existing_active_task_count: number;
    existing_estimated_minutes: number;
    task_estimated_minutes: number;
    after_estimated_minutes: number;
  };
  impact_level: "low" | "medium" | "high";
  recommendations: string[];
  requires_confirmation: boolean;
};

export type TaskVerification = {
  id: number;
  task_id: number;
  target_status: "completed" | "needs_review" | "mastered";
  evidence: string;
  note: string;
  actual_minutes: number | null;
  verified_at: string;
  created_at: string;
};

export type TaskTimerState = {
  task_id: number;
  state: "running" | "paused" | "stopped";
  active_entry_id: number | null;
  elapsed_seconds: number;
  accumulated_seconds: number;
  actual_minutes: number | null;
  updated_at: string | null;
};

export type TaskTimeEntry = {
  id: number;
  task_id: number;
  started_at: string;
  paused_at: string | null;
  ended_at: string | null;
  duration_seconds: number;
  status: "running" | "paused" | "stopped";
  created_at: string;
  updated_at: string;
};

export type Review = {
  id: number;
  daily_log_id: number;
  review_date: string;
  note: string;
  status: string;
  quality: number | null;
  interval_days: number;
  ease_factor: number;
  repetitions: number;
  topic_id: number | null;
};

export type DailyLog = {
  id: number;
  log_date: string;
  raw_text: string;
  extracted_topics: string[];
  extracted_duration: number | null;
  extracted_outputs: string[];
  understood_content: string[];
  unresolved_questions: string[];
  completed_tasks: string[];
  resolved_questions: string[];
  next_steps: string[];
  project_id?: number | null;
  topic_ids?: number[];
  note_ids?: number[];
  self_assessment: string | null;
  structured_status: string;
  ai_extracted: Record<string, unknown>;
  confirmed_fields: string[];
  field_sources: Record<string, string>;
};

export type DashboardSuggestion = {
  type: string;
  priority: string;
  title: string;
  detail: string;
  route: string;
};

export type LearningReminder = {
  id: string;
  reminder_type: "daily_review" | "weekly_review" | "stage_check";
  title: string;
  detail: string;
  source_type: string;
  source_id: number | null;
  due_date: string;
  status: "pending" | "acknowledged";
  created_at: string;
  acknowledged_at: string | null;
};

export type PushConfig = { enabled: boolean; public_key: string; subscription_count: number };
export type CloudSyncStatus = { configured: boolean; provider: string; path: string; warning: string };

export type PluginCommand = {
  id: string;
  title: string;
  description: string;
  task_type: string;
  prompt_template: string;
  requires_confirmation: boolean;
};

export type PluginManifest = {
  api_version: string;
  id: string;
  name: string;
  version: string;
  description: string;
  permissions: string[];
  commands: PluginCommand[];
};

export type PluginRecord = {
  manifest: PluginManifest;
  enabled: boolean;
  installed_at: string;
  updated_at: string;
  source: string;
};

export type PluginInstallPreview = {
  requires_confirmation: true;
  manifest: PluginManifest;
  already_installed: boolean;
  warning: string;
};

export type PluginCommandPreview = {
  requires_confirmation: boolean;
  plugin_id: string;
  command_id: string;
  title: string;
  task_type: string;
  policy: Record<string, unknown>;
  input_length: number;
  warning: string;
  success?: boolean;
  provider?: string;
  model_name?: string;
  response?: string | null;
  data?: Record<string, unknown> | null;
  error?: string | null;
};

export type Dashboard = {
  today_tasks: Task[];
  recent_logs: DailyLog[];
  current_goal: Goal | null;
  current_stage: Stage | null;
  weekly_minutes: number;
  output_count: number;
  pending_review_count: number;
  due_reviews?: Review[];
  weak_capabilities?: Array<{ id: number; name: string; level: number; confidence: number; evidence_count: number }>;
  active_projects?: Project[];
  recent_notes?: Note[];
  agent_suggestions?: DashboardSuggestion[];
  reminders?: LearningReminder[];
  progress_signal?: { status: string; summary: string; window_days: number; recent_minutes: number; previous_minutes: number; recent_evidence_count: number; previous_evidence_count: number; recent_completed_tasks: number; recent_notes: number; basis: string[] };
};

export type SearchResultItem = {
  id: number;
  title: string;
  subtitle: string;
  snippet: string;
  route: string;
  kind: string;
};

export type GlobalSearchResponse = {
  query: string;
  total: number;
  results: SearchResultItem[];
  grouped: Record<string, SearchResultItem[]>;
};

export type ModelHealth = {
  local: { provider: string; model: string; available: boolean };
  cloud: { provider: string; model: string; enabled: boolean; configured?: boolean; available: boolean };
};

export type RuntimeStatus = {
  scheduler: {
    state: "running" | "stopped" | string;
    thread_alive: boolean;
    interval_seconds: number;
    started_at: string | null;
    stopped_at: string | null;
    last_tick_at: string | null;
    last_error: string | null;
    ticks: number;
  };
  api_workers: number;
};

export type PublicSettings = {
  cloud_key_masked?: string;
  model_routing_mode?: "local_only" | "local_first" | "cloud_confirmed" | string;
  cloud_enabled: boolean;
  local_model: string;
  cloud_model: string;
  cloud_key_configured: boolean;
  daily_cloud_call_limit: number;
  daily_cost_limit?: number;
  max_tokens_per_request?: number;
  local_confidence_threshold?: number;
  cloud_input_price_per_1k: number;
  cloud_output_price_per_1k: number;
  report_model_enhancement_enabled?: boolean;
  native_notifications_enabled?: boolean;
  native_notifications_available?: boolean;
};

export type NativeNotificationStatus = {
  enabled: boolean;
  available: boolean;
  configured: boolean;
  warning: string | null;
};

export type ModelBudget = {
  daily_call_limit: number;
  calls_used: number;
  remaining_calls: number;
  cost_limit: number;
  cost_used: number;
  remaining_cost: number;
  tokens_used: number;
  input_price_per_1k: number;
  output_price_per_1k: number;
};

export type ModelCall = {
  id: number;
  task_type: string;
  risk_level: string;
  provider: string;
  model_name: string;
  upgraded: boolean;
  input_length: number | null;
  output_length: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  duration_ms: number | null;
  estimated_cost: number | null;
  success: boolean;
  created_at: string;
  confidence?: number | null;
  route_reason?: string | null;
  failure_reason?: string | null;
  error?: string | null;
  tokens_estimated?: boolean | null;
  token_estimated?: boolean | null;
  token_source?: "estimated" | "actual" | string | null;
  billing_source?: "provider_usage_rate" | "estimated_rate" | string | null;
  retry_count?: number;
  fallback_used?: boolean;
};

export type AuditLog = {
  id: number;
  entity_type: string;
  entity_id: number | null;
  action: string;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  created_at: string;
};

export type AgentTaskResponse = {
  success: boolean;
  task_type: string;
  provider: string;
  model_name: string;
  response?: string | null;
  data?: Record<string, unknown> | null;
  error?: string | null;
  requires_confirmation?: boolean;
};

export type AgentChangeResponse = {
  success: boolean;
  operation: string;
  preview: Record<string, unknown>;
  executed: boolean;
  result?: Record<string, unknown> | null;
  error?: string | null;
};

export type AgentChangePayload = {
  operation: string;
  payload: Record<string, unknown>;
  confirmed?: boolean;
};

export type PlanAdjustmentChange = {
  entity_type: string;
  task_id: number;
  title: string;
  reason: string;
  before: { due_date: string | null; priority: number; [key: string]: unknown };
  after: { due_date: string | null; priority: number; [key: string]: unknown };
};

export type PlanAdjustmentProposal = {
  proposal_id: number;
  status: string;
  reason: string;
  signal_summary: Record<string, unknown>;
  impact: {
    affected_tasks: number;
    affected_reviews: number;
    pending_logs: number;
    estimated_minutes_delta: number;
    date_shifted_tasks: number;
    priority_changed_tasks: number;
    [key: string]: unknown;
  };
  changes: PlanAdjustmentChange[];
  requires_confirmation: boolean;
  executed: boolean;
  result?: { applied?: number; skipped_count?: number; skipped?: Array<Record<string, unknown>>; [key: string]: unknown } | null;
  error?: string | null;
};

export type NoteVersionDiffHunk = {
  kind: "replace" | "delete" | "insert";
  before_start: number;
  before_count: number;
  after_start: number;
  after_count: number;
  before_lines: string[];
  after_lines: string[];
};

export type NoteVersionDiff = {
  note_id: number;
  from_version: number;
  to_version: number;
  fields: Record<string, { before: unknown; after: unknown }>;
  content_diff: {
    before_line_count: number;
    after_line_count: number;
    hunks: NoteVersionDiffHunk[];
  };
};

export type NoteVersion = {
  id: number;
  note_id: number;
  version_number: number;
  title: string;
  content: string;
  summary: string;
  tags: string[];
  change_note: string;
  created_at: string;
};

export type BlogDraft = {
  id: number;
  source_note_id: number;
  source_version: number | null;
  title: string;
  content: string;
  excerpt: string;
  status: string;
  generation_mode: string;
  model_provider: string | null;
  model_name: string | null;
  source_snapshot: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type BlogDraftPreview = {
  source_note_id: number;
  source_version: number | null;
  title: string;
  content: string;
  excerpt: string;
  generation_mode: string;
  model_provider: string | null;
  model_name: string | null;
  instruction: string;
  warning: string;
};

export type BlogDraftGenerateResponse = {
  executed: boolean;
  requires_confirmation: boolean;
  preview?: BlogDraftPreview;
  draft?: BlogDraft;
};

export type ReviewCard = {
  id: number;
  front: string;
  back: string;
  hint: string;
  card_type: "qa" | "code" | "explain" | "transfer" | string;
  topic_id: number | null;
  source_note_id: number | null;
  status: string;
  due_date: string;
  interval_days: number;
  ease_factor: number;
  repetitions: number;
  last_quality: number | null;
  error_type: string | null;
  error_count: number;
  last_error_note: string;
  created_at: string;
  updated_at: string;
};

export type ReviewCardCreate = {
  front: string;
  back?: string;
  hint?: string;
  card_type?: "qa" | "code" | "explain" | "transfer";
  topic_id?: number | null;
  source_note_id?: number | null;
};

export type ReviewHistory = {
  id: number;
  card_id: number;
  quality: number;
  interval_before: number;
  interval_after: number;
  ease_before: number;
  ease_after: number;
  repetitions_before: number;
  repetitions_after: number;
  due_before: string;
  due_after: string;
  reviewed_at: string;
};

export type ReviewStats = {
  total_cards: number;
  active_cards: number;
  due_cards: number;
  archived_cards: number;
  review_count: number;
  average_quality: number | null;
  mastered_cards: number;
};

export type Note = {
  id: number;
  title: string;
  content: string;
  summary: string;
  tags: string[];
  folder: string;
  source_path: string | null;
  visibility: string;
  ai_review_status: string;
  ai_review: Record<string, unknown>;
  linked_topic_ids: number[];
  linked_task_ids: number[];
  linked_project_ids: number[];
  status: string;
};

export type NoteAgentReview = {
  suggested_title: string;
  summary: string;
  suggested_tags: string[];
  technical_issues: string[];
  missing_prerequisites: string[];
  related_note_ids: number[];
  review_questions: string[];
  quality_score: number;
  quality_dimensions: Record<string, number>;
  provider?: string;
  model_name?: string;
  generation_mode?: string;
  generated_at?: string;
  [key: string]: unknown;
};

export type NoteAgentAnalyzeResponse = {
  executed: boolean;
  requires_confirmation: boolean;
  note_id: number;
  review: NoteAgentReview;
  applied_fields?: string[];
  note?: Note;
  warning?: string;
};

export type KnowledgeTopic = {
  id: number;
  name: string;
  domain: string;
  definition: string;
  self_level: string;
  verified_level: number;
  tags: string[];
  prerequisites: number[];
  evidence?: Array<Record<string, unknown>>;
  last_reviewed_at: string | null;
  next_review_at: string | null;
};

export type TopicRelation = {
  id: number;
  source_topic_id: number;
  target_topic_id: number;
  relation_type: string;
};

export type KnowledgeGraph = {
  nodes: Array<{ id: number; name: string; domain: string; verified_level: number; degree?: number; practice_count?: number; note_count?: number; weak?: boolean; orphan?: boolean }>;
  edges: TopicRelation[];
  analysis?: { weak_topics: string[]; orphan_topics: string[]; learned_without_practice: string[]; practice_without_notes: string[]; prerequisite_gaps: string[]; job_direction?: string | null; job_directions?: string[]; job_relevant_topics?: string[]; job_direction_gaps?: Array<{ topic_id: number; name: string; reason: string }> };
};

export type CapabilityGrowthPoint = { date: string; level: number; source_type: string; source_id: number | null };
export type CapabilityProfile = { id: number; name: string; description: string; level: number; confidence: number; evidence_count: number; last_assessed_at: string | null; evidence: Array<Record<string, unknown>>; growth?: CapabilityGrowthPoint[] };
export type CapabilityAssessment = { id: number; capability_id: number; previous_level: number; new_level: number; evidence_count: number; evidence_snapshot: unknown[]; trigger: string; created_at: string };
export type CapabilityEvidenceResponse = {
  capability: Pick<CapabilityProfile, "id" | "name" | "description" | "level" | "confidence" | "evidence_count" | "last_assessed_at">;
  topics: Array<{ id: number; name: string; domain: string; match_reason: string }>;
  practice: {
    exercise_count: number;
    attempt_count: number;
    passed_attempt_count: number;
    pass_rate: number | null;
    exercises: Array<{
      id: number;
      title: string;
      exercise_type: "algorithm" | "sql";
      prompt: string;
      difficulty: string;
      topic_id: number | null;
      match_reason: string;
      attempts: Array<{ id: number; status: string; passed: boolean; score: number | null; feedback: string; created_at: string }>;
    }>;
  };
  review: {
    card_count: number;
    error_event_count: number;
    by_error_type: Record<string, number>;
    cards: Array<{
      id: number;
      front: string;
      topic_id: number | null;
      error_type: string | null;
      error_count: number;
      last_error_note: string;
      error_events: Array<{ id: number; quality: number; error_type: string | null; error_note: string; reviewed_at: string }>;
    }>;
  };
  saved_evidence: Array<{ id: number; source_type: string; source_id: number | null; score: number; note: string; created_at: string }>;
};
export type PlanProposal = { proposal_id: number; status: string; reason: string; signal_summary: Record<string, unknown>; impact: Record<string, any>; changes: Array<Record<string, unknown>>; requires_confirmation: boolean; executed: boolean; result?: Record<string, unknown> | null; error?: string | null };
export type PracticeExercise = { id: number; title: string; exercise_type: "algorithm" | "sql"; prompt: string; difficulty: "easy" | "medium" | "hard"; topic_id: number | null; validation_spec: Record<string, unknown>; hints: string[]; status: string; created_at: string; updated_at: string };
export type PracticeAttempt = { id: number; exercise_id: number; code: string; query: string; answer: string; status: string; passed: boolean; score: number | null; feedback: string; stdout: string; stderr: string; duration_ms: number; created_at: string };
export type CodeRun = { id: number; exercise_id: number | null; status: string; stdout: string; stderr: string; exit_code: number | null; duration_ms: number; policy: Record<string, unknown>; created_at: string };
export type ProjectMilestone = { id: number; project_id: number; title: string; description: string; status: "pending" | "in_progress" | "completed" | "blocked"; due_date: string | null; order_index: number; evidence: string; completed_at: string | null; created_at: string; updated_at: string };
export type ProjectBoard = { project_id: number; columns: Record<string, ProjectMilestone[]>; total: number };
export type ProjectTimeline = { project_id: number; items: Array<{ type: "milestone" | "task"; id: number; title: string; status: string; date: string | null; evidence: unknown }>; evidence_count: number };
export type ReviewErrorAnalysis = { days: number; total_errors: number; by_error_type: Record<string, number>; by_topic: Record<string, number>; trend: Array<{ date: string; count: number }>; recommendations: Array<{ error_type: string; count: number; action: string }> };
export type ReviewSchedule = { executed: boolean; requires_confirmation: boolean; lookahead_days: number; recommendations: Array<{ daily_log_id: number; review_date: string; topic_id: number | null; note: string; reason: string }>; created_reviews: Review[] };

export type AnalyticsDailyPoint = { date: string; minutes: number; outputs: number; logs: number; completed_tasks: number; reviews: number; review_quality: number | null; teaching_attempts: number; teaching_score: number | null };
export type AnalyticsTopic = { topic_id: number; name: string; domain: string; task_count: number; completed_tasks: number; minutes: number; review_count: number; average_quality: number | null; teaching_attempts: number; average_score: number | null };
export type AnalyticsSummary = { today_minutes: number; week_minutes: number; total_logs: number; total_tasks: number; completed_tasks: number; task_status_counts?: Record<string, number>; outputs: number; daily: AnalyticsDailyPoint[]; topics: AnalyticsTopic[]; capabilities: CapabilityProfile[]; model_calls: { total: number; actual_tokens: number; estimated_tokens: number; estimated_cost: number }; metrics?: { overdue_task_rate: number; overdue_tasks: number; due_tasks: number; theory_tasks: number; practice_tasks: number; theory_practice_ratio: number | null; input_items: number; output_items: number; input_output_ratio: number | null; practice_exercises: number; practice_attempts: number; practice_pass_rate: number | null; code_runs: number; project_count: number; project_milestones: number; completed_milestones: number; project_progress_rate: number | null; repeated_error_cards: number; repeated_error_trend: Array<{ date: string; count: number }> } };

export type ReportType = "daily" | "weekly" | "stage" | "bottleneck";
export type ReportEvidence = { fact?: string; value?: unknown; source_type?: string; confidence?: number; [key: string]: unknown };
export type ReportFeedback = { id: number; report_id: number; feedback_type: string; note: string; proposed_change: Record<string, unknown>; created_at: string };
export type ReportProposal = { proposal_id: number; status: string; reason: string; signal_summary: Record<string, unknown>; impact: Record<string, unknown>; changes: Array<Record<string, unknown>>; requires_confirmation: boolean; executed: boolean; result?: Record<string, unknown> | null; error?: string | null; batch_id?: number | null };
export type ReportFeedbackEffect = ReportFeedback & { proposal_id: number | null; proposal_status: string | null; proposal_executed_at: string | null; batch_id: number | null; applied_count: number };
export type ReportFeedbackEffects = { report_id: number; summary: { total_feedback: number; feedback_by_type: Record<string, number>; proposals_total: number; proposal_status: Record<string, number> }; feedback: ReportFeedbackEffect[] };
export type ReportComparison = { report_type: ReportType; left: { id: number; version: number; period_start: string; period_end: string; created_at: string }; right: { id: number; version: number; period_start: string; period_end: string; created_at: string }; changes: { evidence: ReportSectionChange; weak_points: ReportSectionChange; recommendations: ReportSectionChange; summary_changed: boolean; confidence: { left: number; right: number; delta: number } } };
export type ReportSectionChange = { added: Array<Record<string, unknown>>; removed: Array<Record<string, unknown>>; changed: Array<{ key: string; left: Record<string, unknown>; right: Record<string, unknown> }> };
export type LearningReport = { id: number; report_type: ReportType; period_start: string; period_end: string; stage_id: number | null; title: string; summary: string; evidence: ReportEvidence[]; achievements: unknown[]; unfinished_items: Array<Record<string, unknown>>; weak_points: ReportEvidence[]; recommendations: ReportEvidence[]; proposed_changes: unknown[]; confidence: number; source_snapshot: Record<string, unknown>; status: string; generation_mode: string; generation_status?: string; model_provider?: string | null; model_name?: string | null; retry_count?: number; fallback_used?: boolean; version: number; created_at: string; updated_at: string };

export type ImportSearchResult = {
  matches: Array<{ import_id: number; indexed_file_id: number; relative_path: string; snippet: string; content_status: string; sha256: string }>;
};

export type ImportPreviewItem = {
  imported_file_id: number;
  relative_path: string;
  source_path: string;
  suggested_topics: string[];
  will_create_note: boolean;
  already_confirmed: boolean;
};

export type ImportConfirmResponse = {
  executed: boolean;
  batch_id?: number | null;
  requires_confirmation?: boolean;
  files?: number;
  preview?: ImportPreviewItem[];
  confirmed_files?: number;
  reused_files?: number;
  created_topics?: number;
  created_notes?: number;
  topic_ids?: number[];
  note_ids?: number[];
  created_tasks?: number;
  created_reviews?: number;
  created_cards?: number;
  card_ids?: number[];
  task_ids?: number[];
  review_ids?: number[];
  status?: string;
};

export type WebImportResponse = {
  resource_id: number;
  url: string;
  final_url: string;
  title: string;
  sha256: string;
  size: number;
  mime_type: string | null;
  content_status: string;
  content_length: number;
  confirmed: boolean;
  requires_confirmation?: boolean;
  warning?: string;
};

export type WebImportConfirmResponse = {
  executed: boolean;
  requires_confirmation?: boolean;
  reused?: boolean;
  preview?: Array<{ resource_id: number; source_path: string; title: string; suggested_topics: string[]; will_create_note: boolean; already_confirmed: boolean }>;
  resource_id?: number;
  batch_id?: number;
  created_topics?: number;
  created_notes?: number;
  topic_ids?: number[];
  note_ids?: number[];
  status?: string;
};

export type AuthorizedDirectory = {
  id: number;
  path: string;
  label: string;
  active: boolean;
  local_analysis: boolean;
  cloud_transfer: boolean;
  write_access: boolean;
  excluded_extensions: string[];
  allowed_extensions: string[];
  excluded_patterns: string[];
  authorized_at: string;
  revoked_at: string | null;
  last_scanned_at: string | null;
  scan_enabled: boolean;
};

export type DirectoryChangeAlert = {
  id: number;
  directory_id: number;
  relative_path: string;
  change_type: "added" | "modified" | "deleted" | string;
  old_sha256: string | null;
  new_sha256: string | null;
  detected_at: string;
  acknowledged_at: string | null;
};

export type ScanJob = {
  job_id: string;
  directory_id: number;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | string;
  progress: number;
  attempts?: number;
  max_attempts?: number;
  error?: string | null;
  result?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
};

export type SetupStatus = {
  completed: boolean;
  requires_onboarding: boolean;
  profile_confirmed: boolean;
  first_plan_generated: boolean;
  authorized_directory_count: number;
  privacy: {
    local_data_default: boolean;
    cloud_transfer_requires_permission: boolean;
    directory_access_requires_explicit_authorization: boolean;
  };
};

export type UserProfile = {
  id: number;
  major: string;
  grade: string;
  long_term_goal: string;
  target_job_directions: string[];
  confirmed_skills: string[];
  unverified_skills: string[];
  weak_capabilities: string[];
  learning_preferences: string[];
  proactive_level: string;
  profile_confirmed: boolean;
  created_at: string;
  updated_at: string;
};

export type UserProfileUpdate = Omit<UserProfile, "id" | "profile_confirmed" | "created_at" | "updated_at">;

export type SetupInitializeResponse = {
  executed: boolean;
  requires_confirmation: boolean;
  profile_preview?: UserProfile;
  plan_preview?: { goal_title: string; stage_title: string; task_title: string; capability_targets: string[]; [key: string]: unknown };
  profile?: UserProfile;
  created_goal_id?: number | null;
  created_stage_id?: number | null;
  created_task_id?: number | null;
  first_plan_generated?: boolean;
  setup?: SetupStatus;
};

export type AuthorizedDirectoryCreate = {
  path: string;
  label?: string;
  local_analysis?: boolean;
  cloud_transfer?: boolean;
  write_access?: boolean;
  excluded_extensions?: string[];
  allowed_extensions?: string[];
  excluded_patterns?: string[];
};

export type DirectoryPermissionUpdate = {
  local_analysis?: boolean;
  cloud_transfer?: boolean;
  write_access?: boolean;
  excluded_extensions?: string[];
  allowed_extensions?: string[];
  excluded_patterns?: string[];
};

export type AgentContext = {
  goals: Goal[];
  stages: Stage[];
  tasks: Task[];
  daily_logs: DailyLog[];
  notes: Note[];
  knowledge_topics: KnowledgeTopic[];
};

export type AgentChatResponse = {
  success: boolean;
  response: string | null;
  error: string | null;
  profile: string;
  session_id: string;
  request_id?: string | null;
  turn_id?: string | null;
  provider?: string | null;
  model_name?: string | null;
  route_reason?: string | null;
  output_type?: "explain" | "suggestion" | "operation" | string;
  basis?: string[];
  uncertainty?: string;
  actions?: Array<{ operation: "create_note" | "create_task" | "create_topic"; label: string; payload: Record<string, unknown> }>;
};

export type TeachingAttempt = {
  id: number;
  session_id: number;
  topic_id: number | null;
  task_id: number | null;
  stage_id: number | null;
  phase: string;
  prompt: string;
  expected_answer: string;
  rubric: string[];
  user_answer: string;
  score: number | null;
  error_type: string | null;
  feedback: string;
  recommendation: string;
  evaluation_source: string;
  evaluation_confidence: number | null;
  evaluation_details: { covered_rubric?: string[]; missing_rubric?: string[]; misconceptions?: string[] };
  review_card_id: number | null;
  created_at: string;
  answered_at: string | null;
  evaluated_at: string | null;
};

export type TeachingSession = {
  id: number;
  title: string;
  topic_id: number | null;
  task_id: number | null;
  stage_id: number | null;
  status: string;
  explanation: string;
  created_at: string;
  updated_at: string;
  attempts: TeachingAttempt[];
};

export type TeachingRecommendations = {
  session_id: number;
  weak_attempts: TeachingAttempt[];
  review_card_ids: number[];
  recommendations: string[];
};

export type ParseDailyLogResponse = {
  success: boolean;
  raw_text: string;
  structured_status: string;
  data: Record<string, unknown>;
  provider: string;
  model_name: string;
  error: string | null;
  duration_ms: number;
};

export type Project = {
  id: number;
  title: string;
  description: string;
  status: string;
  path: string;
  repository_url: string;
  technologies: string[];
  authorized_directory_id: number | null;
  skills: string[];
  outcomes: string[];
  milestones: Array<{ title?: string; status?: string; due_date?: string; evidence?: string; [key: string]: unknown }>;
};

export type GitHubRepository = {
  id: number;
  project_id: number;
  owner: string;
  name: string;
  full_name: string;
  html_url: string;
  default_branch: string;
  private: boolean;
  description: string;
  last_synced_sha: string | null;
  last_sync_at: string | null;
  commit_count: number;
  created_at: string;
  updated_at: string;
};

export type GitHubCommitAnalysis = {
  summary: string;
  areas: string[];
  signals: { changed_files: number; additions: number; deletions: number; test_files: number; documentation_files: number; extension_counts: Record<string, number> };
  learning_points: string[];
  recommendations: string[];
  confidence: number;
};

export type GitHubCommit = {
  id: number;
  repository_id: number;
  sha: string;
  short_sha: string;
  message: string;
  author_name: string;
  author_login: string;
  committed_at: string | null;
  html_url: string;
  additions: number;
  deletions: number;
  changed_files: number;
  files: Array<{ filename: string; status: string; additions: number; deletions: number; changes: number }>;
  analysis_status: string;
  analysis: GitHubCommitAnalysis;
  analysis_confirmed: boolean;
  imported_at: string;
};

export type GitHubLinkPreview = { requires_confirmation: boolean; repository: Partial<GitHubRepository> & { already_linked?: boolean }; warning?: string };
export type GitHubSyncPreview = { requires_confirmation: boolean; repository_id: number; fetched_commits: number; new_commits: number; commits: Array<Partial<GitHubCommit> & { short_sha: string }>; warning?: string };
export type GitHubAnalysisResponse = { requires_confirmation: boolean; commit_id: number; analysis: GitHubCommitAnalysis; analysis_confirmed?: boolean; warning?: string; status?: string };

export type JobAnalysis = {
  id: number;
  title: string;
  source_hash: string;
  extracted_skills: string[];
  matched_topics: Array<{ id: number; name: string; verified_level: number; matched_skills: string[]; reason?: string }>;
  matched_capabilities: Array<{ id: number; name: string; level: number; confidence: number; matched_skills: string[] }>;
  project_evidence: Array<{ id: number; title: string; status: string; matched_skills: string[]; outcomes: string[] }>;
  gaps: string[];
  recommendations: string[];
  confidence: number;
  created_at: string;
  updated_at: string;
};

export type JobAnalysisResult = Omit<JobAnalysis, "id" | "created_at" | "updated_at"> & { id?: number; created_at?: string; updated_at?: string };
export type JobAnalysisResponse = { requires_confirmation: boolean; analysis: JobAnalysisResult; warning?: string; status?: string };

export type ExportData = {
  goals: Goal[];
  stages: Stage[];
  tasks: Task[];
  daily_logs: DailyLog[];
  notes?: Note[];
  knowledge_topics?: KnowledgeTopic[];
  knowledge_relations?: TopicRelation[];
  projects?: Project[];
  reviews?: Review[];
  weekly_plans?: WeeklyPlan[];
  review_cards?: ReviewCard[];
  review_history?: ReviewHistory[];
  teaching_sessions?: TeachingSession[];
  teaching_attempts?: TeachingAttempt[];
  authorized_directories?: AuthorizedDirectory[];
  practice_exercises?: PracticeExercise[];
  practice_attempts?: PracticeAttempt[];
  code_runs?: CodeRun[];
  project_milestones?: ProjectMilestone[];
  capability_assessments?: CapabilityAssessment[];
};

export type BackupSnapshot = {
  id: number;
  label: string;
  source: string;
  sha256: string;
  summary: Record<string, number>;
  created_at: string;
};

export type BackupDiff = {
  left: { id: number; label: string; created_at: string };
  right: { id: number; label: string; created_at: string };
  diff: Record<string, { added: number; removed: number; unchanged: number }>;
};

export type BackupFieldDiffRecord = {
  match_key: string;
  kind: "added" | "removed" | "changed";
  label: string;
  fields: Array<{ field: string; before: unknown; after: unknown }> | null;
};

export type BackupFieldDiff = {
  left: { id: number; label: string; created_at: string };
  right: { id: number; label: string; created_at: string };
  summary: Record<string, { added: number; removed: number; changed: number; unchanged: number }>;
  records: Record<string, BackupFieldDiffRecord[]>;
};

export type BackupMergePatch = {
  entity_type: string;
  match_key: string | number;
  label: string;
  fields: Record<string, unknown>;
  conflicts: Array<{ field: string; current: unknown; backup: unknown }>;
};

export type BackupMergeResponse = {
  applied: boolean;
  requires_confirmation?: boolean;
  merge_batch_id?: number;
  affected_records?: number;
  skipped_records?: number;
  preview?: { affected_records: number; patches: BackupMergePatch[] };
  warning?: string;
};

export type BackupMergeBatch = { id: number; status: string; patch_count: number; created_at: string; reverted_at: string | null };

export type RestoreBatch = {
  id: number;
  snapshot_id: number | null;
  status: string;
  requested_counts: Record<string, number>;
  restored_counts: Record<string, number>;
  skipped_counts: Record<string, number>;
  created_ids: Record<string, number[]>;
  created_at: string;
  reverted_at: string | null;
};

export type SyncBundle = {
  format: "learning-workstation-sync-v1";
  algorithm: string;
  kdf_iterations: number;
  salt: string;
  ciphertext: string;
  payload_sha256: string;
  summary: Record<string, number>;
};

export type SyncExportResponse = { bundle: SyncBundle; summary: Record<string, number>; warning: string };
export type SyncPreview = {
  format: string;
  preview: Record<string, number>;
  diff: Record<string, { added: number; removed: number; unchanged: number }>;
  strategy: "append";
  requires_confirmation: boolean;
  warning: string;
};

export type GoalCreate = { title: string; description?: string; priority?: number };
export type StageCreate = {
  title: string;
  capability_targets?: string[];
  prerequisites?: string[];
  order_index?: number;
};
export type TaskCreate = Partial<Omit<Task, "id">> & { title: string };
export type NoteCreate = { title: string; content?: string; summary?: string; tags?: string[]; folder?: string; source_path?: string | null; visibility?: string; ai_review_status?: string; ai_review?: Record<string, unknown>; linked_topic_ids?: number[]; linked_task_ids?: number[]; linked_project_ids?: number[]; status?: string };
export type TopicCreate = {
  name: string;
  domain?: string;
  definition?: string;
  self_level?: string;
  tags?: string[];
  prerequisites?: number[];
  verified_level?: number;
};
