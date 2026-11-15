import { useState } from "react";
import { api } from "./api";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

export default function AgentChangeWorkspace({ onNotice, onError }: Props) {
  const [title, setTitle] = useState("");
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  async function previewChange() {
    if (!title.trim()) return;
    setBusy(true);
    try {
      const result = await api.agentChange("create_task", { title: title.trim() });
      if (!result.success) throw new Error(result.error ?? "暂时不能检查这项任务");
      setPreview(result.preview);
      onNotice("任务内容已经准备好，确认后才会加入清单。");
    } catch (error) { onError(error instanceof Error ? error.message : "暂时不能检查这项任务"); }
    finally { setBusy(false); }
  }

  async function confirmChange() {
    if (!preview) return;
    setBusy(true);
    try {
      const result = await api.agentChange("create_task", { title: String(preview.title) }, true);
      if (!result.success || !result.executed) throw new Error(result.error ?? "任务没有加入清单");
      setTitle(""); setPreview(null); onNotice("任务已经加入学习计划。");
    } catch (error) { onError(error instanceof Error ? error.message : "任务没有加入清单"); }
    finally { setBusy(false); }
  }

  return <aside className="coach-action-region sf-utility-surface"><div className="sf-surface-header"><div><h2 className="sf-surface-title">把聊到的事加入计划</h2><p className="sf-surface-description">想清楚后，再把下一步记进任务清单。</p></div><span className="sf-surface-metadata">由你决定</span></div><label className="field-label">准备做什么<input aria-label="准备加入计划的任务" value={title} onChange={event => setTitle(event.target.value)} placeholder="例如：完成两道窗口函数边界练习" /></label><button type="button" className="secondary-button coach-action-preview" disabled={busy || !title.trim()} onClick={() => void previewChange()}>{busy ? "正在检查…" : "先检查一下"}</button><small className="coach-action-privacy">这里不会自动修改计划，只有你确认后才会加入。</small>{preview && <div className="coach-action-confirm"><span>准备加入</span><strong>{String(preview.title ?? title)}</strong><p>任务会以“未开始”状态加入学习计划，你可以之后再安排时间。</p><div className="form-footer"><button type="button" className="ghost-button" onClick={() => setPreview(null)}>再想想</button><button type="button" className="primary-button" disabled={busy} onClick={() => void confirmChange()}>{busy ? "正在加入…" : "加入任务清单"}</button></div></div>}</aside>;
}
