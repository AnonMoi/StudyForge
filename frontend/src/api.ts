import type {
  AgentChatResponse,
  AgentTaskResponse,
  AgentContext,
  Dashboard,
  GlobalSearchResponse,
  DailyLog,
  ExportData,
  Goal,
  GoalCreate,
  KnowledgeTopic,
  ModelHealth,
  RuntimeStatus,
  Note,
  NoteCreate,
  NoteAgentAnalyzeResponse,
  BlogDraft,
  BlogDraftGenerateResponse,
  ParseDailyLogResponse,
  PublicSettings,
  Stage,
  StageCreate,
  Task,
  TaskCreate,
  TaskTimerState,
  TaskTimeEntry,
  TopicCreate,
  TeachingSession,
  TeachingAttempt,
  TeachingRecommendations,
  LearningReport,
  ReportType,
  DirectoryChangeAlert,
  SetupStatus,
  SetupInitializeResponse,
  UserProfile,
  UserProfileUpdate,
  WebImportResponse,
  WebImportConfirmResponse,
  GitHubRepository,
  GitHubCommit,
  GitHubLinkPreview,
  GitHubSyncPreview,
  GitHubAnalysisResponse,
  JobAnalysis,
  JobAnalysisResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly fields: Array<Record<string, unknown>>;

  constructor(status: number, message: string, code = "API_ERROR", requestId: string | null = null, fields: Array<Record<string, unknown>> = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.fields = fields;
  }
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "当前操作未获得授权。";
    if (error.status === 404) return "目标内容不存在或已被移除。";
    if (error.status === 409) return "操作与现有数据冲突，请刷新后重试。";
    if (error.status === 422) return "输入内容未通过校验，请检查后重试。";
    if (error.status >= 500) return "服务暂时不可用，请稍后重试。";
    return error.message;
  }
  if (error instanceof TypeError) return "无法连接本地服务，请确认后端已启动。";
  return "操作失败，请稍后重试。";
}

