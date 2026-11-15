import { useEffect, useState } from "react";
import { api, getApiErrorMessage } from "./api";
import type { AuthorizedDirectory, ImportConfirmResponse, SetupInitializeResponse, SetupStatus, UserProfile, UserProfileUpdate } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void; onboarding?: boolean; onInitialized?: (setup: NonNullable<SetupInitializeResponse["setup"]>) => void; onFinished?: (setup: SetupStatus) => void };

const emptyProfile: UserProfileUpdate = { major: "", grade: "", long_term_goal: "", target_job_directions: [], confirmed_skills: [], unverified_skills: [], weak_capabilities: [], learning_preferences: [], proactive_level: "中主动" };
const splitLines = (value: string) => value.split(/[\n,，]/).map(item => item.trim()).filter(Boolean);
const fromProfile = (profile: UserProfile): UserProfileUpdate => ({ major: profile.major, grade: profile.grade, long_term_goal: profile.long_term_goal, target_job_directions: profile.target_job_directions, confirmed_skills: profile.confirmed_skills, unverified_skills: profile.unverified_skills, weak_capabilities: profile.weak_capabilities, learning_preferences: profile.learning_preferences, proactive_level: profile.proactive_level });

export default function UserProfileWorkspace({ onNotice, onError, onboarding = false, onInitialized, onFinished }: Props) {
  const [form, setForm] = useState<UserProfileUpdate>(emptyProfile);
  const [preview, setPreview] = useState<SetupInitializeResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [sourceStep, setSourceStep] = useState(false);
  const [directoryPath, setDirectoryPath] = useState("");
  const [directoryLabel, setDirectoryLabel] = useState("");
  const [directories, setDirectories] = useState<AuthorizedDirectory[]>([]);
  const [selectedDirectoryId, setSelectedDirectoryId] = useState("");
  const [activeDirectory, setActiveDirectory] = useState<AuthorizedDirectory | null>(null);
  const [importId, setImportId] = useState<number | null>(null);
  const [importPreview, setImportPreview] = useState<ImportConfirmResponse | null>(null);
  const [importResult, setImportResult] = useState<ImportConfirmResponse | null>(null);
  const [generateTasks, setGenerateTasks] = useState(false);
  const [generateReviews, setGenerateReviews] = useState(true);
  useEffect(() => { void api.userProfile().then(profile => setForm(fromProfile(profile))).catch(error => onError(getApiErrorMessage(error))); }, [onError]);
  useEffect(() => {
    if (!sourceStep) return;
    void api.authorizedDirectories().then(items => {
      const active = items.filter(item => item.active);
      setDirectories(active);
      if (!selectedDirectoryId && active.length === 1) setSelectedDirectoryId(String(active[0].id));
    }).catch(error => onError(getApiErrorMessage(error)));
  }, [sourceStep, onError, selectedDirectoryId]);
  const update = <K extends keyof UserProfileUpdate>(key: K, value: UserProfileUpdate[K]) => setForm(current => ({ ...current, [key]: value }));
  async function save() {
    setBusy(true);
    try { await api.updateUserProfile(form); onNotice("用户画像已保存，后续建议会以此为上下文。"); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }
  async function previewSetup() {
    setBusy(true);
    try { setPreview(await api.initializeSetup(form, false)); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }
  async function confirmSetup() {
    setBusy(true);
    try {
      const result = await api.initializeSetup(form, true);
      setPreview(null);
      if (result.setup) {
        onInitialized?.(result.setup);
      }
      setSourceStep(true);
      onNotice("用户画像已确认，首版学习主线已建立。现在可以授权资料目录并生成导入报告。");
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }
  async function scanDirectory(directory: AuthorizedDirectory) {
    setBusy(true);
    try {
      const report = await api.scanDirectory(directory.id);
      const nextImportId = typeof report.import_id === "number" ? report.import_id : null;
      if (!nextImportId) throw new Error("目录扫描没有返回导入记录");
      setActiveDirectory(directory);
      setImportId(nextImportId);
      setImportPreview(await api.importPreview(nextImportId));
      setImportResult(null);
      onNotice(`已扫描 ${directory.label || directory.path}，请检查导入报告后再确认写入。`);
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }
  async function authorizeAndScan() {
    if (selectedDirectoryId) {
      const existing = directories.find(item => item.id === Number(selectedDirectoryId));
      if (existing) return scanDirectory(existing);
    }
    if (!directoryPath.trim()) return;
    setBusy(true);
    try {
      const directory = await api.authorizeDirectory({ path: directoryPath.trim(), label: directoryLabel.trim(), local_analysis: true, cloud_transfer: false, write_access: false });
      setDirectories(current => [directory, ...current]);
      setSelectedDirectoryId(String(directory.id));
      await scanDirectory(directory);
    } catch (error) { onError(getApiErrorMessage(error)); setBusy(false); }
  }
  async function confirmImport() {
    if (!importId) return;
    setBusy(true);
    try {
      const result = await api.confirmImport(importId, { generate_tasks: generateTasks, generate_reviews: generateReviews });
      setImportResult(result);
      setImportPreview(null);
      onNotice("导入报告已确认，资料已写入本地知识库。");
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }
  async function finishOnboarding() {
    setBusy(true);
    try {
      const status = await api.completeSetup();
      onFinished?.(status);
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }
  const listField = (key: keyof UserProfileUpdate, label: string, placeholder: string) => <label>{label}<textarea className="sf-field" rows={2} value={(form[key] as string[]).join("\n")} onChange={event => update(key, splitLines(event.target.value) as UserProfileUpdate[typeof key])} placeholder={placeholder} /></label>;
  return <section className={`profile-workspace setup-section sf-open-section ${onboarding ? "onboarding-profile" : ""}`}>
    <div className="setup-section-heading sf-surface-header"><div><h2 className="sf-section-title">{onboarding ? "建立学习画像与首版主线" : "学习画像"}</h2><p className="sf-surface-description">这些内容是你确认过的学习事实；杏菜只会基于它们提出建议，不会替你决定方向。</p></div><span className="sf-surface-metadata">{onboarding ? "必需 · 预览后确认" : "已建立 · 可随时更新"}</span></div>
    {!sourceStep && <>
      <div className="profile-core-grid">
        <label>专业<input className="sf-field" value={form.major} onChange={event => update("major", event.target.value)} placeholder="例如：数据科学与大数据技术" /></label>
        <label>年级<input className="sf-field" value={form.grade} onChange={event => update("grade", event.target.value)} placeholder="例如：大一" /></label>
        <label className="profile-wide">长期学习目标 <em>必填</em><textarea className="sf-field" rows={3} required aria-required="true" value={form.long_term_goal} onChange={event => update("long_term_goal", event.target.value)} placeholder="你希望长期建立什么能力？" /></label>
        <label>杏菜的主动程度<select className="sf-field" value={form.proactive_level} onChange={event => update("proactive_level", event.target.value)}><option>低主动</option><option>中主动</option><option>高主动</option></select></label>
      </div>
      <details className="setup-disclosure profile-details">
        <summary><span>补充画像</span><small>推荐填写，用于提高建议的针对性</small></summary>
        <div className="profile-grid">{listField("target_job_directions", "目标岗位方向", "每行一个，可保留多个探索方向")}{listField("confirmed_skills", "已确认技能", "只有有证据支持的技能才放这里")}{listField("unverified_skills", "待验证技能", "接触过但尚未充分验证的技能")}{listField("weak_capabilities", "薄弱能力", "当前最需要补强的能力")}{listField("learning_preferences", "学习偏好", "例如：项目驱动、先理解原理再练习")}</div>
      </details>
      <div className="setup-action-row"><span>保存画像不会导入资料，也不会调用云端模型。</span><div className="button-row"><button type="button" className="ghost-button" onClick={() => void save()} disabled={busy}>{busy ? "保存中…" : onboarding ? "保存为画像草稿" : "保存画像"}</button>{onboarding && <button type="button" className="primary-button" onClick={() => void previewSetup()} disabled={busy || !form.long_term_goal.trim()}>{busy ? "处理中…" : "预览首版学习主线"}</button>}</div></div>
    </>}
    {preview?.plan_preview && <div className="setup-preview-composition sf-utility-surface"><div className="sf-surface-header"><div><strong className="sf-surface-title">首版学习主线预览</strong><p className="sf-surface-description">确认前不会创建目标、阶段或任务。</p></div></div><dl><div><dt>长期目标</dt><dd>{preview.plan_preview.goal_title}</dd></div><div><dt>第一阶段</dt><dd>{preview.plan_preview.stage_title}</dd></div><div><dt>第一项任务</dt><dd>{preview.plan_preview.task_title}</dd></div><div><dt>能力目标</dt><dd>{preview.plan_preview.capability_targets.join("、")}</dd></div></dl><div className="setup-action-row"><button type="button" className="text-button" onClick={() => setPreview(null)}>返回修改</button><button type="button" className="primary-button" onClick={() => void confirmSetup()} disabled={busy}>{busy ? "建立中…" : "确认并建立学习主线"}</button></div></div>}
    {onboarding && sourceStep && <div className="onboarding-sources"><div className="setup-section-heading sf-surface-header"><div><h3 className="sf-section-title">授权学习资料</h3><p className="sf-surface-description">这是推荐步骤，可以跳过。目录只在明确授权后本地扫描，导入前始终先展示报告。</p></div><span className="sf-surface-metadata">推荐 · 可稍后处理</span></div><div className="stack-form setup-source-form">{directories.length > 0 && <label>使用已有授权目录<select className="sf-field" aria-label="首次启动已有授权目录" value={selectedDirectoryId} onChange={event => { setSelectedDirectoryId(event.target.value); setDirectoryPath(""); }}><option value="">新授权目录</option>{directories.map(item => <option key={item.id} value={item.id}>{item.label || item.path}</option>)}</select></label>}{!selectedDirectoryId && <><label>本地资料目录<input className="sf-field" aria-label="首次启动资料目录" value={directoryPath} onChange={event => setDirectoryPath(event.target.value)} placeholder="例如 C:\\Users\\你\\学习资料" /></label><label>目录名称<input className="sf-field" aria-label="首次启动目录名称" value={directoryLabel} onChange={event => setDirectoryLabel(event.target.value)} placeholder="例如：课程资料" /></label></>}<div className="button-row"><button type="button" className="primary-button" onClick={() => void authorizeAndScan()} disabled={busy || (!selectedDirectoryId && !directoryPath.trim())}>{busy ? "扫描中…" : selectedDirectoryId ? "扫描已有授权目录" : "授权并扫描目录"}</button><button type="button" className="text-button" onClick={() => void finishOnboarding()} disabled={busy}>暂不导入</button></div></div>{activeDirectory && <small>当前目录：{activeDirectory.label || activeDirectory.path} · 本地分析允许 · 云端发送关闭 · 写入关闭</small>}{importPreview && <div className="setup-preview-composition sf-utility-surface"><div className="sf-surface-header"><div><strong className="sf-surface-title">导入报告预览</strong><p className="sf-surface-description">发现 {importPreview.files ?? importPreview.preview?.length ?? 0} 个文件。确认后会保留原始副本、正文和索引，并创建来源笔记。</p></div></div><div className="import-options"><label><input type="checkbox" checked={generateTasks} onChange={event => setGenerateTasks(event.target.checked)} />为导入主题生成学习任务</label><label><input type="checkbox" checked={generateReviews} onChange={event => setGenerateReviews(event.target.checked)} />为导入主题安排首次复习</label></div><div className="import-preview-list">{importPreview.preview?.slice(0, 12).map(item => <div className="task-row" key={item.imported_file_id}><span>{item.relative_path}</span><small>{item.suggested_topics.join("、") || "未提取到主题"}</small></div>)}</div><div className="setup-action-row"><button type="button" className="primary-button" onClick={() => void confirmImport()} disabled={busy || !importId}>{busy ? "写入中…" : "确认并写入知识库"}</button></div></div>}{importResult && <div className="setup-result-notice sf-notice-surface sf-notice-surface--success" role="status"><strong>导入已完成</strong><p>已处理 {importResult.confirmed_files ?? 0} 个文件，新增 {importResult.created_topics ?? 0} 个知识主题和 {importResult.created_notes ?? 0} 篇来源笔记。</p><div className="setup-action-row"><span>后续仍可在“文件导入”页继续管理目录。</span><button type="button" className="primary-button" onClick={() => void finishOnboarding()} disabled={busy}>完成设置</button></div></div>}</div>}
  </section>;
}
