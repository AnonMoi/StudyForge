import { FormEvent, useEffect, useState } from "react";
import { api } from "./api";
import MarkdownRenderer from "./MarkdownRenderer";

const taskOptions = [
  ["writing", "云端技术写作"],
  ["learning_plan", "云端学习规划"],
  ["teaching", "云端深度讲解"],
  ["knowledge_analysis", "云端知识分析"],
  ["daily_log", "本地学习记录结构化"],
] as const;

export default function ModelTaskWorkspace() {
  const [taskType, setTaskType] = useState("writing");
  const [prompt, setPrompt] = useState("");
  const [result, setResult] = useState("");
  const [provider, setProvider] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [confirmationNeeded, setConfirmationNeeded] = useState(false);
  const [budget, setBudget] = useState<import("./types").ModelBudget | null>(null);

  useEffect(() => {
    void api.modelBudget().then(setBudget).catch(() => undefined);
  }, []);

  async function submit(event: FormEvent, confirmed = false) {
    event.preventDefault();
    if (!prompt.trim()) return;
    setLoading(true); setError(""); setResult("");
    try {
      const response = await api.runTask(taskType, prompt.trim(), confirmed);
      if (!response.success) {
        setConfirmationNeeded(Boolean(response.requires_confirmation));
        setError(response.error ?? "任务执行失败");
        return;
      }
      setConfirmationNeeded(false);
      setProvider(`${response.provider} / ${response.model_name}`);
      setResult(response.response ?? JSON.stringify(response.data, null, 2));
      const next = await api.modelBudget().catch(() => null);
      if (next) setBudget(next);
    } catch (e) { setError(e instanceof Error ? e.message : "任务执行失败"); }
    finally { setLoading(false); }
  }

  const cloudTask = taskType === "writing" || taskType === "learning_plan" || taskType === "teaching" || taskType === "knowledge_analysis";
  const willConfirm = cloudTask && (budget?.calls_used ?? 0) >= (budget?.daily_call_limit ?? 0) - 3;
  const estimatedTokens = cloudTask ? Math.max(1, Math.round(prompt.trim().length / 3)) : 0;
  const estimatedFee = budget && cloudTask ? estimatedTokens / 1000 * budget.input_price_per_1k + 500 / 1000 * budget.output_price_per_1k : 0;

  return <section className="model-task-workspace sf-open-section">
    <div className="sf-surface-header"><h2 className="sf-section-title">模型任务分工</h2><span className="sf-surface-metadata">本地隐私优先 · 云端按需</span></div>
    <p>学习记录结构化默认交给本地模型；写作、规划、深度讲解和知识分析交给云端模型。高风险操作必须二次确认。</p>
    {budget && <div className="budget-strip"><span>今日云端调用 {budget.calls_used}/{budget.daily_call_limit}</span><span>消耗 {budget.tokens_used} tokens</span><span>费用 ¥{budget.cost_used.toFixed(4)} / ¥{budget.cost_limit.toFixed(2)}</span><span>费率 输入 ¥{budget.input_price_per_1k}/1k · 输出 ¥{budget.output_price_per_1k}/1k</span></div>}
    <form onSubmit={event => void submit(event)}>
      <label className="field-label">任务类型<select aria-label="模型任务类型" value={taskType} onChange={e => { setTaskType(e.target.value); setConfirmationNeeded(false); }}>{taskOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className="field-label">任务内容<textarea aria-label="模型任务内容" value={prompt} onChange={e => setPrompt(e.target.value)} rows={8} placeholder="输入需要处理的学习材料或任务…" /></label>
      <button className="primary-button" disabled={loading || !prompt.trim()}>{loading ? "处理中…" : "执行任务"}</button>
    </form>
    {willConfirm && !confirmationNeeded && <div className="sf-notice-surface sf-notice-surface--warning"><strong>云端预算提示</strong><p>剩余调用次数不足 3 次。云端任务在预算用尽后会被阻止，不会产生额外费用。</p></div>}
    {confirmationNeeded && <div className="sf-utility-surface"><strong>该任务需要确认</strong><p>这是可能影响代码或学习计划的高风险云端任务。发送前会脱敏常见密钥、邮箱和手机号。</p>{cloudTask && <p>预估约 {estimatedTokens} tokens，费用约 ¥{estimatedFee.toFixed(4)}；实际费用以供应商返回的 usage 为准。</p>}<button type="button" className="primary-button" disabled={loading} onClick={event => void submit(event, true)}>确认并执行</button></div>}
    {provider && <small>实际调用：{provider}</small>}
    {error && <div className="sf-notice-surface sf-notice-surface--error">{error}</div>}
    {result && <MarkdownRenderer content={result} className="task-result sf-utility-surface" />}
  </section>;
}
