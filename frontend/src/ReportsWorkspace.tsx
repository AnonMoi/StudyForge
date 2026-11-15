import { useEffect, useState } from "react";
import { api, downloadJson, getApiErrorMessage } from "./api";
import type { LearningReport, ReportComparison, ReportFeedback, ReportFeedbackEffects, ReportProposal, ReportType } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

const reportTypes: Array<{ type: ReportType; label: string; action: string; description: string }> = [
  { type: "daily", label: "今天", action: "整理今天", description: "看看今天花了多少时间，做完了什么，还有什么没想通。" },
  { type: "weekly", label: "这一周", action: "整理这周", description: "把这一周的任务、学习记录和复习放在一起看。" },
  { type: "stage", label: "当前阶段", action: "整理阶段", description: "回到当前目标，看看已经留下哪些学习依据。" },
  { type: "bottleneck", label: "总是卡住的地方", action: "找找卡点", description: "从延期、复习和未解决问题里找出反复出现的阻碍。" },
];

const feedbackText: Record<string, string> = {
  helpful: "这份回看有帮助",
  not_helpful: "有些地方不贴合",
  accepted: "这些建议值得安排",
  rejected: "这次先不安排",
  adjusted: "调整后再安排",
};

const proposalStatusText: Record<string, string> = {
  pending: "等你决定",
  executed: "已经加入计划",
  partially_executed: "部分加入计划",
  conflict: "有冲突，暂未改动",
  rejected: "已经放下",
};

function reportTypeLabel(type: ReportType) {
  return reportTypes.find(item => item.type === type)?.label ?? "这段时间";
}

function readableDate(value: string) {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric" }).format(date);
}

function periodText(report: LearningReport) {
  if (report.period_start === report.period_end) return readableDate(report.period_start);
  return `${readableDate(report.period_start)}至${readableDate(report.period_end)}`;
}

function itemText(value: unknown, keys: string[]) {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (!value || typeof value !== "object") return "";
  const record = value as Record<string, unknown>;
  for (const key of keys) {
    const candidate = record[key];
    if (typeof candidate === "string" || typeof candidate === "number") return String(candidate);
  }
  return "";
}

function sourceText(source: unknown) {
  const value = String(source ?? "");
  if (value === "statistics") return "来自已保存的任务、记录与复习";
  if (value.includes("task")) return "来自任务记录";
  if (value.includes("review")) return "来自复习记录";
  if (value.includes("log")) return "来自学习记录";
  return "来自本机保存的学习记录";
}

function generationText(report: LearningReport) {
  if (report.generation_mode === "model") return "这份回看根据本机保存记录整理，并使用了你在设置中允许的文字整理功能。";
  if (report.generation_mode === "deterministic_fallback" || report.fallback_used) return "这次文字整理没有完成，页面已改用本机保存记录直接汇总；已有事实没有丢失。";
  return "这份回看由本机已保存的任务、学习记录、复习和教学结果直接汇总。";
}

function proposalChangeText(change: Record<string, unknown>) {
  return String(change.title ?? change.action ?? change.reason ?? "一项学习安排");
}

