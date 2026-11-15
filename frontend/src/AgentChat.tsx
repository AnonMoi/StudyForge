import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import MarkdownRenderer from "./MarkdownRenderer";
import { api, getApiErrorMessage } from "./api";
import type { AgentChatResponse } from "./types";
import {
  agentTurnVisualState,
  completedProviderCopy,
  createAgentTurnLifecycle,
  isActiveAgentTurn,
  pendingPrimaryCopy,
  pendingTechnicalCopy,
  reduceAgentTurnLifecycle,
  technicalFailureCopy,
  type AgentLifecycleEventType,
  type AgentTurnLifecycle,
  type LifecycleEnvelope,
} from "./agentTurnLifecycle";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
type Action = NonNullable<AgentChatResponse["actions"]>[number];
type Message = {
  id: string;
  turnId?: string;
  persona?: string;
  role: "user" | "assistant";
  text: string;
  sourceText?: string;
  lifecycle?: AgentTurnLifecycle;
  outputType?: string;
  basis?: string[];
  uncertainty?: string;
  actions?: Action[];
  pendingAction?: { action: Action; preview: Record<string, unknown> };
  actionCompleted?: string;
};
type HistoryMessage = {
  id?: number;
  turn_id?: string | null;
  request_id?: string | null;
  persona?: string | null;
  role: "user" | "assistant";
  turn_status?: string | null;
  provider?: string | null;
  model_name?: string | null;
  route_reason?: string | null;
  failure_kind?: string | null;
  content: string;
};
type StreamEnvelope = Partial<AgentChatResponse> & LifecycleEnvelope & {
  chunk?: string;
  message?: string;
  stage?: string;
  attempt_status?: string;
};

const serverEvents = new Set<AgentLifecycleEventType>([
  "accepted", "local_started", "local_failed", "cloud_started", "meta", "token",
  "completed", "failed", "cancelled", "error", "done",
]);
const sessionKey = "learning-workstation-session-id";
const previewFieldNames: Record<string, string> = { title: "内容", folder: "分类", status: "加入后的状态", name: "名称", review_date: "复习日期", from_status: "原来", to_status: "确认后" };

function visiblePreviewValue(key: string, value: unknown) {
  if (key === "folder" && value === "Inbox") return "收集箱";
  const states: Record<string, string> = { not_started: "未开始", active: "进行中", completed: "已完成", mastered: "已掌握" };
  return states[String(value)] ?? String(value ?? "—");
}

function restoredLifecycle(item: HistoryMessage, turnId: string, state: "completed" | "failed" | "cancelled"): AgentTurnLifecycle {
  return {
    ...createAgentTurnLifecycle(turnId),
    state,
    provider: item.provider ?? undefined,
    modelName: item.model_name ?? undefined,
    routeReason: item.route_reason ?? undefined,
    failureKind: state === "cancelled" ? "cancelled" : item.failure_kind ?? undefined,
    receivedToken: state === "completed",
  };
}

function historyMessages(items: HistoryMessage[]): Message[] {
  return items.filter(item => item.turn_status !== "pending").flatMap((item, index): Message[] => {
    const turnId = item.turn_id ?? item.request_id ?? undefined;
    const base: Message = {
      id: `history-${item.id ?? index}`,
      turnId,
      persona: item.persona ?? undefined,
      role: item.role,
      text: item.content,
    };
    if (!turnId) return [base];
    if (item.role === "user" && (item.turn_status === "failed" || item.turn_status === "cancelled")) {
      const state = item.turn_status;
      return [base, {
        id: `history-${state}-${turnId}`,
        turnId,
        persona: item.persona ?? undefined,
        role: "assistant",
        text: "",
        sourceText: item.content,
        lifecycle: restoredLifecycle(item, turnId, state),
      }];
    }
    if (item.role === "assistant" && item.turn_status === "completed") base.lifecycle = restoredLifecycle(item, turnId, "completed");
    return [base];
  });
}

const sessionId = (() => {
  const existing = window.localStorage.getItem(sessionKey);
  if (existing) return existing;
  const created = `desktop-${crypto.randomUUID()}`;
  window.localStorage.setItem(sessionKey, created);
  return created;
})();

