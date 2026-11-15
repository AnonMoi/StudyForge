import { useEffect, useState } from "react";
import { api } from "./api";
import type { AuditLog, ModelBudget, ModelCall, RuntimeStatus } from "./types";

type Props = { onError: (message: string) => void };

export default function OperationsWorkspace({ onError }: Props) {
  const [budget, setBudget] = useState<ModelBudget | null>(null);
  const [calls, setCalls] = useState<ModelCall[]>([]);
  const [audits, setAudits] = useState<AuditLog[]>([]);
  const [bills, setBills] = useState<Array<Record<string, unknown>>>([]);
  const [syncs, setSyncs] = useState<Array<Record<string, unknown>>>([]);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [billText, setBillText] = useState("");
  const [billStatus, setBillStatus] = useState("");

  useEffect(() => {
    Promise.all([api.modelBudget(), api.modelCalls(), api.audits(), api.providerBills(), api.providerBillSyncs(), api.runtimeStatus()])
      .then(([nextBudget, nextCalls, nextAudits, nextBills, nextSyncs, nextRuntime]) => {
        setBudget(nextBudget);
        setCalls(nextCalls.calls);
        setAudits(nextAudits);
        setBills(nextBills.bills);
        setSyncs(nextSyncs.syncs);
        setRuntime(nextRuntime);
      })
      .catch((error) => onError(error instanceof Error ? error.message : "运行记录加载失败"));
  }, [onError]);

  return (
    <div className="operations-workspace">
      <section className="sf-open-section">
        <div className="sf-surface-header">
          <div><h2 className="sf-section-title">模型成本与调用</h2><p className="sf-surface-description">每日预算、调用次数和路由记录</p></div>
          <span className="sf-surface-metadata">{budget?.remaining_calls ?? "—"} 次剩余</span>
        </div>
        <dl className="operations-metrics">
          <div className="operations-metric"><dt>今日云端调用</dt><dd>{budget?.calls_used ?? 0}<small> / {budget?.daily_call_limit ?? 0}</small></dd></div>
          <div className="operations-metric"><dt>估算费用</dt><dd>{(budget?.cost_used ?? 0).toFixed(2)}<small> / {budget?.cost_limit ?? 0}</small></dd></div>
          <div className="operations-metric"><dt>剩余调用</dt><dd>{budget?.remaining_calls ?? 0}<small>次</small></dd></div>
          <div className="operations-metric"><dt>剩余预算</dt><dd>{(budget?.remaining_cost ?? 0).toFixed(2)}<small>单位</small></dd></div>
        </dl>
      </section>

      <section className="sf-open-section">
        <div className="sf-surface-header"><div><h2 className="sf-section-title">提醒服务</h2><p className="sf-surface-description">这里可以查看学习提醒是否正常工作。</p></div><span className={runtime?.scheduler.thread_alive ? "status-good" : "status-warn"}>{runtime?.scheduler.thread_alive ? "运行中" : "未运行"}</span></div>
        {runtime ? <div className="runtime-status-grid"><span>线程：{runtime.scheduler.thread_alive ? "存活" : "已停止"}</span><span>周期：{runtime.scheduler.interval_seconds} 秒</span><span>已执行：{runtime.scheduler.ticks} 次</span><span>最近执行：{runtime.scheduler.last_tick_at ? new Date(runtime.scheduler.last_tick_at).toLocaleString() : "尚未执行"}</span></div> : <div className="empty"><p>后台状态暂不可用。</p></div>}
        {runtime?.scheduler.last_error && <p className="error-text">最近一次调度错误：{runtime.scheduler.last_error}</p>}
      </section>

      <section className="sf-open-section">
        <div className="sf-surface-header"><h2 className="sf-section-title">调用历史</h2><span className="sf-surface-metadata">{calls.length} 条</span></div>
        {calls.length ? <div className="relation-list">{calls.map((call) => {
          const isOpen = expanded === call.id;
          return <div className="task-row operation-call" key={call.id}>
            <button type="button" className="operation-call-toggle" aria-expanded={isOpen} onClick={() => setExpanded(isOpen ? null : call.id)}>
              <span><strong>{call.task_type} · {call.provider}</strong><small>{call.model_name} · 风险 {call.risk_level} · {call.success ? "成功" : "失败"} · {call.created_at}</small></span>
              <span className="priority">{call.estimated_cost ?? 0}</span>
            </button>
            {isOpen && <div className="operation-call-details">
              <span>输入/输出：{call.input_length ?? "—"} / {call.output_length ?? "—"} 字符</span>
              <span>Token：{call.input_tokens ?? "—"} / {call.output_tokens ?? "—"} / {call.total_tokens ?? "—"}{call.token_source ? `（${call.token_source}）` : ""}</span>
              <span>耗时：{call.duration_ms ?? "—"} ms；置信度：{call.confidence ?? "—"}</span>
              <span>路由原因：{call.route_reason ?? "未记录"}{call.upgraded ? "；已升级" : ""}</span>
              {(call.failure_reason || call.error) && <span className="error-text">失败原因：{call.failure_reason ?? call.error}</span>}
            </div>}
          </div>;
        })}</div> : <div className="empty"><p>还没有模型调用记录。</p></div>}
      </section>

      <section className="sf-open-section">
        <div className="sf-surface-header"><div><h2 className="sf-section-title">供应商账单对账</h2><p className="sf-surface-description">自动同步仅使用本地配置的供应商接口；不会在前端展示密钥。仍可导入 JSON 作为兜底。</p></div><span className="sf-surface-metadata">{bills.length} 份</span></div>
        <div className="form-footer"><button type="button" className="primary-button" onClick={() => { setBillStatus("正在同步账单…"); void api.syncProviderBill().then((result) => { setSyncs((current) => [result, ...current]); setBillStatus(result.status === "succeeded" ? "账单已同步并完成本地对账。" : String(result.error ?? "账单同步失败。")); return api.providerBills(); }).then((nextBills) => setBills(nextBills.bills)).catch((error) => setBillStatus(error instanceof Error ? error.message : "账单同步失败")); }}>同步最近账单</button>{billStatus && <small>{billStatus}</small>}</div>
        <textarea aria-label="供应商账单 JSON" value={billText} onChange={(event) => setBillText(event.target.value)} placeholder='{"provider":"zhiapi","source_name":"2026-08账单","lines":[{"call_id":1,"model_name":"gpt-5.6-luna","amount":0.12}]}' rows={4} />
        <div className="form-footer"><button type="button" className="primary-button" onClick={() => { try { const payload = JSON.parse(billText) as { provider: string; lines: Array<Record<string, unknown>> }; void api.importProviderBill(payload).then((result) => { setBills((current) => [result, ...current]); setBillStatus("账单已导入并完成本地对账。"); }).catch((error) => setBillStatus(error instanceof Error ? error.message : "账单导入失败")); } catch { setBillStatus("账单 JSON 格式无效。"); } }}>导入并对账</button>{billStatus && <small>{billStatus}</small>}</div>
        {bills.length > 0 && <div className="relation-list">{bills.map((bill, index) => <div className="task-row" key={String(bill.id ?? index)}><div><strong>{String(bill.provider)} · {String(bill.source_name)}</strong><small>总额 ¥{Number(bill.total_amount ?? 0).toFixed(4)} · 已匹配 ¥{Number(bill.matched_amount ?? 0).toFixed(4)} · 未匹配 ¥{Number(bill.unmatched_amount ?? 0).toFixed(4)}</small></div></div>)}</div>}
        {syncs.length > 0 && <div className="relation-list">{syncs.slice(0, 5).map((sync, index) => <div className="task-row" key={String(sync.id ?? index)}><div><strong>自动同步 · {String(sync.status)}</strong><small>{String(sync.period_start)} 至 {String(sync.period_end)} · 尝试 {String(sync.attempts)}/{String(sync.max_attempts)}{sync.error ? ` · ${String(sync.error)}` : ""}</small></div></div>)}</div>}
      </section>

      <section className="sf-open-section">
        <div className="sf-surface-header"><h2 className="sf-section-title">变更审计</h2><span className="sf-surface-metadata">{audits.length} 条</span></div>
        {audits.length ? <div className="relation-list audit-list" aria-label="变更审计记录">{audits.map((item) => <div className="task-row" key={item.id}><div><strong>{item.entity_type} · {item.action}</strong><small>{item.created_at}</small></div></div>)}</div> : <div className="empty"><p>还没有结构化变更记录。</p></div>}
      </section>
    </div>
  );
}
