import { useState } from "react";
import { api } from "./api";
import type { PlanAdjustmentProposal } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

export default function PlanAdjustmentProposalWorkspace({ onNotice, onError }: Props) {
  const [reason, setReason] = useState("最近的安排需要重新理一理");
  const [proposal, setProposal] = useState<PlanAdjustmentProposal | null>(null);
  const [busy, setBusy] = useState(false);

  async function generate() {
    setBusy(true);
    try {
      const result = await api.proposePlanAdjustment(reason.trim() || undefined);
      setProposal(result);
      onNotice(result.changes.length ? "已经整理出一份调整建议，请看看是否合适。" : "看过最近的安排了，现在不需要调整任务。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "暂时无法整理调整建议");
    } finally { setBusy(false); }
  }

  async function execute() {
    if (!proposal || !proposal.requires_confirmation) return;
    setBusy(true);
    try {
      const result = await api.executePlanAdjustment(proposal.proposal_id, true);
      setProposal(result);
      if (result.executed) onNotice(`计划已重新安排 ${result.result?.applied ?? 0} 项，保留 ${result.result?.skipped_count ?? 0} 项手动修改。`);
      else onError(result.error ?? "这次没有修改计划");
    } catch (error) {
      onError(error instanceof Error ? error.message : "计划调整没有保存成功");
    } finally { setBusy(false); }
  }

  return <section className="plan-adjustment-panel sf-open-section">
    <div className="sf-surface-header">
      <div><h2 className="sf-section-title">帮我整理近期安排</h2><p className="sf-surface-description">看看逾期任务、本周安排和需要复习的内容，先给建议，不会直接修改计划。</p></div>
      <span className="sf-surface-metadata">{proposal ? `建议 ${proposal.proposal_id} · ${proposal.executed ? "已采用" : "等你确认"}` : "按需使用"}</span>
    </div>
    <div className="inline-form">
      <input aria-label="这次为什么要调整计划" value={reason} onChange={event => setReason(event.target.value)} placeholder="例如：这周课程作业变多，想把自学任务往后放…" />
      <button className="primary-button" disabled={busy} onClick={() => void generate()}>{busy ? "正在整理…" : "看看怎么调整"}</button>
    </div>
    {proposal && <div className="plan-adjustment-preview">
      <div className="adjustment-impact-grid">
        <div><strong>{proposal.impact.affected_tasks}</strong><span>受影响任务</span></div>
        <div><strong>{proposal.impact.date_shifted_tasks}</strong><span>重新排期</span></div>
        <div><strong>{proposal.impact.affected_reviews}</strong><span>需要复习</span></div>
        <div><strong>{proposal.impact.pending_logs}</strong><span>还没整理的记录</span></div>
      </div>
      <div className="plan-adjustment-detail sf-utility-surface">
        <strong>为什么这样调整</strong><p>{proposal.reason}</p>
        {proposal.changes.length ? <div className="adjustment-change-list">{proposal.changes.map(change => <div className="adjustment-change-row" key={change.task_id}>
          <div><strong>{change.title}</strong><small>{change.reason}</small></div>
          <div className="change-values"><span>{change.before.due_date ?? "无日期"} · P{change.before.priority}</span><b>→</b><span>{change.after.due_date ?? "无日期"} · P{change.after.priority}</span></div>
        </div>)}</div> : <p className="empty-inline">现在没有需要调整的任务，按原计划继续就好。</p>}
        {proposal.requires_confirmation && <div className="form-footer"><button className="ghost-button" disabled={busy} onClick={() => setProposal(null)}>先不调整</button><button className="primary-button" disabled={busy || !proposal.changes.length} onClick={() => void execute()}>采用这份安排</button></div>}
        {proposal.result && <p className="plan-adjustment-result sf-notice-surface sf-notice-surface--success">已重新安排 {proposal.result.applied ?? 0} 项；保留 {proposal.result.skipped_count ?? 0} 项手动修改，没有覆盖你后来改过的内容。</p>}
      </div>
    </div>}
  </section>;
}
