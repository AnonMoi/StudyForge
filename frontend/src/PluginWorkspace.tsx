import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, getApiErrorMessage } from "./api";
import type { PluginCommandPreview, PluginInstallPreview, PluginManifest, PluginRecord } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

const exampleManifest = {
  id: "study-summarizer",
  name: "学习摘要助手",
  version: "1.0.0",
  description: "将用户提供的材料整理为可复习的摘要。",
  permissions: ["model_task"],
  commands: [{
    id: "summarize",
    title: "生成摘要",
    description: "基于输入内容生成结构化摘要。",
    task_type: "summarize",
    prompt_template: "请将下面内容整理成分层摘要，并标出三个待复习要点：\n\n{{input}}",
  }],
};

export default function PluginWorkspace({ onNotice, onError }: Props) {
  const [plugins, setPlugins] = useState<PluginRecord[]>([]);
  const [manifestText, setManifestText] = useState(JSON.stringify(exampleManifest, null, 2));
  const [installPreview, setInstallPreview] = useState<PluginInstallPreview | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [commandId, setCommandId] = useState("");
  const [input, setInput] = useState("");
  const [commandPreview, setCommandPreview] = useState<PluginCommandPreview | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const data = await api.plugins();
      setPlugins(data);
      setSelectedId(current => current && data.some(item => item.manifest.id === current) ? current : data[0]?.manifest.id ?? null);
    } catch (error) { onError(getApiErrorMessage(error)); }
  }
  useEffect(() => { void load(); }, []);

  const selected = plugins.find(item => item.manifest.id === selectedId) ?? null;
  const commands = selected?.manifest.commands ?? [];
  const selectedCommand = useMemo(() => commands.find(item => item.id === commandId) ?? commands[0] ?? null, [commands, commandId]);

  async function previewInstall(event: FormEvent) {
    event.preventDefault();
    try {
      const manifest = JSON.parse(manifestText) as Record<string, unknown>;
      const result = await api.installPlugin(manifest, false);
      if ("manifest" in result) setInstallPreview(result);
    } catch (error) {
      onError(error instanceof SyntaxError ? "manifest 不是有效 JSON。" : getApiErrorMessage(error));
    }
  }

  async function confirmInstall() {
    if (!installPreview) return;
    setBusy(true);
    try {
      await api.installPlugin(installPreview.manifest as unknown as Record<string, unknown>, true);
      setInstallPreview(null); await load(); onNotice("插件已安装。");
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }

  async function toggle(plugin: PluginRecord) {
    setBusy(true);
    try { await api.togglePlugin(plugin.manifest.id, !plugin.enabled); await load(); onNotice(plugin.enabled ? "插件已停用。" : "插件已启用。"); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }

  async function requestDelete(pluginId: string) {
    try {
      const preview = await api.deletePlugin(pluginId, false);
      setPendingDelete(String(preview.plugin_id ?? pluginId));
    } catch (error) { onError(getApiErrorMessage(error)); }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setBusy(true);
    try { await api.deletePlugin(pendingDelete, true); setPendingDelete(null); await load(); onNotice("插件已卸载，学习数据未受影响。"); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }

  async function previewCommand() {
    if (!selected || !selectedCommand || !selected.enabled) return;
    setBusy(true);
    try { setCommandPreview(await api.runPluginCommand(selected.manifest.id, selectedCommand.id, input, false)); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }

  async function confirmCommand() {
    if (!selected || !selectedCommand) return;
    setBusy(true);
    try { setCommandPreview(await api.runPluginCommand(selected.manifest.id, selectedCommand.id, input, true)); onNotice("插件命令已执行。"); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }

  return <div className="plugin-workspace">
    <section className="plugin-header sf-open-section"><div><p className="card-kicker">DECLARATIVE EXTENSIONS / V1</p><h2 className="sf-section-title">扩展注册表</h2><p className="sf-surface-description">仅支持声明式 manifest 和模型任务命令，权限固定为 model_task。</p></div><span className="tag">{plugins.length} 个已注册</span></section>
    <div className="plugin-layout">
      <section className="stack-form plugin-install-panel sf-utility-surface"><div className="sf-surface-header"><div><h3 className="sf-surface-title">安装插件</h3><p className="sf-surface-description">导入前先检查 manifest，确认后才写入本机注册表。</p></div><span className="sf-surface-metadata">JSON</span></div><form onSubmit={previewInstall}><textarea aria-label="插件 manifest" rows={18} value={manifestText} onChange={event => setManifestText(event.target.value)} /><div className="form-footer"><span>不加载 JS、Python 或外部文件。</span><button className="primary-button" disabled={busy}>预览安装</button></div></form>{installPreview && <div className="plugin-confirm"><div className="sf-surface-header"><strong className="sf-surface-title">确认安装 {installPreview.manifest.name}</strong><span className="sf-surface-metadata">v{installPreview.manifest.version}</span></div><p>{installPreview.warning}</p><div className="plugin-manifest-summary"><span>{installPreview.manifest.commands.length} 个命令</span><span>{installPreview.already_installed ? "将更新已有版本" : "新注册"}</span><span>权限：{installPreview.manifest.permissions.join("、")}</span></div><div className="button-row"><button type="button" className="ghost-button" onClick={() => setInstallPreview(null)}>取消</button><button type="button" className="primary-button" disabled={busy} onClick={() => void confirmInstall()}>确认安装</button></div></div>}</section>
      <section className="plugin-list-panel sf-open-section"><div className="sf-surface-header"><div><h3 className="sf-section-title">已注册插件</h3><p className="sf-surface-description">停用后命令不可执行。</p></div><span className="sf-surface-metadata">{plugins.filter(item => item.enabled).length} 个启用</span></div>{plugins.length ? <div className="plugin-list">{plugins.map(plugin => <button type="button" className={`plugin-row ${selectedId === plugin.manifest.id ? "selected" : ""}`} key={plugin.manifest.id} onClick={() => { setSelectedId(plugin.manifest.id); setCommandId(""); setCommandPreview(null); }}><span className={`plugin-status ${plugin.enabled ? "enabled" : "disabled"}`} /><span><strong>{plugin.manifest.name}</strong><small>{plugin.manifest.id} · v{plugin.manifest.version}</small></span><em>{plugin.enabled ? "启用" : "停用"}</em></button>)}</div> : <div className="empty"><p>还没有注册插件。</p></div>}</section>
    </div>
    <section className="plugin-command-panel sf-open-section">{selected ? <><div className="sf-surface-header"><div><h3 className="sf-section-title">{selected.manifest.name}</h3><p className="sf-surface-description">{selected.manifest.description || "无描述"}</p></div><div className="button-row"><button type="button" className="ghost-button" disabled={busy} onClick={() => void toggle(selected)}>{selected.enabled ? "停用" : "启用"}</button><button type="button" className="ghost-button danger-button" disabled={busy} onClick={() => void requestDelete(selected.manifest.id)}>卸载</button></div></div><div className="plugin-command-grid"><div className="stack-form"><label>命令<select aria-label="插件命令" value={selectedCommand?.id ?? ""} onChange={event => { setCommandId(event.target.value); setCommandPreview(null); }}>{commands.map(command => <option key={command.id} value={command.id}>{command.title}</option>)}</select></label>{selectedCommand && <p className="plugin-command-description">{selectedCommand.description || "无命令说明"} · task_type: {selectedCommand.task_type}</p>}<textarea aria-label="命令输入" rows={7} value={input} onChange={event => { setInput(event.target.value); setCommandPreview(null); }} placeholder="输入要交给插件命令处理的内容…" /><button type="button" className="primary-button" disabled={busy || !selected.enabled || !selectedCommand} onClick={() => void previewCommand()}>预览执行</button></div><div className="plugin-result sf-utility-surface">{commandPreview ? <><div className="sf-surface-header"><strong className="sf-surface-title">{commandPreview.requires_confirmation ? "执行确认" : (commandPreview.success ? "执行完成" : "执行失败")}</strong><span className="sf-surface-metadata">{commandPreview.provider ?? commandPreview.task_type}</span></div>{commandPreview.requires_confirmation ? <><p>{commandPreview.warning}</p><div className="plugin-manifest-summary"><span>输入 {commandPreview.input_length} 字符</span><span>风险：{String(commandPreview.policy.risk ?? "low")}</span><span>{String(commandPreview.policy.reason ?? "按默认路由")}</span></div><div className="button-row"><button type="button" className="ghost-button" onClick={() => setCommandPreview(null)}>取消</button><button type="button" className="primary-button" disabled={busy} onClick={() => void confirmCommand()}>确认执行</button></div></> : <>{commandPreview.response && <pre>{commandPreview.response}</pre>}{commandPreview.error && <p className="error-text">{commandPreview.error}</p>}</>}</> : <div className="empty"><p>选择命令并预览执行，模型调用前会展示路由策略。</p></div>}</div></div></> : <div className="empty"><p>安装或选择一个插件开始。</p></div>}{pendingDelete && <div className="plugin-confirm delete-confirm sf-notice-surface sf-notice-surface--error"><strong>确认卸载插件？</strong><p>只会移除注册信息，不会删除学习数据。</p><div className="button-row"><button type="button" className="ghost-button" onClick={() => setPendingDelete(null)}>取消</button><button type="button" className="danger-button" disabled={busy} onClick={() => void confirmDelete()}>确认卸载</button></div></div>}</section>
  </div>;
}