function createRequestId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    return `request-${Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("")}`;
  }
  return `request-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function canRetryRequest(options?: RequestInit): boolean {
  const method = (options?.method ?? "GET").toUpperCase();
  return method === "GET" || method === "HEAD" || method === "OPTIONS";
}

async function request<T>(path: string, options?: RequestInit, attempt = 0): Promise<T> {
  const requestId = createRequestId();
  const retryable = canRetryRequest(options);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json", "X-Request-ID": requestId, ...(options?.headers ?? {}) },
      ...options,
    });
  } catch (error) {
    if (retryable && attempt < 1) return request<T>(path, options, attempt + 1);
    throw error;
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { error?: { code?: string; message?: string; request_id?: string; fields?: Array<Record<string, unknown>> }; detail?: string } | null;
    const message = body?.error?.message ?? body?.detail ?? `请求失败：${response.status}`;
    if (retryable && response.status >= 500 && attempt < 1) return request<T>(path, options, attempt + 1);
    throw new ApiError(response.status, message, body?.error?.code, body?.error?.request_id ?? response.headers.get("X-Request-ID"), body?.error?.fields ?? []);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  dashboard: () => request<Dashboard>("/api/dashboard"),
  reminders: () => request<{ reminders: import("./types").LearningReminder[]; pending_count: number }>("/api/reminders"),
  refreshReminders: () => request<{ reminders: import("./types").LearningReminder[] }>("/api/reminders/refresh", { method: "POST" }),
  acknowledgeReminder: (reminderId: string) => request<import("./types").LearningReminder>(`/api/reminders/${reminderId}/acknowledge`, { method: "POST" }),
  pushConfig: () => request<import("./types").PushConfig>("/api/push/config"),
  registerPushSubscription: (payload: { endpoint: string; p256dh: string; auth: string; expiration_time?: number | null }) => request<Record<string, unknown>>("/api/push/subscriptions", { method: "POST", body: JSON.stringify(payload) }),
  unregisterPushSubscription: (endpoint: string) => request<Record<string, unknown>>("/api/push/subscriptions", { method: "DELETE", body: JSON.stringify({ endpoint }) }),
  testPush: (confirmed = false) => request<Record<string, unknown>>("/api/push/test", { method: "POST", body: JSON.stringify({ confirmed }) }),
  nativeNotificationStatus: () => request<import("./types").NativeNotificationStatus>("/api/native-notifications/status"),
  testNativeNotifications: (confirmed = false) => request<Record<string, unknown>>("/api/native-notifications/test", { method: "POST", body: JSON.stringify({ confirmed }) }),
  cloudSyncStatus: () => request<import("./types").CloudSyncStatus>("/api/sync/cloud/status"),
  cloudSyncPush: (passphrase: string, confirmed = false) => request<Record<string, unknown>>("/api/sync/cloud/push", { method: "POST", body: JSON.stringify({ passphrase, confirmed }) }),
  cloudSyncPull: (passphrase: string, confirmed = false) => request<Record<string, unknown>>("/api/sync/cloud/pull", { method: "POST", body: JSON.stringify({ passphrase, confirmed }) }),
  plugins: () => request<import("./types").PluginRecord[]>("/api/plugins"),
  installPlugin: (manifest: Record<string, unknown>, confirmed = false) => request<import("./types").PluginInstallPreview | { installed: boolean; updated: boolean; plugin: import("./types").PluginRecord }>("/api/plugins/install", { method: "POST", body: JSON.stringify({ manifest, confirmed }) }),
  togglePlugin: (pluginId: string, enabled: boolean) => request<{ plugin: import("./types").PluginRecord }>(`/api/plugins/${encodeURIComponent(pluginId)}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
  deletePlugin: (pluginId: string, confirmed = false) => request<Record<string, unknown>>(`/api/plugins/${encodeURIComponent(pluginId)}`, { method: "DELETE", body: JSON.stringify({ confirmed }) }),
  runPluginCommand: (pluginId: string, commandId: string, user_input: string, confirmed = false) => request<import("./types").PluginCommandPreview>(`/api/plugins/${encodeURIComponent(pluginId)}/commands/${encodeURIComponent(commandId)}/run`, { method: "POST", body: JSON.stringify({ user_input, confirmed }) }),
  globalSearch: (q: string, limit = 6) => request<GlobalSearchResponse>(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  modelHealth: () => request<ModelHealth>("/api/models/health"),
  runtimeStatus: () => request<RuntimeStatus>("/api/runtime/status"),
  modelBudget: () => request<import("./types").ModelBudget>("/api/models/budget"),
  modelCalls: () => request<{ total: number; calls: import("./types").ModelCall[] }>("/api/models/calls"),
  providerBills: () => request<{ total: number; bills: Array<Record<string, unknown>> }>("/api/models/bills"),
  providerBillSyncs: () => request<{ total: number; syncs: Array<Record<string, unknown>> }>("/api/models/bills/syncs"),
  syncProviderBill: (payload: { period_start?: string; period_end?: string } = {}) => request<Record<string, unknown>>("/api/models/bills/sync", { method: "POST", body: JSON.stringify(payload) }),
  importProviderBill: (payload: { provider: string; source_name?: string; period_start?: string; period_end?: string; currency?: string; lines: Array<Record<string, unknown>> }) => request<Record<string, unknown>>("/api/models/bills/import", { method: "POST", body: JSON.stringify(payload) }),
  audits: () => request<import("./types").AuditLog[]>("/api/audits"),
  publicSettings: () => request<PublicSettings>("/api/settings/public"),
  settings: () => request<PublicSettings & { persisted_at?: string | null }>("/api/settings"),
  updateSettings: (payload: Record<string, unknown>) => request<PublicSettings & { warning?: string | null }>("/api/settings", { method: "PUT", body: JSON.stringify(payload) }),
  agentContext: () => request<AgentContext>("/api/agent/context"),
  projects: () => request<import("./types").Project[]>("/api/projects"),
  createProject: (payload: { title: string; description?: string; status?: string; path?: string; repository_url?: string; technologies?: string[]; authorized_directory_id?: number | null; skills?: string[]; outcomes?: string[]; milestones?: Array<Record<string, unknown>> }) => request<import("./types").Project>("/api/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (projectId: number, payload: Partial<{ title: string; description: string; status: string; path: string; repository_url: string; technologies: string[]; authorized_directory_id: number | null; skills: string[]; outcomes: string[]; milestones: Array<Record<string, unknown>> }>) => request<import("./types").Project>(`/api/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteProject: (projectId: number) => request<void>(`/api/projects/${projectId}`, { method: "DELETE" }),
  restoreBackup: (backup: unknown, confirmed = false) => request<Record<string, unknown>>("/api/backup/restore", { method: "POST", body: JSON.stringify({ backup, confirmed }) }),
  restoreStatus: () => request<Record<string, unknown>>("/api/backup/restore-status"),
  dueReviews: () => request<import("./types").Review[]>("/api/reviews/due"),
  scheduleReviews: (confirmed = false) => request<import("./types").ReviewSchedule>("/api/reviews/schedule", { method: "POST", body: JSON.stringify({ confirmed }) }),
  updateReview: (reviewId: number, status: string, quality?: number) => request<import("./types").Review>(`/api/reviews/${reviewId}`, { method: "PATCH", body: JSON.stringify({ status, ...(quality === undefined ? {} : { quality }) }) }),
  revokeDirectory: (directoryId: number) => request<void>(`/api/authorized-directories/${directoryId}`, { method: "DELETE" }),
  chat: (message: string) => request<AgentChatResponse>("/api/agent/chat", {
    method: "POST",
    body: JSON.stringify({ message, request_id: crypto.randomUUID() }),
  }),
  teachingSessions: () => request<TeachingSession[]>("/api/teaching/sessions"),
  teachingSession: (sessionId: number) => request<TeachingSession>(`/api/teaching/sessions/${sessionId}`),
  createTeachingSession: (payload: { title: string; topic_id?: number | null; task_id?: number | null; stage_id?: number | null; explanation?: string }) => request<TeachingSession>("/api/teaching/sessions", { method: "POST", body: JSON.stringify(payload) }),
  generateTeachingMaterial: (sessionId: number, instruction?: string) => request<TeachingSession>(`/api/teaching/sessions/${sessionId}/generate`, { method: "POST", body: JSON.stringify({ instruction: instruction ?? "请先讲解主题，再给出一道由易到难的练习题。" }) }),
  createTeachingAttempt: (sessionId: number, payload: { prompt: string; expected_answer?: string; rubric?: string[]; phase?: string; topic_id?: number | null; task_id?: number | null; stage_id?: number | null }) => request<TeachingAttempt>(`/api/teaching/sessions/${sessionId}/attempts`, { method: "POST", body: JSON.stringify(payload) }),
  answerTeachingAttempt: (sessionId: number, attemptId: number, user_answer: string) => request<TeachingAttempt>(`/api/teaching/sessions/${sessionId}/attempts/${attemptId}/answer`, { method: "POST", body: JSON.stringify({ user_answer }) }),
  evaluateTeachingAttempt: (sessionId: number, attemptId: number) => request<TeachingAttempt>(`/api/teaching/sessions/${sessionId}/attempts/${attemptId}/evaluate`, { method: "POST" }),
  teachingRecommendations: (sessionId: number) => request<TeachingRecommendations>(`/api/teaching/sessions/${sessionId}/recommendations`),
  runTask: (task_type: string, prompt: string, confirmed = false) => request<AgentTaskResponse>("/api/agent/task", {
    method: "POST",
    body: JSON.stringify({ task_type, prompt, confirmed }),
  }),
  agentChange: (operation: string, payload: Record<string, unknown>, confirmed = false) => request<import("./types").AgentChangeResponse>("/api/agent/change", {
    method: "POST",
    body: JSON.stringify({ operation, payload, confirmed }),
  }),
  proposePlanAdjustment: (reason = "根据当前学习信号调整近期计划", lookahead_days = 7, max_changes = 12) => request<import("./types").PlanAdjustmentProposal>("/api/agent/plan-adjustment/propose", {
    method: "POST",
    body: JSON.stringify({ reason, lookahead_days, max_changes }),
  }),
  executePlanAdjustment: (proposalId: number, confirmed = false) => request<import("./types").PlanAdjustmentProposal>(`/api/agent/plan-adjustment/${proposalId}/execute`, {
    method: "POST",
    body: JSON.stringify({ confirmed }),
  }),
  tasks: () => request<Task[]>("/api/tasks"),
  taskNotes: (taskId: number) => request<Note[]>(`/api/tasks/${taskId}/notes`),
  weeklyPlans: () => request<import("./types").WeeklyPlan[]>("/api/weekly-plans"),
  weeklyPlan: (weekKey: string) => request<import("./types").WeeklyPlan>(`/api/weekly-plans/${encodeURIComponent(weekKey)}`),
  weeklySummary: (weekKey: string) => request<import("./types").WeeklySummary>(`/api/weekly-plans/${encodeURIComponent(weekKey)}/summary`),
  createWeeklyPlan: (payload: { week_key: string; goal_id?: number | null; project_id?: number | null; objective?: string; expected_outputs?: string[]; reflection?: string; blockers?: string; status?: string }) => request<import("./types").WeeklyPlan>("/api/weekly-plans", { method: "POST", body: JSON.stringify(payload) }),
  updateWeeklyPlan: (planId: number, payload: Partial<{ goal_id: number | null; project_id: number | null; objective: string; expected_outputs: string[]; reflection: string; blockers: string; status: string }>) => request<import("./types").WeeklyPlan>(`/api/weekly-plans/${planId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  previewTaskImpact: (payload: { title: string; stage_id?: number | null; topic_id?: number | null; project_id?: number | null; due_date?: string | null; week_key?: string | null; estimated_minutes?: number; task_type?: string }) => request<import("./types").TaskImpactPreview>("/api/tasks/impact-preview", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  createTask: (payload: TaskCreate) => request<Task>("/api/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  updateTask: (taskId: number, payload: Partial<TaskCreate>) => request<Task>(`/api/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }),
  taskVerifications: (taskId: number) => request<import("./types").TaskVerification[]>(`/api/tasks/${taskId}/verifications`),
  verifyTask: (taskId: number, payload: { target_status: "completed" | "needs_review" | "mastered"; evidence: string; note?: string; actual_minutes?: number | null }) => request<Task>(`/api/tasks/${taskId}/verify`, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  taskTimer: (taskId: number) => request<TaskTimerState>(`/api/tasks/${taskId}/timer`),
  startTaskTimer: (taskId: number) => request<TaskTimerState>(`/api/tasks/${taskId}/timer/start`, { method: "POST" }),
  pauseTaskTimer: (taskId: number) => request<TaskTimerState>(`/api/tasks/${taskId}/timer/pause`, { method: "POST" }),
  resumeTaskTimer: (taskId: number) => request<TaskTimerState>(`/api/tasks/${taskId}/timer/resume`, { method: "POST" }),
  stopTaskTimer: (taskId: number) => request<TaskTimerState>(`/api/tasks/${taskId}/timer/stop`, { method: "POST" }),
  taskTimeEntries: (taskId: number) => request<TaskTimeEntry[]>(`/api/tasks/${taskId}/time-entries`),
  deleteTask: (taskId: number) => request<void>(`/api/tasks/${taskId}`, { method: "DELETE" }),
  dailyLogs: () => request<DailyLog[]>("/api/daily-logs"),
  createDailyLog: (raw_text: string, confirm = false, extracted?: Partial<DailyLog>) => request<DailyLog>("/api/daily-logs", {
    method: "POST",
    body: JSON.stringify({ raw_text, confirm, ...(extracted ?? {}) }),
  }),
  updateDailyLog: (logId: number, payload: Partial<DailyLog> & { confirm?: boolean }) => request<DailyLog>(`/api/daily-logs/${logId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }),
  parseDailyLog: (raw_text: string) => request<ParseDailyLogResponse>("/api/daily-logs/parse", {
    method: "POST",
    body: JSON.stringify({ raw_text }),
  }),
  goals: () => request<Goal[]>("/api/goals"),
  createGoal: (payload: GoalCreate) => request<Goal>("/api/goals", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  updateGoal: (goalId: number, payload: Partial<GoalCreate>) => request<Goal>(`/api/goals/${goalId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteGoal: (goalId: number) => request<void>(`/api/goals/${goalId}`, { method: "DELETE" }),
  stages: () => request<Stage[]>("/api/stages"),
  createStage: (goalId: number, payload: StageCreate) => request<Stage>(`/api/goals/${goalId}/stages`, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  updateStage: (stageId: number, payload: Partial<StageCreate> & { status?: string }) => request<Stage>(`/api/stages/${stageId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteStage: (stageId: number) => request<void>(`/api/stages/${stageId}`, { method: "DELETE" }),
  notes: () => request<Note[]>("/api/notes"),
  createNote: (payload: NoteCreate) => request<Note>("/api/notes", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  updateNote: (noteId: number, payload: Partial<NoteCreate>) => request<Note>(`/api/notes/${noteId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  }),
  analyzeNote: (noteId: number, confirmed = false, apply_fields: string[] = [], instruction?: string) => request<NoteAgentAnalyzeResponse>(`/api/notes/${noteId}/agent/analyze`, { method: "POST", body: JSON.stringify({ confirmed, apply_fields, ...(instruction ? { instruction } : {}) }) }),
  noteQualitySummary: () => request<{ total_notes: number; reviewed_notes: number; unreviewed_notes: number; average_quality_score: number | null; quality_scores: Array<{ note_id: number; title: string; score: number }> }>("/api/notes/quality-summary"),
  noteVersions: (noteId: number) => request<import("./types").NoteVersion[]>(`/api/notes/${noteId}/versions`),
  noteVersionDiff: (noteId: number, fromVersion: number, toVersion: number) => request<import("./types").NoteVersionDiff>(`/api/notes/${noteId}/versions/diff?from_version=${fromVersion}&to_version=${toVersion}`),
  restoreNoteVersion: (noteId: number, versionNumber: number, fields?: string[]) => request<Note>(`/api/notes/${noteId}/versions/${versionNumber}/restore`, { method: "POST", body: JSON.stringify({ confirmed: true, fields: fields ?? ["title", "content", "summary", "tags"] }) }),
  generateBlogDraft: (noteId: number, confirmed = false, instruction?: string) => request<BlogDraftGenerateResponse>(`/api/notes/${noteId}/blog-drafts/generate`, { method: "POST", body: JSON.stringify({ confirmed, ...(instruction ? { instruction } : {}) }) }),
  blogDrafts: (noteId: number) => request<BlogDraft[]>(`/api/notes/${noteId}/blog-drafts`),
  blogDraftExportBlob: async (draftId: number, format: "md" | "txt" | "html") => { const response = await fetch(`${API_BASE}/api/blog-drafts/${draftId}/export/${format}`); if (!response.ok) throw new Error(`博客草稿导出失败：${response.status}`); return response.blob(); },
  reviewCards: (includeCompleted = false, includeDeleted = false) => request<import("./types").ReviewCard[]>(`/api/review-cards?include_completed=${includeCompleted}&include_deleted=${includeDeleted}`),
  dueReviewCards: () => request<import("./types").ReviewCard[]>("/api/review-cards/due"),
  reviewCardStats: () => request<import("./types").ReviewStats>("/api/review-cards/stats"),
  reviewCardErrors: () => request<{ total_cards: number; total_errors: number; by_type: Record<string, number>; cards: import("./types").ReviewCard[] }>("/api/review-cards/errors"),
  reviewErrorAnalysis: (days = 30) => request<import("./types").ReviewErrorAnalysis>(`/api/review-cards/errors/analysis?days=${days}`),
  reviewCardHistory: (cardId: number) => request<import("./types").ReviewHistory[]>(`/api/review-cards/${cardId}/history`),
  createReviewCard: (payload: import("./types").ReviewCardCreate) => request<import("./types").ReviewCard>("/api/review-cards", { method: "POST", body: JSON.stringify(payload) }),
  updateReviewCard: (cardId: number, payload: Partial<import("./types").ReviewCardCreate>) => request<import("./types").ReviewCard>(`/api/review-cards/${cardId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  archiveReviewCard: (cardId: number) => request<import("./types").ReviewCard>(`/api/review-cards/${cardId}/archive`, { method: "POST" }),
  deleteReviewCard: (cardId: number) => request<import("./types").ReviewCard>(`/api/review-cards/${cardId}`, { method: "DELETE" }),
  bulkReviewCards: (card_ids: number[], action: "archive" | "restore" | "delete") => request<import("./types").ReviewCard[]>("/api/review-cards/bulk", { method: "POST", body: JSON.stringify({ card_ids, action }) }),
  revertAgentChangeBatch: (batchId: number, confirmed = false) => request<Record<string, unknown>>(`/api/agent/change-batches/${batchId}/revert`, { method: "POST", body: JSON.stringify({ confirmed }) }),
  generateReviewCards: (noteId: number, confirmed = false) => request<{ executed: boolean; requires_confirmation?: boolean; reused?: boolean; batch_id?: number; cards: import("./types").ReviewCard[]; preview: Array<{ front: string; back: string; hint: string; source_note_id: number }> }>(`/api/review-cards/generate?note_id=${noteId}&confirmed=${confirmed}`, { method: "POST" }),
  answerReviewCard: (cardId: number, quality: number, error_type?: string, error_note?: string) => request<import("./types").ReviewCard>(`/api/review-cards/${cardId}/answer`, { method: "POST", body: JSON.stringify({ quality, ...(error_type ? { error_type } : {}), ...(error_note ? { error_note } : {}) }) }),
  graphLayout: () => request<{ node_positions: Record<string, { x: number; y: number }>; zoom: number }>("/api/knowledge-graph/layout"),
  updateGraphLayout: (payload: { node_positions: Record<string, { x: number; y: number }>; zoom: number }) => request<Record<string, unknown>>("/api/knowledge-graph/layout", { method: "PUT", body: JSON.stringify(payload) }),
  topics: () => request<KnowledgeTopic[]>("/api/knowledge-topics"),
  createTopic: (payload: TopicCreate) => request<KnowledgeTopic>("/api/knowledge-topics", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  updateTopic: (topicId: number, payload: Partial<import("./types").TopicCreate>) => request<KnowledgeTopic>(`/api/knowledge-topics/${topicId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  verifyTopic: (topicId: number, payload: { verified_level: number; evidence: string; source_type?: string }) => request<KnowledgeTopic>(`/api/knowledge-topics/${topicId}/verify`, { method: "POST", body: JSON.stringify(payload) }),
  graph: () => request<import("./types").KnowledgeGraph>("/api/knowledge-graph"),
  capabilities: () => request<{ profiles: import("./types").CapabilityProfile[] }>("/api/capabilities"),
  assessCapabilities: () => request<{ profiles: import("./types").CapabilityProfile[] }>("/api/capabilities/assess", { method: "POST" }),
  capabilityHistory: (capabilityId: number) => request<import("./types").CapabilityAssessment[]>(`/api/capabilities/${capabilityId}/history`),
  capabilityEvidence: (capabilityId: number) => request<import("./types").CapabilityEvidenceResponse>(`/api/capabilities/${capabilityId}/evidence`),
  proposeCapabilityPlan: (capabilityId: number) => request<import("./types").PlanProposal>(`/api/capabilities/${capabilityId}/plan`, { method: "POST" }),
  executePlanProposal: (proposalId: number, confirmed = false) => request<import("./types").PlanProposal>(`/api/agent/plan-adjustment/${proposalId}/execute`, { method: "POST", body: JSON.stringify({ confirmed }) }),
  exercises: (exerciseType?: "algorithm" | "sql") => request<import("./types").PracticeExercise[]>(`/api/exercises${exerciseType ? `?exercise_type=${exerciseType}` : ""}`),
  createExercise: (payload: { title: string; exercise_type: "algorithm" | "sql"; prompt: string; difficulty: "easy" | "medium" | "hard"; topic_id?: number | null; validation_spec: Record<string, unknown>; hints?: string[] }) => request<import("./types").PracticeExercise>("/api/exercises", { method: "POST", body: JSON.stringify(payload) }),
  submitExerciseAttempt: (exerciseId: number, payload: { code?: string; query?: string; answer?: string }) => request<import("./types").PracticeAttempt>(`/api/exercises/${exerciseId}/attempts`, { method: "POST", body: JSON.stringify(payload) }),
  runCode: (payload: { code: string; stdin?: string; timeout_seconds?: number; confirmed?: boolean }) => request<import("./types").CodeRun | { executed: false; requires_confirmation: true; policy: Record<string, unknown>; warning: string }>("/api/code-runs", { method: "POST", body: JSON.stringify(payload) }),
  projectMilestones: (projectId: number) => request<import("./types").ProjectMilestone[]>(`/api/projects/${projectId}/milestones`),
  createProjectMilestone: (projectId: number, payload: { title: string; description?: string; status?: string; due_date?: string | null; order_index?: number; evidence?: string }) => request<import("./types").ProjectMilestone>(`/api/projects/${projectId}/milestones`, { method: "POST", body: JSON.stringify(payload) }),
  updateProjectMilestone: (milestoneId: number, payload: Partial<{ title: string; description: string; status: string; due_date: string | null; order_index: number; evidence: string }>) => request<import("./types").ProjectMilestone>(`/api/project-milestones/${milestoneId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  projectBoard: (projectId: number) => request<import("./types").ProjectBoard>(`/api/projects/${projectId}/board`),
  projectTimeline: (projectId: number) => request<import("./types").ProjectTimeline>(`/api/projects/${projectId}/timeline`),
  githubRepositories: (projectId: number) => request<{ repositories: GitHubRepository[] }>(`/api/projects/${projectId}/github`),
  linkGitHubRepository: (projectId: number, repository: string, confirmed = false) => request<GitHubLinkPreview>(`/api/projects/${projectId}/github/link`, { method: "POST", body: JSON.stringify({ repository, confirmed }) }),
  syncGitHubRepository: (projectId: number, repositoryId: number, confirmed = false, limit = 20) => request<GitHubSyncPreview & { synced_commits?: number; reused_commits?: number; status?: string }>(`/api/projects/${projectId}/github/${repositoryId}/sync`, { method: "POST", body: JSON.stringify({ confirmed, limit }) }),
  githubCommits: (projectId: number, repositoryId: number, limit = 50) => request<{ repository: GitHubRepository; commits: GitHubCommit[] }>(`/api/projects/${projectId}/github/${repositoryId}/commits?limit=${limit}`),
  analyzeGitHubCommit: (projectId: number, commitId: number, confirmed = false) => request<GitHubAnalysisResponse>(`/api/projects/${projectId}/github/commits/${commitId}/analyze`, { method: "POST", body: JSON.stringify({ confirmed }) }),
  jobAnalyses: () => request<JobAnalysis[]>("/api/job-analyses"),
  analyzeJob: (title: string, description: string, confirmed = false) => request<JobAnalysisResponse>("/api/job-analyses", { method: "POST", body: JSON.stringify({ title, description, confirmed }) }),
  jobAnalysis: (analysisId: number) => request<JobAnalysis>(`/api/job-analyses/${analysisId}`),
  createRelation: (topicId: number, target_topic_id: number, relation_type: string) => request<import("./types").TopicRelation>(`/api/knowledge-topics/${topicId}/relations`, {
    method: "POST",
    body: JSON.stringify({ target_topic_id, relation_type }),
  }),
  deleteRelation: (relationId: number) => request<void>(`/api/knowledge-relations/${relationId}`, { method: "DELETE" }),
  searchImportedContent: (q: string) => request<import("./types").ImportSearchResult>(`/api/imports/search?q=${encodeURIComponent(q)}`),
  exportData: () => request<ExportData>("/api/exports/json"),
  readableExportBlob: async (format: "md" | "txt" | "html") => {
    const response = await fetch(`${API_BASE}/api/exports/${format}`);
    if (!response.ok) throw new Error(`阅读版导出失败：${response.status}`);
    return response.blob();
  },
  analytics: (days = 30) => request<import("./types").AnalyticsSummary>(`/api/analytics/summary?days=${days}`),
  reports: (reportType?: ReportType) => request<LearningReport[]>(`/api/reports${reportType ? `?report_type=${reportType}` : ""}`),
  report: (reportId: number) => request<LearningReport>(`/api/reports/${reportId}`),
  reportFeedback: (reportId: number) => request<import("./types").ReportFeedback[]>(`/api/reports/${reportId}/feedback`),
  reportFeedbackEffects: (reportId: number) => request<import("./types").ReportFeedbackEffects>(`/api/reports/${reportId}/feedback/effects`),
  reportProposals: (reportId: number) => request<import("./types").ReportProposal[]>(`/api/reports/${reportId}/proposals`),
  compareReports: (leftId: number, rightId: number) => request<import("./types").ReportComparison>(`/api/reports/compare?left_id=${leftId}&right_id=${rightId}`),
  createReportFeedback: (reportId: number, payload: { feedback_type: string; note?: string; proposed_change?: Record<string, unknown> }) => request<import("./types").ReportFeedback>(`/api/reports/${reportId}/feedback`, { method: "POST", body: JSON.stringify(payload) }),
  generateReport: (reportType: ReportType, payload: { period_start?: string; period_end?: string; stage_id?: number | null; force_new_version?: boolean } = {}) => request<LearningReport>(`/api/reports/${reportType}/generate`, { method: "POST", body: JSON.stringify(payload) }),
  reportExport: (reportId: number, format: "json") => request<Record<string, unknown>>(`/api/reports/${reportId}/export/${format}`),
  reportExportBlob: async (reportId: number, format: "txt" | "md" | "html") => { const response = await fetch(`${API_BASE}/api/reports/${reportId}/export/${format}`); if (!response.ok) throw new Error(`报告导出失败：${response.status}`); return response.blob(); },
  backup: () => request<ExportData>("/api/backup/json"),
  createBackupSnapshot: (label?: string, backup?: unknown) => request<Record<string, unknown>>("/api/backup/snapshots", { method: "POST", body: JSON.stringify({ ...(label ? { label } : {}), ...(backup ? { backup } : {}) }) }),
  backupSnapshots: () => request<import("./types").BackupSnapshot[]>("/api/backup/snapshots"),
  backupSnapshot: (snapshotId: number) => request<Record<string, unknown>>(`/api/backup/snapshots/${snapshotId}`),
  backupDiff: (leftId: number, rightId: number) => request<import("./types").BackupDiff>(`/api/backup/diff?left_id=${leftId}&right_id=${rightId}`),
  backupFieldDiff: (leftId: number, rightId: number) => request<import("./types").BackupFieldDiff>(`/api/backup/diff/fields?left_id=${leftId}&right_id=${rightId}`),
  mergeBackup: (backup: unknown, confirmed = false, selections: Array<{ entity_type: string; match_key: string | number; fields: string[] }> = []) => request<import("./types").BackupMergeResponse>("/api/backup/merge", { method: "POST", body: JSON.stringify({ backup, confirmed, selections }) }),
  backupMergeBatches: () => request<import("./types").BackupMergeBatch[]>("/api/backup/merge-batches"),
  revertBackupMergeBatch: (batchId: number, confirmed = false) => request<Record<string, unknown>>(`/api/backup/merge-batches/${batchId}/revert`, { method: "POST", body: JSON.stringify({ confirmed }) }),
  restoreBatches: () => request<import("./types").RestoreBatch[]>("/api/backup/restore-batches"),
  revertRestoreBatch: (batchId: number, confirmed = false) => request<Record<string, unknown>>(`/api/backup/restore-batches/${batchId}/revert`, { method: "POST", body: JSON.stringify({ confirmed }) }),
  syncExport: (passphrase: string) => request<import("./types").SyncExportResponse>("/api/sync/export", { method: "POST", body: JSON.stringify({ passphrase }) }),
  syncPreview: (bundle: unknown, passphrase: string) => request<import("./types").SyncPreview>("/api/sync/preview", { method: "POST", body: JSON.stringify({ bundle, passphrase }) }),
  syncApply: (bundle: unknown, passphrase: string, confirmed = false) => request<import("./types").SyncPreview & Record<string, unknown>>("/api/sync/apply", { method: "POST", body: JSON.stringify({ bundle, passphrase, confirmed }) }),
  setupStatus: () => request<SetupStatus>("/api/setup/status"),
  completeSetup: () => request<SetupStatus>("/api/setup/complete", { method: "POST" }),
  userProfile: () => request<UserProfile>("/api/user-profile"),
  updateUserProfile: (payload: UserProfileUpdate) => request<UserProfile>("/api/user-profile", { method: "PUT", body: JSON.stringify(payload) }),
  initializeSetup: (profile: UserProfileUpdate, confirmed = false, create_initial_plan = true) => request<SetupInitializeResponse>("/api/setup/initialize", { method: "POST", body: JSON.stringify({ profile, confirmed, create_initial_plan }) }),
  authorizedDirectories: () => request<import("./types").AuthorizedDirectory[]>("/api/authorized-directories"),
  authorizeDirectory: (payload: import("./types").AuthorizedDirectoryCreate) => request<import("./types").AuthorizedDirectory>("/api/authorized-directories", { method: "POST", body: JSON.stringify(payload) }),
  directoryPermissions: (directoryId: number, payload: import("./types").DirectoryPermissionUpdate) => request<import("./types").AuthorizedDirectory>(`/api/authorized-directories/${directoryId}/permissions`, { method: "PATCH", body: JSON.stringify(payload) }),
  directoryScanSettings: (directoryId: number, scan_enabled: boolean) => request<import("./types").AuthorizedDirectory>(`/api/authorized-directories/${directoryId}/scan-settings`, { method: "PATCH", body: JSON.stringify({ scan_enabled }) }),
  directoryChanges: (directoryId: number, includeAcknowledged = false) => request<DirectoryChangeAlert[]>(`/api/authorized-directories/${directoryId}/changes?include_acknowledged=${includeAcknowledged}`),
  acknowledgeDirectoryChanges: (directoryId: number) => request<{ acknowledged: number; acknowledged_at: string }>(`/api/authorized-directories/${directoryId}/changes/acknowledge`, { method: "POST" }),
  scanDirectory: (id: number, relativePath?: string) => request<Record<string, unknown>>(`/api/authorized-directories/${id}/scan`, { method: "POST", body: JSON.stringify(relativePath ? { path: relativePath } : {}) }),
  startScanJob: (id: number, relativePath?: string) => request<import("./types").ScanJob>(`/api/authorized-directories/${id}/scan/jobs`, { method: "POST", body: JSON.stringify(relativePath ? { path: relativePath } : {}) }),
  scanJobs: (id: number) => request<import("./types").ScanJob[]>(`/api/authorized-directories/${id}/scan/jobs`),
  scanJob: (id: number, jobId: string) => request<import("./types").ScanJob>(`/api/authorized-directories/${id}/scan/jobs/${jobId}`),
  cancelScanJob: (id: number, jobId: string) => request<import("./types").ScanJob>(`/api/authorized-directories/${id}/scan/jobs/${jobId}`, { method: "DELETE" }),
  retryScanJob: (id: number, jobId: string) => request<import("./types").ScanJob>(`/api/authorized-directories/${id}/scan/jobs/${jobId}/retry`, { method: "POST" }),
  importPreview: (importId: number, relative_paths?: string[]) => request<import("./types").ImportConfirmResponse>(`/api/imports/${importId}/confirm`, { method: "POST", body: JSON.stringify({ confirmed: false, ...(relative_paths?.length ? { relative_paths } : {}) }) }),
  confirmImport: (importId: number, options: { relative_paths?: string[]; generate_tasks?: boolean; generate_reviews?: boolean } = {}) => request<import("./types").ImportConfirmResponse>(`/api/imports/${importId}/confirm`, { method: "POST", body: JSON.stringify({ confirmed: true, ...options }) }),
  importWeb: (url: string) => request<WebImportResponse>("/api/imports/web", { method: "POST", body: JSON.stringify({ url }) }),
  webImportPreview: (resourceId: number) => request<WebImportConfirmResponse>(`/api/imports/web/${resourceId}/confirm`, { method: "POST", body: JSON.stringify({ confirmed: false }) }),
  confirmWebImport: (resourceId: number) => request<WebImportConfirmResponse>(`/api/imports/web/${resourceId}/confirm`, { method: "POST", body: JSON.stringify({ confirmed: true }) }),
  deleteWebImport: (resourceId: number) => request<void>(`/api/imports/web/${resourceId}`, { method: "DELETE" }),
  writeDirectoryFile: (id: number, relativePath: string, content: string, confirmed = false) => request<Record<string, unknown>>(`/api/authorized-directories/${id}/write`, { method: "POST", body: JSON.stringify({ path: relativePath, content, confirmed }) }),
  revertDirectoryWrite: (directoryId: number, batchId: number, confirmed = false) => request<Record<string, unknown>>(`/api/authorized-directories/${directoryId}/write-batches/${batchId}/revert`, { method: "POST", body: JSON.stringify({ confirmed }) }),
  cloudAnalyzeDirectoryFile: (id: number, relativePath: string, prompt: string, confirmed = false) => request<Record<string, unknown>>(`/api/authorized-directories/${id}/cloud-analysis`, { method: "POST", body: JSON.stringify({ path: relativePath, prompt, confirmed }) }),
  downloadBackup: (data: unknown) => downloadJson(`learning-workstation-backup-${new Date().toISOString().slice(0, 10)}.json`, data),
};

export function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
