import { useEffect, useState } from "react";
import { api, getApiErrorMessage } from "./api";
import type { CloudSyncStatus, ModelBudget, ModelHealth, PublicSettings, SyncBundle, SyncPreview } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

export default function SettingsWorkspace({ onNotice, onError }: Props) {
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [health, setHealth] = useState<ModelHealth | null>(null);
  const [budget, setBudget] = useState<ModelBudget | null>(null);
  const [cloudSync, setCloudSync] = useState<CloudSyncStatus | null>(null);
  const [syncPassphrase, setSyncPassphrase] = useState("");
  const [syncFile, setSyncFile] = useState<File | null>(null);
  const [localSyncBundle, setLocalSyncBundle] = useState<SyncBundle | null>(null);
  const [localSyncPreview, setLocalSyncPreview] = useState<SyncPreview | null>(null);
  const [cloudSyncPreview, setCloudSyncPreview] = useState<Record<string, unknown> | null>(null);
  const [cloudSyncAction, setCloudSyncAction] = useState<"push" | "pull" | null>(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ local_model_name: "", cloud_model_name: "", cloud_model_enabled: false, model_routing_mode: "local_first", daily_cloud_call_limit: 20, daily_cost_limit: 2, max_tokens_per_request: 12000, local_confidence_threshold: 0.65, cloud_input_price_per_1k: 0.02, cloud_output_price_per_1k: 0.06, report_model_enhancement_enabled: false, native_notifications_enabled: false });

  async function load() {
    try {
      const [nextSettings, nextHealth, nextBudget] = await Promise.all([api.settings(), api.modelHealth(), api.modelBudget()]);
      setSettings(nextSettings); setHealth(nextHealth); setBudget(nextBudget);
      try { setCloudSync(await api.cloudSyncStatus()); }
      catch { setCloudSync({ configured: false, provider: "webdav", path: "", warning: "云同步状态暂不可用；本地设置仍可使用。" }); }
      setForm({ local_model_name: nextSettings.local_model, cloud_model_name: nextSettings.cloud_model, cloud_model_enabled: nextSettings.cloud_enabled, model_routing_mode: nextSettings.model_routing_mode ?? "local_first", daily_cloud_call_limit: nextSettings.daily_cloud_call_limit, daily_cost_limit: nextSettings.daily_cost_limit ?? nextBudget.cost_limit, max_tokens_per_request: nextSettings.max_tokens_per_request ?? 12000, local_confidence_threshold: nextSettings.local_confidence_threshold ?? 0.65, cloud_input_price_per_1k: nextSettings.cloud_input_price_per_1k, cloud_output_price_per_1k: nextSettings.cloud_output_price_per_1k, report_model_enhancement_enabled: nextSettings.report_model_enhancement_enabled ?? false, native_notifications_enabled: nextSettings.native_notifications_enabled ?? false });
    } catch (error) { onError(getApiErrorMessage(error)); }
  }
  useEffect(() => { void load(); }, []);
  async function save() {
    setBusy(true);
    try { const result = await api.updateSettings(form); setSettings(result); setBudget(await api.modelBudget()); onNotice(result.warning ?? "模型与费用设置已保存。"); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }
  async function testNativeNotifications() {
    try {
      const preview = await api.testNativeNotifications(false);
      if (!preview.requires_confirmation || !window.confirm("发送一条 Windows 原生通知测试？")) return;
      const result = await api.testNativeNotifications(true);
      onNotice(result.sent ? "Windows 原生通知测试已发送。" : "Windows 原生通知发送失败。");
    } catch (error) { onError(getApiErrorMessage(error)); }
  }
  function requireSyncPassphrase() {
    if (syncPassphrase.trim().length < 12) {
      onError("同步包口令至少需要 12 个字符。");
      return false;
    }
    return true;
  }
  function downloadSyncBundle(bundle: SyncBundle) {
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `learning-workstation-sync-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  async function exportSyncBundle() {
    if (!requireSyncPassphrase()) return;
    setSyncBusy(true);
    try {
      const result = await api.syncExport(syncPassphrase);
      downloadSyncBundle(result.bundle);
      onNotice("加密同步包已下载；包内不包含明文学习数据。");
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setSyncBusy(false); }
  }
  async function previewImportedSync() {
    if (!requireSyncPassphrase() || !syncFile) return;
    setSyncBusy(true);
    try {
      const parsed = JSON.parse(await syncFile.text()) as SyncBundle;
      if (parsed.format !== "learning-workstation-sync-v1") throw new Error("文件不是受支持的加密同步包。");
      setLocalSyncBundle(parsed);
      setLocalSyncPreview(await api.syncPreview(parsed, syncPassphrase));
    } catch (error) { onError(error instanceof Error ? error.message : getApiErrorMessage(error)); }
    finally { setSyncBusy(false); }
  }
  async function applyImportedSync() {
    if (!localSyncBundle || !requireSyncPassphrase()) return;
    setSyncBusy(true);
    try {
      await api.syncApply(localSyncBundle, syncPassphrase, true);
      setLocalSyncBundle(null); setLocalSyncPreview(null); setSyncFile(null); setSyncPassphrase("");
      onNotice("本地同步包已按追加策略恢复；已有记录不会被覆盖。");
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setSyncBusy(false); }
  }
  async function previewCloudSync(action: "push" | "pull") {
    if (!requireSyncPassphrase() || !cloudSync?.configured) return;
    setSyncBusy(true);
    try {
      setCloudSyncAction(action);
      setCloudSyncPreview(action === "push" ? await api.cloudSyncPush(syncPassphrase, false) : await api.cloudSyncPull(syncPassphrase, false));
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setSyncBusy(false); }
  }
  async function confirmCloudSync(action: "push" | "pull") {
    if (!requireSyncPassphrase() || !cloudSync?.configured) return;
    setSyncBusy(true);
    try {
      const result = action === "push" ? await api.cloudSyncPush(syncPassphrase, true) : await api.cloudSyncPull(syncPassphrase, true);
      setCloudSyncPreview(null); setCloudSyncAction(null); setSyncPassphrase("");
      onNotice(action === "push" ? "加密同步包已推送到 WebDAV。" : `WebDAV 同步包已恢复 ${JSON.stringify(result.restored_counts ?? {})}。`);
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setSyncBusy(false); }
  }
  const update = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm(current => ({ ...current, [key]: value }));
  const localState = health?.local.available ? "在线" : "离线";
  const cloudState = health?.cloud.enabled ? (health.cloud.available ? "在线" : health.cloud.configured === false ? "未配置" : "不可用") : "已关闭";
  const routingDescription = form.model_routing_mode === "local_only"
    ? "所有模型任务只在本地执行，不会升级到云端。"
    : form.model_routing_mode === "cloud_confirmed"
      ? "本地模型先执行；需要升级到云端时，必须先得到你的确认。"
      : "本地模型先执行；只有本地失败或超时后，才会按权限与预算尝试云端。";

  return <div className="settings-workspace">
    <section className="setup-section model-settings-section sf-working-surface">
      <div className="setup-section-heading sf-surface-header"><div><h2 className="sf-section-title">模型与路由</h2><p className="sf-surface-description">确定任务先在哪里运行、何时允许云端接手。环境变量中的密钥不会被写回页面。</p></div><span className="sf-surface-metadata">推荐 · 可使用默认值</span></div>

      <dl className="model-status-summary" aria-label="模型与预算状态">
        <div><dt>本地模型</dt><dd><span className={`sf-status-text ${health?.local.available ? "available" : "unavailable"}`}><i aria-hidden="true" />{localState}</span><small>{health?.local.model ?? settings?.local_model ?? "读取中"}</small></dd></div>
        <div><dt>云端模型</dt><dd><span className={`sf-status-text ${health?.cloud.available ? "available" : "unavailable"}`}><i aria-hidden="true" />{cloudState}</span><small>{health?.cloud.model ?? settings?.cloud_model ?? "读取中"}</small></dd></div>
        <div><dt>今日云端使用</dt><dd>{budget?.calls_used ?? 0} / {budget?.daily_call_limit ?? 0} 次<small>费用 ¥{(budget?.cost_used ?? 0).toFixed(4)} / ¥{(budget?.cost_limit ?? 0).toFixed(2)}</small></dd></div>
      </dl>

      <div className="model-routing-grid">
        <label>本地模型名称<input className="sf-field" value={form.local_model_name} onChange={event => update("local_model_name", event.target.value)} /></label>
        <label>路由方式<select className="sf-field" value={form.model_routing_mode} onChange={event => update("model_routing_mode", event.target.value)}><option value="local_only">仅使用本地模型</option><option value="local_first">本地优先，失败或超时后升级</option><option value="cloud_confirmed">云端升级前必须确认</option></select></label>
        <p className="routing-explanation">{routingDescription}</p>
        <label>云端模型名称<input className="sf-field" value={form.cloud_model_name} onChange={event => update("cloud_model_name", event.target.value)} /></label>
        <label className="setup-toggle-row"><input type="checkbox" checked={form.cloud_model_enabled} onChange={event => update("cloud_model_enabled", event.target.checked)} /><span><strong>允许云端模型参与路由</strong><small>仍受确认策略、调用次数与费用上限约束。</small></span></label>
      </div>

    </section>

    <section id="usage-limits" className="setup-section usage-limits-section sf-open-section">
      <div className="setup-section-heading sf-surface-header"><div><h2 className="sf-section-title">使用限制</h2><p className="sf-surface-description">云端达到任一上限后自动停止，工作站继续使用本地能力。</p></div><span className="sf-surface-metadata">推荐 · 费用边界</span></div>
      <div className="usage-limits">
        <label>每日云端调用上限<input className="sf-field" type="number" min="0" value={form.daily_cloud_call_limit} onChange={event => update("daily_cloud_call_limit", Number(event.target.value))} /></label>
        <label>每日费用上限（元）<input className="sf-field" type="number" min="0" step="0.01" value={form.daily_cost_limit} onChange={event => update("daily_cost_limit", Number(event.target.value))} /></label>
      </div>
    </section>

    <section id="advanced-settings" className="setup-section advanced-settings-section sf-open-section">
      <div className="setup-section-heading sf-surface-header"><div><h2 className="sf-section-title">高级设置</h2><p className="sf-surface-description">按需调整模型阈值、计价、报告增强与系统通知。</p></div><span className="sf-surface-metadata">高级 · 保持默认即可</span></div>
      <details className="setup-disclosure advanced-settings">
        <summary><span>打开高级模型与系统偏好</span><small>Token、阈值、计价、报告增强与原生通知</small></summary>
        <div className="advanced-settings-grid">
          <label>单次最大 Token<input className="sf-field" type="number" min="128" value={form.max_tokens_per_request} onChange={event => update("max_tokens_per_request", Number(event.target.value))} /></label>
          <label>本地置信度阈值<input className="sf-field" type="number" min="0" max="1" step="0.05" value={form.local_confidence_threshold} onChange={event => update("local_confidence_threshold", Number(event.target.value))} /></label>
          <label>云端输入价格 / 1K<input className="sf-field" type="number" min="0" step="0.001" value={form.cloud_input_price_per_1k} onChange={event => update("cloud_input_price_per_1k", Number(event.target.value))} /></label>
          <label>云端输出价格 / 1K<input className="sf-field" type="number" min="0" step="0.001" value={form.cloud_output_price_per_1k} onChange={event => update("cloud_output_price_per_1k", Number(event.target.value))} /></label>
          <label className="setup-toggle-row"><input type="checkbox" checked={form.report_model_enhancement_enabled} onChange={event => update("report_model_enhancement_enabled", event.target.checked)} /><span><strong>允许报告使用模型增强</strong><small>关闭时使用确定性证据汇总。</small></span></label>
          <label className="setup-toggle-row"><input type="checkbox" checked={form.native_notifications_enabled} disabled={!settings?.native_notifications_available} onChange={event => update("native_notifications_enabled", event.target.checked)} /><span><strong>启用 Windows 原生通知</strong><small>{settings?.native_notifications_available ? "独立于浏览器显示学习提醒，默认关闭。" : "当前系统不可用或未检测到 PowerShell。"}</small></span></label>
        </div>
        <button type="button" className="text-button" disabled={busy || !settings?.native_notifications_available || !form.native_notifications_enabled} onClick={() => void testNativeNotifications()}>发送测试通知</button>
      </details>

      <div className="setup-action-row"><span>{settings?.cloud_key_masked ?? (settings?.cloud_key_configured ? "云端密钥已配置" : "云端密钥未配置")}</span><button className="primary-button" onClick={() => void save()} disabled={busy || !form.local_model_name.trim() || !form.cloud_model_name.trim()}>{busy ? "保存中…" : "保存模型设置"}</button></div>
    </section>

    <section id="encrypted-sync" className="setup-section sync-settings-panel sf-open-section">
      <div className="setup-section-heading sf-surface-header"><div><h2 className="sf-section-title">加密同步</h2><p className="sf-surface-description">口令只保留在当前页面。导入和远端拉取都先预览，确认后仅追加恢复，不覆盖已有记录。</p></div><span className="sf-surface-metadata">高级 · 按需配置</span></div>
      <details className="setup-disclosure sync-disclosure">
        <summary><span>打开加密同步工具</span><small>{cloudSync?.configured ? "WebDAV 已配置" : "WebDAV 未配置，可使用本地同步包"}</small></summary>
        <div className="sync-passphrase"><label>同步包口令<input className="sf-field" aria-label="设置页同步包口令" autoComplete="new-password" type="password" minLength={12} value={syncPassphrase} onChange={event => { setSyncPassphrase(event.target.value); setLocalSyncPreview(null); setCloudSyncPreview(null); setCloudSyncAction(null); }} placeholder="至少 12 个字符，仅保留在当前页面" /></label><small>同一口令用于导出、预览和恢复；系统不会保存口令。</small></div>
        <div className="sync-channel-grid">
          <section aria-labelledby="local-sync-title"><div><h4 id="local-sync-title">本地加密包</h4><p>下载备份，或选择已有加密包后先预览。</p></div><div className="button-row"><button type="button" className="ghost-button" disabled={syncBusy} onClick={() => void exportSyncBundle()}>导出加密包</button><label className="file-button sf-button sf-button--secondary">选择加密包<input aria-label="选择加密同步包" type="file" accept="application/json,.json" onChange={event => { setSyncFile(event.target.files?.[0] ?? null); setLocalSyncBundle(null); setLocalSyncPreview(null); }} /></label><button type="button" className="ghost-button" disabled={syncBusy || !syncFile} onClick={() => void previewImportedSync()}>预览导入</button></div><small>{syncFile ? `已选择：${syncFile.name}` : "尚未选择本地同步包"}</small></section>
          <section aria-labelledby="webdav-sync-title"><div><h4 id="webdav-sync-title">WebDAV 远端</h4><p>{cloudSync?.warning ?? "正在读取 WebDAV 配置状态…"}</p></div><div className="button-row"><button type="button" className="ghost-button" disabled={syncBusy || !cloudSync?.configured} onClick={() => void previewCloudSync("push")}>预览推送</button><button type="button" className="ghost-button" disabled={syncBusy || !cloudSync?.configured} onClick={() => void previewCloudSync("pull")}>预览拉取</button></div></section>
        </div>
        {localSyncPreview && <div className="setup-preview-composition sf-utility-surface"><div className="sf-surface-header"><div><strong className="sf-surface-title">本地同步导入预览</strong><p className="sf-surface-description">{localSyncPreview.warning}</p></div></div><small>新增 / 可恢复记录：{JSON.stringify(localSyncPreview.preview)}</small><div className="button-row"><button type="button" className="primary-button" disabled={syncBusy} onClick={() => void applyImportedSync()}>确认追加恢复</button><button type="button" className="text-button" onClick={() => { setLocalSyncBundle(null); setLocalSyncPreview(null); }}>取消</button></div></div>}
        {cloudSyncPreview && cloudSyncAction && <div className="setup-preview-composition sf-utility-surface"><div className="sf-surface-header"><div><strong className="sf-surface-title">WebDAV 同步预览</strong><p className="sf-surface-description">{String(cloudSyncPreview.warning ?? "请确认同步范围")}</p></div></div><small>{JSON.stringify(cloudSyncPreview.summary ?? cloudSyncPreview.preview ?? {})}</small><div className="button-row"><button type="button" className="primary-button" disabled={syncBusy} onClick={() => void confirmCloudSync(cloudSyncAction)}>确认{cloudSyncAction === "pull" ? "拉取并追加" : "推送"}</button><button type="button" className="text-button" onClick={() => { setCloudSyncPreview(null); setCloudSyncAction(null); }}>取消</button></div></div>}
      </details>
    </section>
  </div>;
}
