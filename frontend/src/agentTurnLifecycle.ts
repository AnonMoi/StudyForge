export type AgentLifecycleState =
  | "submitting"
  | "accepted"
  | "pending_local"
  | "fallback_evaluating"
  | "pending_cloud"
  | "completed"
  | "failed"
  | "cancelled"
  | "protocol_error";

export type AgentLifecycleEventType =
  | "accepted"
  | "local_started"
  | "local_failed"
  | "cloud_started"
  | "meta"
  | "token"
  | "completed"
  | "failed"
  | "cancelled"
  | "error"
  | "done"
  | "client_cancelled"
  | "client_protocol_error";

export type LifecycleEnvelope = {
  request_id?: string;
  turn_id?: string;
  attempt_id?: string;
  provider?: string;
  model_name?: string;
  route_reason?: string;
  failure_kind?: string;
  status?: string;
  replayed?: boolean;
};

export type AgentTurnLifecycle = {
  requestId: string;
  turnId: string;
  state: AgentLifecycleState;
  activeAttemptId?: string;
  localAttemptId?: string;
  provider?: string;
  modelName?: string;
  routeReason?: string;
  failureKind?: string;
  replayed: boolean;
  receivedToken: boolean;
  protocolViolation?: string;
};

export type LifecycleTransition = {
  lifecycle: AgentTurnLifecycle;
  violation?: string;
};

const ACTIVE_STATES = new Set<AgentLifecycleState>([
  "submitting",
  "accepted",
  "pending_local",
  "fallback_evaluating",
  "pending_cloud",
]);

export function createAgentTurnLifecycle(requestId: string): AgentTurnLifecycle {
  return {
    requestId,
    turnId: requestId,
    state: "submitting",
    replayed: false,
    receivedToken: false,
  };
}

export function isActiveAgentTurn(lifecycle?: AgentTurnLifecycle): boolean {
  return Boolean(lifecycle && ACTIVE_STATES.has(lifecycle.state));
}

export function agentTurnVisualState(lifecycle?: AgentTurnLifecycle): "pending" | "final" | "error" {
  if (!lifecycle || lifecycle.state === "completed") return "final";
  return isActiveAgentTurn(lifecycle) ? "pending" : "error";
}

function protocolError(current: AgentTurnLifecycle, detail: string): LifecycleTransition {
  return {
    lifecycle: {
      ...current,
      state: "protocol_error",
      failureKind: "protocol_error",
      protocolViolation: detail,
    },
    violation: detail,
  };
}

function withMetadata(current: AgentTurnLifecycle, envelope: LifecycleEnvelope): AgentTurnLifecycle {
  return {
    ...current,
    provider: envelope.provider ?? current.provider,
    modelName: envelope.model_name ?? current.modelName,
    routeReason: envelope.route_reason ?? current.routeReason,
    failureKind: envelope.failure_kind ?? current.failureKind,
  };
}