export default function AgentChat({ personaName = "学习伙伴", persona = "study-coach" }: { personaName?: string; persona?: "study-coach" | "anna" }) {
  const isAnna = persona === "anna";
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const activeTurnRef = useRef<string | null>(null);
  const activeRequestRef = useRef<AbortController | null>(null);
  const composingRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const followLatestRef = useRef(true);
  const busy = messages.some(item => item.role === "assistant" && isActiveAgentTurn(item.lifecycle));

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/agent/history/${sessionId}`)
      .then(response => {
        if (!response.ok) throw new Error("历史对话暂时没有读出来");
        return response.json();
      })
      .then(items => {
        if (cancelled) return;
        const history = historyMessages(items as HistoryMessage[]);
        setMessages(current => {
          if (!current.length) return history;
          const liveKeys = new Set(current.filter(item => item.turnId).map(item => `${item.turnId}:${item.role}`));
          return [...history.filter(item => !item.turnId || !liveKeys.has(`${item.turnId}:${item.role}`)), ...current];
        });
      })
      .catch(err => { if (!cancelled) setHistoryError(err instanceof Error ? err.message : "历史记录加载失败"); })
      .finally(() => { if (!cancelled) setHistoryLoading(false); });
    return () => {
      cancelled = true;
      activeRequestRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    const nextHeight = Math.min(textarea.scrollHeight, 168);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 168 ? "auto" : "hidden";
  }, [message]);

  useEffect(() => {
    const container = messagesRef.current;
    if (container && followLatestRef.current) container.scrollTop = container.scrollHeight;
  }, [messages]);

  const updateAssistant = (assistantId: string, turnId: string, update: (entry: Message) => Message) => {
    if (activeTurnRef.current !== turnId) return;
    setMessages(current => current.map(entry => entry.id === assistantId ? update(entry) : entry));
  };

  function cancelActiveTurn(assistantId: string, turnId: string) {
    if (activeTurnRef.current !== turnId) return;
    setMessages(current => current.map(entry => {
      if (entry.id !== assistantId || !entry.lifecycle) return entry;
      return { ...entry, lifecycle: reduceAgentTurnLifecycle(entry.lifecycle, "client_cancelled", {}).lifecycle };
    }));
    activeTurnRef.current = null;
    activeRequestRef.current?.abort();
    activeRequestRef.current = null;
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  }

  async function sendMessage(text: string, retry?: { assistantId: string; previousTurnId: string }) {
    const trimmed = text.trim();
    if (!trimmed || activeTurnRef.current) return;
    const turnId = crypto.randomUUID();
    const assistantId = retry?.assistantId ?? `assistant-${turnId}`;
    const request = new AbortController();
    let lifecycle = createAgentTurnLifecycle(turnId);
    let assistantText = "";
    let doneSeen = false;
    activeTurnRef.current = turnId;
    activeRequestRef.current = request;
    followLatestRef.current = true;
    setError("");

    if (retry) {
      setMessages(current => current.map(entry => {
        if (entry.id === assistantId) return { ...entry, turnId, text: "", lifecycle, outputType: undefined, basis: undefined, uncertainty: undefined, actions: undefined, pendingAction: undefined, actionCompleted: undefined };
        if (entry.turnId === retry.previousTurnId && entry.role === "user") return { ...entry, turnId };
        return entry;
      }));
    } else {
      setMessages(current => [...current,
        { id: `user-${turnId}`, turnId, persona, role: "user", text: trimmed },
        { id: assistantId, turnId, persona, role: "assistant", text: "", sourceText: trimmed, lifecycle },
      ]);
      setMessage("");
    }

    const applyEvent = (type: AgentLifecycleEventType, envelope: StreamEnvelope) => {
      const transition = reduceAgentTurnLifecycle(lifecycle, type, envelope);
      lifecycle = transition.lifecycle;
      if (transition.violation) console.error("agent_stream_protocol_violation", { requestId: turnId, event: type, detail: transition.violation });
      updateAssistant(assistantId, turnId, entry => ({ ...entry, lifecycle }));
      return !transition.violation;
    };
    const failProtocol = (detail: string) => applyEvent("client_protocol_error", { route_reason: detail });

    try {
      const response = await fetch(`${API_BASE}/api/agent/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmed, session_id: sessionId, persona, request_id: turnId }),
        signal: request.signal,
      });
      if (!response.ok || !response.body) {
        applyEvent("error", { request_id: turnId, turn_id: turnId, failure_kind: "provider_error", route_reason: response.ok ? "empty_stream" : "transport_error" });
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const handleEvent = (rawEvent: string) => {
        if (activeTurnRef.current !== turnId || lifecycle.state === "protocol_error") return;
        const lines = rawEvent.split("\n");
        const type = lines.find(line => line.startsWith("event: "))?.slice(7) ?? "";
        const data = lines.filter(line => line.startsWith("data: ")).map(line => line.slice(6)).join("\n");
        if (!serverEvents.has(type as AgentLifecycleEventType)) return void failProtocol(`unknown event: ${type || "missing"}`);
        let envelope: StreamEnvelope;
        try { envelope = JSON.parse(data) as StreamEnvelope; }
        catch { return void failProtocol("invalid event JSON"); }
        const eventType = type as AgentLifecycleEventType;
        if (!applyEvent(eventType, envelope)) return;
        if (eventType === "token") {
          const chunk = envelope.chunk ?? "";
          assistantText += chunk;
          updateAssistant(assistantId, turnId, entry => ({ ...entry, text: entry.text + chunk }));
        } else if (eventType === "meta") {
          updateAssistant(assistantId, turnId, entry => ({ ...entry, outputType: envelope.output_type, basis: envelope.basis, uncertainty: envelope.uncertainty, actions: envelope.actions }));
        } else if (eventType === "done") doneSeen = true;
      };

      while (true) {
        const result = await reader.read();
        if (activeTurnRef.current !== turnId) {
          await reader.cancel();
          return;
        }
        buffer += decoder.decode(result.value ?? new Uint8Array(), { stream: !result.done });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        events.filter(Boolean).forEach(handleEvent);
        if (lifecycle.state === "protocol_error") {
          await reader.cancel();
          return;
        }
        if (result.done) break;
      }
      if (buffer.trim()) handleEvent(buffer);
      if ((lifecycle as AgentTurnLifecycle).state === "protocol_error") return;
      if (!doneSeen || !["completed", "failed", "cancelled"].includes(lifecycle.state)) failProtocol("stream ended without matching done event");
      if (lifecycle.state === "completed" && !assistantText.trim()) failProtocol("completed without response content");
    } catch (err) {
      if (request.signal.aborted || activeTurnRef.current !== turnId) return;
      console.error("agent_stream_transport_failure", { requestId: turnId, error: err instanceof Error ? err.name : "unknown" });
      applyEvent("error", { request_id: turnId, turn_id: turnId, failure_kind: "provider_error", route_reason: "transport_error" });
    } finally {
      if (activeTurnRef.current === turnId) {
        activeTurnRef.current = null;
        activeRequestRef.current = null;
        window.requestAnimationFrame(() => textareaRef.current?.focus());
      }
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void sendMessage(message);
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (event.nativeEvent.isComposing || composingRef.current || event.keyCode === 229) return;
    event.preventDefault();
    if (!busy && message.trim()) event.currentTarget.form?.requestSubmit();
  }

  async function previewAction(messageId: string, action: Action) {
    try {
      const result = await api.agentChange(action.operation, action.payload);
      if (!result.success) throw new Error(result.error ?? "暂时不能检查这项建议");
      setMessages(current => current.map(entry => entry.id === messageId ? { ...entry, pendingAction: { action, preview: result.preview } } : entry));
    } catch (err) { setError(getApiErrorMessage(err)); }
  }

  async function confirmAction(messageId: string, pending: NonNullable<Message["pendingAction"]>) {
    try {
      const result = await api.agentChange(pending.action.operation, pending.action.payload, true);
      if (!result.success || !result.executed) throw new Error(result.error ?? "这项改动没有保存成功");
      setMessages(current => current.map(entry => entry.id === messageId ? { ...entry, pendingAction: undefined, actionCompleted: "已经按你的确认保存。" } : entry));
    } catch (err) { setError(getApiErrorMessage(err)); }
  }

  const quickPrompts = isAnna ? ["我今天先做什么？", "帮我把目标拆小一点", "我有点拖延，怎么办？"] : ["我这周应该先补哪一块？", "帮我把这个目标拆小一点", "根据最近记录，我下一步做什么？"];
  const speakerName = (item: Message) => item.persona === "anna" ? "八奈见杏菜" : item.persona === "study-coach" ? "学习伙伴" : personaName;
  return <section className={isAnna ? "anna-conversation" : "coach-consultation"}>
    {!isAnna && <div className="coach-context"><div><h2>和学习伙伴聊一聊</h2><p>问题越具体，越容易找到下一步。</p></div><span>对话保存在本机</span></div>}
    <div className={isAnna ? "anna-conversation__stream" : "coach-conversation"} ref={messagesRef} aria-label={isAnna ? undefined : "与学习伙伴的对话"} onScroll={event => {
      const target = event.currentTarget;
      followLatestRef.current = target.scrollHeight - target.scrollTop - target.clientHeight < 72;
    }}>
      {historyLoading && <div className={isAnna ? "anna-conversation__loading" : "coach-conversation__loading"} role="status">正在读取以前的对话…</div>}
      {historyError && <div className={isAnna ? "anna-conversation__history-error" : "coach-conversation__history-error sf-notice-surface sf-notice-surface--error"} role="status">历史对话暂时没有读出来，你仍然可以开始新对话。</div>}
      {!historyLoading && !messages.length && <div className={isAnna ? "anna-conversation__empty" : "coach-conversation__empty"}><strong>{isAnna ? "温水，今天准备从哪件事开始？" : "你现在最想解决哪件学习上的事？"}</strong><p>{isAnna ? "别把计划写成愿望清单，先挑一件今天能做完的事。" : "可以说说目标、卡住的地方，或者让学习伙伴一起看最近的记录。"}</p><div className={isAnna ? "anna-quick-prompts" : "coach-conversation__prompts"}>{quickPrompts.map(prompt => <button type="button" className="sf-button sf-button--tertiary sf-button--compact" key={prompt} onClick={() => { setMessage(prompt); textareaRef.current?.focus(); }}>{prompt}</button>)}</div></div>}
      {messages.map(item => {
        const visualState = agentTurnVisualState(item.lifecycle);
        const technicalStatus = item.lifecycle && pendingTechnicalCopy(item.lifecycle);
        const providerCopy = item.lifecycle && completedProviderCopy(item.lifecycle);
        const canCancel = item.lifecycle && ["pending_local", "fallback_evaluating", "pending_cloud"].includes(item.lifecycle.state);
        return <div className={`${isAnna ? "anna-turn" : "coach-turn"} ${item.role} is-${visualState}`} key={item.id} data-turn-role={item.role} data-turn-id={item.turnId} data-lifecycle-state={item.lifecycle?.state} data-provider={item.lifecycle?.provider}>
          {item.role === "user" ? <p>{item.text}</p> : <>
            <span className={isAnna ? "anna-turn__speaker" : "coach-turn__speaker"}>{speakerName(item)}</span>
            {visualState === "pending" && item.lifecycle ? <div className={isAnna ? "anna-turn__pending" : "coach-turn__pending"}>
              <div className={isAnna ? "anna-turn__pending-main" : "coach-turn__pending-main"} role="status" aria-live="polite" aria-atomic="true"><i aria-hidden="true" /><span>{pendingPrimaryCopy(item.lifecycle)}</span>{technicalStatus && <small>{technicalStatus}</small>}</div>
              {canCancel && <button type="button" className="sf-button sf-button--tertiary sf-button--compact" aria-label="取消这次请求" onClick={() => item.turnId && cancelActiveTurn(item.id, item.turnId)}>取消</button>}
            </div> : visualState === "error" && item.lifecycle ? <div className={isAnna ? "anna-turn__error" : "coach-turn__error"} role={item.lifecycle.state === "cancelled" ? "status" : "alert"}><p>{technicalFailureCopy(item.lifecycle)}</p><button type="button" className="sf-button sf-button--tertiary sf-button--compact" aria-label="重新发送这条消息" onClick={() => item.turnId && item.sourceText && void sendMessage(item.sourceText, { assistantId: item.id, previousTurnId: item.turnId })} disabled={busy}>再试一次</button></div> : <>
              {item.outputType && <div className={isAnna ? "anna-turn__kind" : "coach-turn__kind"}>{item.outputType === "explain" ? "解释思路" : item.outputType === "operation" ? "可以这样做" : "学习建议"}</div>}
              <MarkdownRenderer content={item.text} />
              {item.lifecycle?.state === "completed" && <span className="sr-only" role="status">回答已完成</span>}
              {providerCopy && <small className={isAnna ? "anna-turn__source" : "coach-turn__source"}>{providerCopy}</small>}
              {item.uncertainty && <small className={isAnna ? "anna-turn__uncertainty" : "coach-turn__uncertainty"}>需要留意：{item.uncertainty}</small>}
              {item.basis?.length ? <small className={isAnna ? "anna-turn__basis" : "coach-turn__basis"}>参考了：{item.basis.join("、")}</small> : null}
              {item.actions?.length ? <div className={isAnna ? "anna-turn__actions" : "coach-turn__actions"}>{item.actions.map(action => <button type="button" className="ghost-button sf-button--compact" key={action.operation} onClick={() => void previewAction(item.id, action)}>{action.label}</button>)}</div> : null}
              {item.pendingAction && <div className={isAnna ? "anna-action-review" : "coach-turn__action-review"}><span>确认前再看一眼</span><dl>{Object.entries(item.pendingAction.preview).filter(([key]) => !["operation", "task_id", "stage_id"].includes(key)).map(([key, value]) => <div key={key}><dt>{previewFieldNames[key] ?? "内容"}</dt><dd>{visiblePreviewValue(key, value)}</dd></div>)}</dl><p>只有确认后才会保存这项改动。</p><div className="button-row"><button type="button" className="ghost-button" onClick={() => setMessages(current => current.map(entry => entry.id === item.id ? { ...entry, pendingAction: undefined } : entry))}>先不改</button><button type="button" className="primary-button" onClick={() => void confirmAction(item.id, item.pendingAction!)}>确认保存</button></div></div>}
              {item.actionCompleted && <small className={isAnna ? "anna-action-complete" : "coach-turn__action-complete"} role="status">{item.actionCompleted}</small>}
            </>}
          </>}
        </div>;
      })}
    </div>
    {error && <div className={isAnna ? "anna-conversation__error" : "coach-conversation__error sf-notice-surface sf-notice-surface--error"} role="alert">{error}</div>}
    <form className={`${isAnna ? "anna-composer" : "coach-composer"} sf-composite-field`} onSubmit={submit}>
      <label className={isAnna ? "anna-composer__field" : "coach-composer__field"}><span>想聊什么</span><textarea className="sf-field" ref={textareaRef} aria-label={`发送给${isAnna ? "杏菜" : "学习伙伴"}`} value={message} onChange={event => setMessage(event.target.value)} onKeyDown={handleComposerKeyDown} onCompositionStart={() => { composingRef.current = true; }} onCompositionEnd={() => { composingRef.current = false; }} placeholder={isAnna ? "跟杏菜说说你正在做什么…" : "写下目标、问题，或者最近卡住的地方…"} rows={1} /></label>
      <div className={isAnna ? "anna-composer__footer" : "coach-composer__footer"}><small>Enter 发送 · Shift+Enter 换行</small><button type="submit" className="sf-button sf-button--primary" disabled={busy || !message.trim()}>{busy ? "等待回复" : "发送"}</button></div>
    </form>
  </section>;
}
