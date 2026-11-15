import { useEffect, useMemo, useState } from "react";
import { api, getApiErrorMessage } from "./api";
import type { TeachingAttempt, TeachingRecommendations, TeachingSession } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

export default function InterviewWorkspace({ onNotice, onError }: Props) {
  const [sessions, setSessions] = useState<TeachingSession[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [role, setRole] = useState("");
  const [focus, setFocus] = useState("后端开发基础、项目经历和学习方法");
  const [answer, setAnswer] = useState("");
  const [recommendations, setRecommendations] = useState<TeachingRecommendations | null>(null);
  const [busy, setBusy] = useState(false);

  const selected = useMemo(() => sessions.find(item => item.id === selectedId) ?? null, [sessions, selectedId]);
  const currentAttempt: TeachingAttempt | null = selected?.attempts[selected.attempts.length - 1] ?? null;

  async function load() {
    try {
      const data = (await api.teachingSessions()).filter(item => item.title.startsWith("模拟面试 · "));
      setSessions(data);
      if (selectedId && data.some(item => item.id === selectedId)) return;
      if (data[0]) setSelectedId(data[0].id);
    } catch (error) { onError(getApiErrorMessage(error)); }
  }
  useEffect(() => { void load(); }, []);

  async function createInterview() {
    if (!role.trim()) return;
    setBusy(true);
    try {
      const created = await api.createTeachingSession({ title: `模拟面试 · ${role.trim()}`, explanation: `目标岗位：${role.trim()}\n面试范围：${focus.trim()}` });
      setSelectedId(created.id); setRole(""); setRecommendations(null); await load(); onNotice("模拟面试已创建。");
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }

  async function generateQuestion() {
    if (!selected) return;
    setBusy(true);
    try { await api.generateTeachingMaterial(selected.id, `你是严谨的面试官。请围绕岗位“${selected.title.replace("模拟面试 · ", "")}"和面试范围“${focus}”，先给出简短的面试背景，再提出一个需要候选人用自己的经历或技术判断回答的问题。不要直接给出答案。`); await load(); onNotice("面试问题已生成。"); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }

  async function submitAnswer() {
    if (!selected || !currentAttempt || !answer.trim()) return;
    setBusy(true);
    try { await api.answerTeachingAttempt(selected.id, currentAttempt.id, answer.trim()); setAnswer(""); await load(); onNotice("回答已保存，可以开始评价。"); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }

  async function evaluateAnswer() {
    if (!selected || !currentAttempt) return;
    setBusy(true);
    try { await api.evaluateTeachingAttempt(selected.id, currentAttempt.id); setRecommendations(await api.teachingRecommendations(selected.id)); await load(); onNotice("面试回答已评价。"); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }

  return <div className="interview-workspace">
    <section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">面试场次</h2><p className="sf-surface-description">本地优先保存面试问题、回答、评价和复习建议</p></div><span className="sf-surface-metadata">{sessions.length} 场</span></div><div className="interview-policy sf-notice-surface"><strong>使用边界</strong><span>面试内容默认保存在本机；模型调用仍遵守现有路由、预算和确认策略。生成内容是训练材料，不代表真实岗位结论。</span></div><div className="interview-form"><input aria-label="目标岗位" value={role} onChange={event => setRole(event.target.value)} placeholder="例如：Python 后端实习生" /><input aria-label="面试范围" value={focus} onChange={event => setFocus(event.target.value)} placeholder="面试范围，用顿号分隔" /><button className="primary-button" type="button" disabled={!role.trim() || busy} onClick={() => void createInterview()}>创建面试</button></div><div className="interview-session-list">{sessions.map(session => <button className={`teaching-session-row ${selectedId === session.id ? "selected" : ""}`} key={session.id} type="button" onClick={() => { setSelectedId(session.id); setRecommendations(null); }}><strong>{session.title}</strong><small>{session.attempts.length ? "已有问题" : "待生成问题"} · {session.status === "completed" ? "已完成" : "进行中"}</small></button>)}</div></section>
    <section className="interview-main sf-open-section">{selected ? <><div className="sf-surface-header"><div><h2 className="sf-section-title">{selected.title}</h2><p className="sf-surface-description">完成一轮回答后再创建下一场，避免混淆不同岗位的评价。</p></div><button className="ghost-button" type="button" disabled={busy || Boolean(selected.attempts.length)} onClick={() => void generateQuestion()}>{busy ? "处理中…" : selected.attempts.length ? "问题已生成" : "生成面试问题"}</button></div><article className="interview-brief"><strong>面试背景</strong><p>{selected.explanation}</p></article>{currentAttempt ? <article className="teaching-attempt"><span>面试问题</span><strong>{currentAttempt.prompt}</strong>{currentAttempt.rubric.length ? <small>评价关注：{currentAttempt.rubric.join("、")}</small> : null}{currentAttempt.evaluated_at ? <div className="teaching-feedback"><div className="teaching-score">{currentAttempt.score ?? "—"}<small> / 5</small></div><p>{currentAttempt.feedback}</p>{currentAttempt.error_type && <em>薄弱点：{currentAttempt.error_type}</em>}<small>{currentAttempt.recommendation}</small></div> : currentAttempt.answered_at ? <div className="button-row"><span className="muted">回答已保存</span><button className="primary-button" type="button" disabled={busy} onClick={() => void evaluateAnswer()}>评价回答</button></div> : <div className="stack-form"><textarea aria-label="面试回答" rows={8} value={answer} onChange={event => setAnswer(event.target.value)} placeholder="像真实面试一样回答，尽量给出背景、行动和结果……" /><button className="primary-button" type="button" disabled={busy || !answer.trim()} onClick={() => void submitAnswer()}>提交回答</button></div>}</article> : <div className="empty"><p>生成一个问题开始模拟面试。</p></div>}{recommendations && <article className="teaching-recommendations"><span>复习建议</span>{recommendations.recommendations.length ? recommendations.recommendations.map((item, index) => <p key={`${item}-${index}`}>{item}</p>) : <p>本轮没有新增复习建议。</p>}</article>}</> : <div className="empty"><p>先创建一场模拟面试。</p></div>}</section>
  </div>;
}