export function reduceAgentTurnLifecycle(
  current: AgentTurnLifecycle,
  type: AgentLifecycleEventType,
  envelope: LifecycleEnvelope,
): LifecycleTransition {
  if (current.state === "protocol_error") return { lifecycle: current };
  if (type === "client_protocol_error") return protocolError(current, envelope.route_reason ?? "invalid stream envelope");
  if (type !== "client_cancelled" && (envelope.request_id !== current.requestId || envelope.turn_id !== current.turnId)) {
    return protocolError(current, `identity mismatch for ${type}`);
  }

  switch (type) {
    case "accepted":
      if (current.state !== "submitting") return protocolError(current, `accepted after ${current.state}`);
      return { lifecycle: { ...withMetadata(current, envelope), state: "accepted", replayed: Boolean(envelope.replayed) } };
    case "local_started":
      if (current.state !== "accepted" || !envelope.attempt_id) return protocolError(current, `local_started after ${current.state}`);
      return { lifecycle: { ...withMetadata(current, envelope), state: "pending_local", activeAttemptId: envelope.attempt_id, localAttemptId: envelope.attempt_id } };
    case "local_failed":
      if (current.state !== "pending_local" || !envelope.attempt_id || envelope.attempt_id !== current.activeAttemptId) {
        return protocolError(current, "local_failed attempt mismatch");
      }
      return { lifecycle: { ...withMetadata(current, envelope), state: "fallback_evaluating" } };
    case "cloud_started":
      if (current.state !== "fallback_evaluating" || !envelope.attempt_id || envelope.attempt_id === current.localAttemptId) {
        return protocolError(current, `cloud_started before eligible local terminal state`);
      }
      return { lifecycle: { ...withMetadata(current, envelope), state: "pending_cloud", activeAttemptId: envelope.attempt_id } };
    case "meta":
      if (!["accepted", "pending_local", "pending_cloud"].includes(current.state)) return protocolError(current, `meta after ${current.state}`);
      return { lifecycle: withMetadata(current, envelope) };
    case "token":
      if (!(current.state === "pending_local" || current.state === "pending_cloud" || (current.state === "accepted" && current.replayed))) {
        return protocolError(current, `token before active provider or replay acceptance`);
      }
      if (envelope.attempt_id && envelope.attempt_id !== current.activeAttemptId) return protocolError(current, "token attempt mismatch");
      return { lifecycle: { ...current, receivedToken: true } };
    case "completed":
      if (!(current.state === "pending_local" || current.state === "pending_cloud" || (current.state === "accepted" && current.replayed)) || !current.receivedToken) {
        return protocolError(current, `completed after ${current.state} without accepted content`);
      }
      return { lifecycle: { ...withMetadata(current, envelope), state: "completed" } };
    case "failed":
      if (!ACTIVE_STATES.has(current.state)) return protocolError(current, `failed after ${current.state}`);
      return { lifecycle: { ...withMetadata(current, envelope), state: "failed" } };
    case "cancelled":
    case "client_cancelled":
      if (!ACTIVE_STATES.has(current.state)) return protocolError(current, `cancelled after ${current.state}`);
      return { lifecycle: { ...withMetadata(current, envelope), state: "cancelled", failureKind: "cancelled" } };
    case "error":
      if (current.state === "failed" || current.state === "cancelled") return { lifecycle: withMetadata(current, envelope) };
      if (!ACTIVE_STATES.has(current.state)) return protocolError(current, `error after ${current.state}`);
      return { lifecycle: { ...withMetadata(current, envelope), state: "failed", failureKind: envelope.failure_kind ?? "provider_error" } };
    case "done": {
      const terminalByStatus: Record<string, AgentLifecycleState> = { completed: "completed", failed: "failed", cancelled: "cancelled" };
      const expected = envelope.status ? terminalByStatus[envelope.status] : undefined;
      if (!expected || current.state !== expected) return protocolError(current, `done(${envelope.status ?? "missing"}) after ${current.state}`);
      return { lifecycle: current };
    }
  }
}

export function technicalFailureCopy(lifecycle: AgentTurnLifecycle): string {
  if (lifecycle.state === "protocol_error") return "本次请求状态异常，请重试。";
  if (lifecycle.state === "cancelled" || lifecycle.failureKind === "cancelled") return "已取消这次请求。";
  if (lifecycle.routeReason?.includes("budget_blocked") || lifecycle.failureKind === "budget") return "本地处理未完成，云端预算限制阻止了继续尝试。";
  if (lifecycle.routeReason?.includes("privacy_blocked") || lifecycle.failureKind === "permission") return "本地处理未完成，隐私设置阻止了云端处理。";
  if (lifecycle.routeReason === "cloud_disabled") return "本地服务暂时不可用，且未启用云端补充。";
  if (lifecycle.failureKind === "timeout") return "本地处理超时，暂时无法完成。";
  if (lifecycle.failureKind === "unavailable") return "处理服务暂时不可用。";
  return "处理服务暂时异常，请稍后重试。";
}

export function pendingPrimaryCopy(lifecycle: AgentTurnLifecycle): string {
  return lifecycle.state === "submitting" || lifecycle.state === "accepted" ? "正在接收…" : "正在整理…";
}

export function pendingTechnicalCopy(lifecycle: AgentTurnLifecycle): string | undefined {
  if (lifecycle.state === "pending_local") return "正在本机处理";
  if (lifecycle.state === "fallback_evaluating") return "正在确认可用的继续方式";
  if (lifecycle.state === "pending_cloud") return "已切换到云端继续处理";
  return undefined;
}

export function completedProviderCopy(lifecycle: AgentTurnLifecycle): string | undefined {
  if (lifecycle.provider === "ollama") return "本机处理";
  if (lifecycle.provider === "zhiapi" || lifecycle.provider === "cloud") return "云端补充";
  return undefined;
}
