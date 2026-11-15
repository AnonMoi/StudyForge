import { FormEvent, useEffect, useState } from "react";
import { api } from "./api";
import type { DailyLog } from "./types";

type Draft = {
  raw_text: string;
  extracted_topics: string[];
  extracted_duration: number | null;
  extracted_outputs: string[];
  understood_content: string[];
  unresolved_questions: string[];
  completed_tasks: string[];
  resolved_questions: string[];
  next_steps: string[];
  self_assessment: string;
  ai_extracted: Record<string, unknown>;
};

const emptyDraft: Draft = { raw_text: "", extracted_topics: [], extracted_duration: null, extracted_outputs: [], understood_content: [], unresolved_questions: [], completed_tasks: [], resolved_questions: [], next_steps: [], self_assessment: "", ai_extracted: {} };
const draftFrom = (data: Record<string, unknown>, rawText: string): Draft => ({
  // The organizer may suggest structure, but the user's original writing is authoritative.
  raw_text: rawText,
  extracted_topics: Array.isArray(data.extracted_topics) ? data.extracted_topics.map(String) : [],
  extracted_duration: typeof data.extracted_duration === "number" ? data.extracted_duration : null,
  extracted_outputs: Array.isArray(data.extracted_outputs) ? data.extracted_outputs.map(String) : [],
  understood_content: Array.isArray(data.understood_content) ? data.understood_content.map(String) : [],
  unresolved_questions: Array.isArray(data.unresolved_questions) ? data.unresolved_questions.map(String) : [],
  completed_tasks: Array.isArray(data.completed_tasks) ? data.completed_tasks.map(String) : [],
  resolved_questions: Array.isArray(data.resolved_questions) ? data.resolved_questions.map(String) : [],
  next_steps: Array.isArray(data.next_steps) ? data.next_steps.map(String) : [],
  self_assessment: typeof data.self_assessment === "string" ? data.self_assessment : "",
  ai_extracted: { ...data },
});
const lines = (value: string) => value.split("\n").map(item => item.trim()).filter(Boolean);
const localDateValue = (date: Date) => [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
const formatJournalDate = (date: Date) => new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "long" }).format(date);
const formatLogDate = (date: string) => {
  const parsed = new Date(`${date}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? date : new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric" }).format(parsed);
};
const logStatus = (status: DailyLog["structured_status"]) => status === "confirmed" ? "已整理" : status === "pending_review" ? "等你确认" : "保留原文";
const logTitle = (log: DailyLog) => log.extracted_topics?.length ? log.extracted_topics.slice(0, 2).join(" · ") : "学习记录";

export default function LogWorkspace({ onNotice, onError }: { onNotice: (message: string) => void; onError: (message: string) => void }) {
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [history, setHistory] = useState<DailyLog[]>([]);
  const [busy, setBusy] = useState(false);
  const [previewed, setPreviewed] = useState(false);
  const [editingLogId, setEditingLogId] = useState<number | null>(null);
  const today = new Date();

  const loadHistory = async () => { try { setHistory(await api.dailyLogs()); } catch (error) { onError(error instanceof Error ? error.message : "无法读取学习日志"); } };
  useEffect(() => { void loadHistory(); }, []);

  async function preview(event: FormEvent) {
    event.preventDefault(); if (!text.trim()) return; setBusy(true);
    try { const result = await api.parseDailyLog(text); setDraft(draftFrom(result.data, text)); setPreviewed(true); onNotice(result.success ? "杏菜已经整理好了，原文没有改动。检查一下再保存。" : "有些内容没有整理出来，你可以直接补充，也可以只保存原文。"); }
    catch (error) { onError(error instanceof Error ? error.message : "暂时没能整理这段记录，请稍后再试"); }
    finally { setBusy(false); }
  }
  async function confirmSave() {
    if (!draft.raw_text.trim()) return; setBusy(true);
    try {
      const fields = { extracted_topics: draft.extracted_topics, extracted_duration: draft.extracted_duration, extracted_outputs: draft.extracted_outputs, understood_content: draft.understood_content, unresolved_questions: draft.unresolved_questions, completed_tasks: draft.completed_tasks, resolved_questions: draft.resolved_questions, next_steps: draft.next_steps, self_assessment: draft.self_assessment, ai_extracted: draft.ai_extracted };
      if (editingLogId === null) await api.createDailyLog(draft.raw_text, true, fields);
      else await api.updateDailyLog(editingLogId, { raw_text: draft.raw_text, ...fields, confirm: true });
      setText(""); setDraft(emptyDraft); setPreviewed(false); setEditingLogId(null); await loadHistory(); onNotice(editingLogId === null ? "今天的学习记录已保存。" : "这条学习记录已更新。");
    }
    catch (error) { onError(error instanceof Error ? error.message : "保存失败"); }
    finally { setBusy(false); }
  }
  function editLog(log: DailyLog) {
    setEditingLogId(log.id);
    setText(log.raw_text);
    setDraft({ raw_text: log.raw_text, extracted_topics: log.extracted_topics ?? [], extracted_duration: log.extracted_duration, extracted_outputs: log.extracted_outputs ?? [], understood_content: log.understood_content ?? [], unresolved_questions: log.unresolved_questions ?? [], completed_tasks: log.completed_tasks ?? [], resolved_questions: log.resolved_questions ?? [], next_steps: log.next_steps ?? [], self_assessment: log.self_assessment ?? "", ai_extracted: log.ai_extracted ?? {} });
    setPreviewed(true);
  }
  function cancelEdit() {
    setEditingLogId(null); setText(""); setDraft(emptyDraft); setPreviewed(false);
  }
  const update = (key: keyof Draft, value: string) => setDraft(current => ({ ...current, [key]: key === "extracted_duration" ? (value ? Number(value) : null) : ["extracted_topics", "extracted_outputs", "understood_content", "unresolved_questions", "completed_tasks", "resolved_questions", "next_steps"].includes(key) ? lines(value) : value }));
  const focusEditor = () => document.getElementById("daily-log-editor")?.focus();

  return <div className="journal-workspace" data-design-contract="journal-stream">
    <section className="journal-editor sf-writing-surface" aria-labelledby="journal-editor-title">
      <header className="journal-editor-heading sf-surface-header">
        <div><h2 className="sf-surface-title" id="journal-editor-title">今天的学习记录</h2><time dateTime={localDateValue(today)}>{formatJournalDate(today)}</time></div>
        <p className="sf-surface-description">先写下真实发生的事，不用急着写成总结。</p>
      </header>
      <form className="journal-writing-form" onSubmit={preview}>
        <label className="journal-writing-label" htmlFor="daily-log-editor">今天的学习记录</label>
        <textarea className="sf-field" id="daily-log-editor" aria-label="今天的学习记录" value={text} onChange={event => setText(event.target.value)} rows={5} placeholder="学了什么、做了多久、哪里想明白了、哪里还容易混淆……" />
        <div className="form-footer journal-editor-footer">
          <span className="journal-preservation-note">原文保留 · 整理后仍可编辑，确认后才保存</span>
          <button className="sf-button sf-button--secondary journal-organize-button" disabled={busy || !text.trim()}><span className="journal-anna-avatar" aria-hidden="true"><img src="/characters/anna/face-first-upscaled.png" alt="" /></span><span>{busy ? "正在整理…" : "杏菜帮我整理"}</span></button>
        </div>
      </form>

      {previewed && <div className="journal-review-sheet sf-utility-surface">
        <div className="log-review-heading"><div><strong>{editingLogId === null ? "整理后的学习记录" : "修改这条学习记录"}</strong><p>原文没有被覆盖。下面只是可编辑的归纳，确认后才会写入。</p></div>{editingLogId !== null && <span>记录 {editingLogId}</span>}</div>
        <label>今天的原始记录<textarea className="sf-field" aria-label="今天的原始记录" value={draft.raw_text} onChange={event => update("raw_text", event.target.value)} rows={4} /></label>
        <div className="journal-review-fields">
          <label>今天涉及哪些内容<textarea className="sf-field" aria-label="今天涉及哪些内容" value={draft.extracted_topics.join("\n")} onChange={event => update("extracted_topics", event.target.value)} rows={3} placeholder="每行写一项" /></label>
          <label className="journal-review-duration">大约学了多久（分钟）<input className="sf-field" aria-label="学习时长（分钟）" type="number" min="0" value={draft.extracted_duration ?? ""} onChange={event => update("extracted_duration", event.target.value)} /></label>
          <label>我弄懂了什么<textarea className="sf-field" aria-label="我弄懂了什么" value={draft.understood_content.join("\n")} onChange={event => update("understood_content", event.target.value)} rows={3} placeholder="每行写一项" /></label>
          <label>我完成了什么<textarea className="sf-field" aria-label="我完成了什么" value={draft.completed_tasks.join("\n")} onChange={event => update("completed_tasks", event.target.value)} rows={3} placeholder="练习、任务或阶段性成果" /></label>
          <label>留下了什么<textarea className="sf-field" aria-label="留下了什么学习成果" value={draft.extracted_outputs.join("\n")} onChange={event => update("extracted_outputs", event.target.value)} rows={3} placeholder="笔记、代码、图表或文档" /></label>
          <label>哪些问题解决了<textarea className="sf-field" aria-label="哪些问题解决了" value={draft.resolved_questions.join("\n")} onChange={event => update("resolved_questions", event.target.value)} rows={3} /></label>
          <label>还卡在哪里<textarea className="sf-field" aria-label="还卡在哪里" value={draft.unresolved_questions.join("\n")} onChange={event => update("unresolved_questions", event.target.value)} rows={3} /></label>
          <label>下一次准备做什么<textarea className="sf-field" aria-label="下一次准备做什么" value={draft.next_steps.join("\n")} onChange={event => update("next_steps", event.target.value)} rows={3} /></label>
          <label className="journal-review-self-assessment">今天学得怎么样<input className="sf-field" aria-label="今天学得怎么样" value={draft.self_assessment} onChange={event => update("self_assessment", event.target.value)} placeholder="例如：大体明白了，但还需要练习" /></label>
        </div>
        <div className="form-footer"><button type="button" className="sf-button sf-button--tertiary" onClick={cancelEdit}>取消</button><button type="button" className="sf-button sf-button--tertiary" onClick={() => setPreviewed(false)}>回到原文</button><button type="button" className="sf-button sf-button--primary" disabled={busy || !draft.raw_text.trim()} onClick={() => void confirmSave()}>{busy ? "保存中…" : editingLogId === null ? "保存这条记录" : "保存修改"}</button></div>
      </div>}
    </section>

    <section className="journal-timeline sf-open-section" aria-labelledby="journal-timeline-title">
      <header className="journal-timeline-heading sf-surface-header"><div><h2 className="sf-section-title" id="journal-timeline-title">学习日志时间线</h2><p className="sf-surface-description">按日期回看真实的学习上下文。</p></div><span className="sf-surface-metadata">{history.length ? `${history.length} 条记录` : "还没有记录"}</span></header>
      {history.length ? <div className="journal-stream">{history.map(log => <article className="journal-entry" key={log.id}>
        <span className="journal-entry-marker" aria-hidden="true" />
        <div className="journal-entry-date"><time dateTime={log.log_date}>{formatLogDate(log.log_date)}</time>{log.extracted_duration != null && <small>{log.extracted_duration} 分钟</small>}</div>
        <div className="journal-entry-content"><h3>{logTitle(log)}</h3><p>{log.raw_text}</p>{log.extracted_outputs?.length ? <small>留下：{log.extracted_outputs.slice(0, 2).join(" · ")}</small> : null}</div>
        <div className="journal-entry-actions"><span className="sf-status-text neutral journal-entry-status">{logStatus(log.structured_status)}</span><button type="button" className="sf-button sf-button--tertiary sf-button--compact journal-entry-edit" onClick={() => editLog(log)}>修改</button></div>
      </article>)}</div> : <div className="journal-empty"><span className="journal-empty-origin" aria-hidden="true" /><div><strong>还没有学习记录</strong><p>写下第一段学习事实，保存后会出现在这里。</p><button type="button" className="sf-button sf-button--tertiary sf-button--compact journal-empty-action" onClick={focusEditor}>开始写第一条</button></div></div>}
    </section>
  </div>;
}