export default function ReportsWorkspace({ onNotice, onError }: Props) {
  const [reports, setReports] = useState<LearningReport[]>([]);
  const [selected, setSelected] = useState<LearningReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<ReportType | "">("");
  const [forceNewVersion, setForceNewVersion] = useState(false);
  const [feedback, setFeedback] = useState<ReportFeedback[]>([]);
  const [feedbackBusy, setFeedbackBusy] = useState<string>("");
  const [proposals, setProposals] = useState<ReportProposal[]>([]);
  const [proposalBusy, setProposalBusy] = useState<number | null>(null);
  const [feedbackEffects, setFeedbackEffects] = useState<ReportFeedbackEffects | null>(null);
  const [comparisonBaseId, setComparisonBaseId] = useState<number | null>(null);
  const [comparison, setComparison] = useState<ReportComparison | null>(null);
  const [comparisonBusy, setComparisonBusy] = useState(false);

  async function load() {
    setLoading(true);
    try { setReports(await api.reports()); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setLoading(false); }
  }

  useEffect(() => { void load(); }, []);

  useEffect(() => {
    if (!selected) return;
    setFeedback([]);
    setProposals([]);
    setFeedbackEffects(null);
    setComparisonBaseId(null);
    setComparison(null);
    void Promise.all([api.reportFeedback(selected.id), api.reportProposals(selected.id), api.reportFeedbackEffects(selected.id)])
      .then(([nextFeedback, nextProposals, nextEffects]) => {
        setFeedback(nextFeedback);
        setProposals(nextProposals);
        setFeedbackEffects(nextEffects);
      })
      .catch(error => onError(getApiErrorMessage(error)));
  }, [selected?.id]);

  async function generate(type: ReportType) {
    setBusy(type);
    try {
      const report = await api.generateReport(type, { force_new_version: forceNewVersion });
      setSelected(report);
      await load();
      onNotice(`${reportTypeLabel(type)}的学习回看已经整理好。`);
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(""); }
  }

  async function openReport(reportId: number) {
    try { setSelected(await api.report(reportId)); }
    catch (error) { onError(getApiErrorMessage(error)); }
  }

  async function submitFeedback(feedbackType: "helpful" | "not_helpful" | "accepted" | "rejected") {
    if (!selected) return;
    setFeedbackBusy(feedbackType);
    try {
      const item = await api.createReportFeedback(selected.id, { feedback_type: feedbackType });
      setFeedback(current => [item, ...current]);
      setProposals(await api.reportProposals(selected.id));
      setFeedbackEffects(await api.reportFeedbackEffects(selected.id));
      onNotice(feedbackType === "accepted" ? "已经准备好计划草稿，确认前不会改动计划。" : "你的看法已经记下。" );
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setFeedbackBusy(""); }
  }

  async function executeProposal(proposal: ReportProposal) {
    setProposalBusy(proposal.proposal_id);
    try {
      const result = await api.executePlanProposal(proposal.proposal_id, true);
      setProposals(current => current.map(item => item.proposal_id === result.proposal_id ? result : item));
      if (selected) setFeedbackEffects(await api.reportFeedbackEffects(selected.id));
      onNotice(result.executed ? "这些安排已经加入计划。" : "计划没有改动，请先查看冲突说明。" );
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setProposalBusy(null); }
  }

  async function compareSelected() {
    if (!selected || !comparisonBaseId) return;
    setComparisonBusy(true);
    try { setComparison(await api.compareReports(comparisonBaseId, selected.id)); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setComparisonBusy(false); }
  }

  async function exportReport(format: "json" | "txt" | "md" | "html") {
    if (!selected) return;
    try {
      if (format === "json") {
        downloadJson(`learning-report-${selected.id}.json`, await api.reportExport(selected.id, format));
      } else {
        const blob = await api.reportExportBlob(selected.id, format);
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `learning-report-${selected.id}.${format}`;
        anchor.click();
        URL.revokeObjectURL(url);
      }
      onNotice("这份学习回看已经下载。" );
    } catch (error) { onError(getApiErrorMessage(error)); }
  }

  const comparableReports = selected ? reports.filter(item => item.id !== selected.id && item.report_type === selected.report_type && item.stage_id === selected.stage_id) : [];
  const executedCount = feedbackEffects?.summary.proposal_status.executed ?? 0;
  const pendingCount = feedbackEffects?.summary.proposal_status.pending ?? 0;

  return <div className="reports-workspace">
    <header className="report-reader-intro sf-open-section">
      <div><h2>把这段时间的学习，整理成一页</h2><p>这里只使用已经保存的任务、学习记录、复习和教学结果。先看事实，再决定下一步。</p></div>
      <span>{reports.length ? `以前留下 ${reports.length} 份回看` : "还没有保存过学习回看"}</span>
    </header>

    <section className="report-create-sheet sf-utility-surface" aria-labelledby="report-period-title">
      <div className="report-create-heading sf-surface-header"><div><h2 className="sf-section-title" id="report-period-title">这次想回看哪一段？</h2><p className="sf-surface-description">同一段时间已经整理过时，会直接打开原来的内容。</p></div></div>
      <div className="report-period-list">
        {reportTypes.map(item => <button className="report-period-choice" type="button" key={item.type} disabled={Boolean(busy)} aria-label={item.action} onClick={() => void generate(item.type)}><strong>{item.label}</strong><span>{item.description}</span><small>{busy === item.type ? "正在整理…" : item.action}</small></button>)}
      </div>
      <label className="report-new-version"><input aria-label="重新留一份这次回看" type="checkbox" checked={forceNewVersion} onChange={event => setForceNewVersion(event.target.checked)} /><span><strong>重新留一份这次回看</strong><small>只在你想保留新的版本时勾选；不会覆盖以前的内容。</small></span></label>
    </section>

    {selected ? <article className="report-reading-paper sf-writing-surface">
      <header className="report-paper-header sf-surface-header">
        <div><p>{reportTypeLabel(selected.report_type)} · {periodText(selected)}{selected.version > 1 ? ` · 第 ${selected.version} 版` : ""}</p><h2 className="sf-surface-title sf-surface-title--prominent">{selected.title}</h2><div className="report-summary">{selected.summary}</div></div>
        <details className="report-download"><summary className="ghost-button">下载这页</summary><div>{([ ["md", "Markdown"], ["txt", "纯文字"], ["html", "网页"], ["json", "原始数据"] ] as const).map(([format, label]) => <button type="button" className="ghost-button" key={format} onClick={() => void exportReport(format)}>{label}</button>)}</div></details>
      </header>

      <section className="report-paper-section sf-open-section" aria-labelledby="report-evidence-title">
        <div className="report-section-heading sf-surface-header"><div><h3 className="sf-section-title" id="report-evidence-title">这段时间留下了什么</h3><p className="sf-surface-description">这些数字都来自已经保存的学习记录。</p></div></div>
        {selected.evidence.length ? <dl className="report-evidence-ledger">{selected.evidence.map((item, index) => <div key={`${String(item.fact ?? "fact")}-${index}`}><dt>{String(item.fact ?? "学习记录")}</dt><dd>{String(item.value ?? "—")}</dd><small>{sourceText(item.source_type)}</small></div>)}</dl> : <p className="report-reading-empty">这段时间还没有留下能够汇总的记录。</p>}
      </section>

      <section className="report-paper-section sf-open-section" aria-labelledby="report-achievement-title">
        <div className="report-section-heading sf-surface-header"><div><h3 className="sf-section-title" id="report-achievement-title">已经做成的事</h3><p className="sf-surface-description">只列已经有记录支撑的结果。</p></div></div>
        <ul className="report-reading-list">{selected.achievements.length ? selected.achievements.map((item, index) => <li key={index}>{itemText(item, ["title", "name", "achievement"]) || "一项已经完成的学习内容"}</li>) : <li>这段时间还没有记录到明确成果。</li>}</ul>
      </section>

      <section className="report-paper-section sf-open-section" aria-labelledby="report-stuck-title">
        <div className="report-section-heading sf-surface-header"><div><h3 className="sf-section-title" id="report-stuck-title">还卡在哪里</h3><p className="sf-surface-description">这里是从未解决问题和反复出现的情况中整理出的提醒，不是对能力的判定。</p></div></div>
        {selected.weak_points.length ? <div className="report-observation-list">{selected.weak_points.map((item, index) => <div key={index}><strong>{itemText(item, ["point", "title", "name"]) || "值得再看一眼"}</strong><p>{itemText(item, ["reason", "description"])}</p></div>)}</div> : <p className="report-reading-empty">现有记录里没有出现反复卡住的地方。</p>}
      </section>

      {selected.unfinished_items.length > 0 && <section className="report-paper-section sf-open-section" aria-labelledby="report-unfinished-title"><div className="report-section-heading sf-surface-header"><div><h3 className="sf-section-title" id="report-unfinished-title">还没做完的事</h3><p className="sf-surface-description">保留原来的任务名称，方便回到计划里继续。</p></div></div><ul className="report-reading-list">{selected.unfinished_items.map((item, index) => <li key={index}>{itemText(item, ["title", "name", "action"]) || "一项尚未完成的任务"}</li>)}</ul></section>}

      <section className="report-paper-section sf-open-section" aria-labelledby="report-next-title">
        <div className="report-section-heading sf-surface-header"><div><h3 className="sf-section-title" id="report-next-title">接下来可以做什么</h3><p className="sf-surface-description">先当作备选；只有你明确确认，相关安排才会进入计划。</p></div></div>
        {selected.recommendations.length ? <div className="report-next-list">{selected.recommendations.map((item, index) => <div key={index}><strong>{itemText(item, ["action", "title", "name"]) || "继续保留学习依据"}</strong><p>{itemText(item, ["reason", "description"])}</p></div>)}</div> : <p className="report-reading-empty">这次没有需要额外安排的建议。</p>}
      </section>

      <section className="report-paper-section report-feedback-section sf-open-section" aria-labelledby="report-feedback-title">
        <div className="report-section-heading sf-surface-header"><div><h3 className="sf-section-title" id="report-feedback-title">这份回看符合实际吗？</h3><p className="sf-surface-description">你的选择会被记下；只有“值得安排”会准备一份计划草稿。</p></div></div>
        <div><div className="report-feedback-actions">{(["helpful", "not_helpful", "accepted", "rejected"] as const).map(type => <button type="button" className="ghost-button" key={type} disabled={Boolean(feedbackBusy)} onClick={() => void submitFeedback(type)}>{feedbackBusy === type ? "正在记录…" : feedbackText[type]}</button>)}</div><p className="report-feedback-note">{feedback.length ? `最近一次选择：${feedbackText[feedback[0].feedback_type] ?? "已经留下看法"}。` : "还没有留下看法。"}{executedCount ? ` 已有 ${executedCount} 份安排加入计划。` : ""}{pendingCount ? ` 还有 ${pendingCount} 份等你决定。` : ""}</p></div>
      </section>

      {proposals.length > 0 && <section className="report-paper-section sf-open-section" aria-labelledby="report-plan-title"><div className="report-section-heading sf-surface-header"><div><h3 className="sf-section-title" id="report-plan-title">加入计划前，再看一眼</h3><p className="sf-surface-description">这里列出的内容还没有写入计划。</p></div></div><div className="report-proposal-list">{proposals.map(proposal => <article className="report-proposal sf-utility-surface" key={proposal.proposal_id}><div><strong>{proposalStatusText[proposal.status] ?? "计划草稿"}</strong><p>{proposal.changes.length ? proposal.changes.map(proposalChangeText).join("；") : "这份草稿没有可以写入的安排。"}</p>{proposal.error && <small className="report-proposal-error sf-notice-surface sf-notice-surface--error">{proposal.error}</small>}{proposal.executed && <small>已经按你的确认更新 {proposal.changes.length} 项安排。</small>}</div>{proposal.requires_confirmation && <button type="button" className="primary-button" disabled={proposalBusy === proposal.proposal_id} onClick={() => void executeProposal(proposal)}>{proposalBusy === proposal.proposal_id ? "正在加入…" : "加入计划"}</button>}</article>)}</div></section>}

      <details className="report-reading-tools sf-utility-surface">
        <summary>以前的版本与整理说明</summary>
        <div className="report-tools-content"><p>{generationText(selected)}这份内容不会自动改动任务或能力记录。</p>{comparableReports.length ? <div className="report-compare-controls"><label>选择另一份同类回看<select aria-label="选择以前的学习回看进行比较" value={comparisonBaseId ?? ""} onChange={event => setComparisonBaseId(event.target.value ? Number(event.target.value) : null)}><option value="">请选择</option>{comparableReports.map(item => <option key={item.id} value={item.id}>{periodText(item)} · 第 {item.version} 版</option>)}</select></label><button type="button" className="ghost-button" disabled={!comparisonBaseId || comparisonBusy} onClick={() => void compareSelected()}>{comparisonBusy ? "正在比较…" : "看看变化"}</button></div> : <p>还没有另一份同类回看可以比较。</p>}{comparison && <p className="report-comparison">和以前相比：新增 {comparison.changes.evidence.added.length} 条学习事实，调整 {comparison.changes.evidence.changed.length} 条；新增 {comparison.changes.weak_points.added.length} 个待留意处，减少 {comparison.changes.weak_points.removed.length} 个。</p>}</div>
      </details>
    </article> : <section className="report-reading-placeholder sf-open-section"><h2 className="sf-section-title">先选择一段时间</h2><p className="sf-surface-description">整理完成后，学习事实、已完成内容、卡点和下一步会按一页连续展开。</p></section>}

    <details className="report-archive sf-open-section" open={reports.length > 0}>
      <summary><span><strong>以前的学习回看</strong><small>重新打开时只查看当时保存的内容，不会跟着后来记录自动变化。</small></span><em>{reports.length} 份</em></summary>
      {loading ? <p className="report-archive-state" role="status">正在读取以前的回看…</p> : reports.length ? <div className="report-history">{reports.map(report => <button type="button" className={`report-history-row ${selected?.id === report.id ? "active" : ""}`} key={report.id} onClick={() => void openReport(report.id)}><span><strong>{report.title}</strong><small>{reportTypeLabel(report.report_type)} · {periodText(report)}</small></span><em>{report.version > 1 ? `第 ${report.version} 版` : "打开"}</em></button>)}</div> : <p className="report-archive-state">整理第一份学习回看后，会在这里留下记录。</p>}
    </details>
  </div>;
}
