import { FormEvent, useEffect, useState } from "react";
import { api, downloadJson, getApiErrorMessage } from "./api";
import GitHubProjectPanel from "./GitHubProjectPanel";
import type { AuthorizedDirectory, KnowledgeTopic, Note, Project, ProjectBoard, ProjectMilestone, ProjectTimeline, Task } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

export default function ProjectsWorkspace({ onNotice, onError }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [projectPath, setProjectPath] = useState("");
  const [repositoryUrl, setRepositoryUrl] = useState("");
  const [technologies, setTechnologies] = useState("");
  const [authorizedDirectoryId, setAuthorizedDirectoryId] = useState("");
  const [directories, setDirectories] = useState<AuthorizedDirectory[]>([]);
  const [skills, setSkills] = useState("");
  const [outcomes, setOutcomes] = useState("");
  const [milestonesText, setMilestonesText] = useState("");
  const [selected, setSelected] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [topics, setTopics] = useState<KnowledgeTopic[]>([]);
  const [expandedProject, setExpandedProject] = useState<number | null>(null);
  const [milestones, setMilestones] = useState<Record<number, ProjectMilestone[]>>({});
  const [boards, setBoards] = useState<Record<number, ProjectBoard>>({});
  const [timelines, setTimelines] = useState<Record<number, ProjectTimeline>>({});
  const [newMilestone, setNewMilestone] = useState("");

  async function load() { try { const [projectData, taskData, noteData, topicData, directoryData] = await Promise.all([api.projects(), api.tasks(), api.notes(), api.topics(), api.authorizedDirectories()]); setProjects(projectData); setTasks(taskData); setNotes(noteData); setTopics(topicData); setDirectories(directoryData.filter(item => item.active)); } catch (e) { onError(e instanceof Error ? e.message : "项目加载失败"); } }
  useEffect(() => { void load(); }, []);
  async function openProject(projectId: number) { try { const [milestoneData, board, timeline] = await Promise.all([api.projectMilestones(projectId), api.projectBoard(projectId), api.projectTimeline(projectId)]); setExpandedProject(projectId); setMilestones(current => ({ ...current, [projectId]: milestoneData })); setBoards(current => ({ ...current, [projectId]: board })); setTimelines(current => ({ ...current, [projectId]: timeline })); } catch (error) { onError(getApiErrorMessage(error)); } }
  async function addMilestone(projectId: number) { if (!newMilestone.trim()) return; try { await api.createProjectMilestone(projectId, { title: newMilestone.trim(), order_index: milestones[projectId]?.length ?? 0 }); setNewMilestone(""); await openProject(projectId); onNotice("里程碑已添加。"); } catch (error) { onError(getApiErrorMessage(error)); } }
  async function updateEntityMilestone(projectId: number, milestoneId: number, changes: Partial<{ status: string; evidence: string }>) { try { await api.updateProjectMilestone(milestoneId, changes); await openProject(projectId); onNotice("里程碑已更新。"); } catch (error) { onError(getApiErrorMessage(error)); } }
  async function save(event: FormEvent) { event.preventDefault(); if (!title.trim()) return; try { const milestones = milestonesText.split("\n").map(item => item.trim()).filter(Boolean).map(item => ({ title: item, status: "pending", evidence: "" })); const payload = { title: title.trim(), description, path: projectPath.trim(), repository_url: repositoryUrl.trim(), technologies: technologies.split(",").map(x => x.trim()).filter(Boolean), authorized_directory_id: authorizedDirectoryId ? Number(authorizedDirectoryId) : null, skills: skills.split(",").map(x => x.trim()).filter(Boolean), outcomes: outcomes.split(",").map(x => x.trim()).filter(Boolean), milestones }; if (selected) await api.updateProject(selected.id, payload); else await api.createProject(payload); clearForm(); await load(); onNotice(selected ? "项目已更新。" : "项目已创建。"); } catch (e) { onError(e instanceof Error ? e.message : "项目保存失败"); } }
  function clearForm() { setTitle(""); setDescription(""); setProjectPath(""); setRepositoryUrl(""); setTechnologies(""); setAuthorizedDirectoryId(""); setSkills(""); setOutcomes(""); setMilestonesText(""); setSelected(null); }
  function edit(project: Project) { setSelected(project); setTitle(project.title); setDescription(project.description); setProjectPath(project.path); setRepositoryUrl(project.repository_url); setTechnologies(project.technologies.join(", ")); setAuthorizedDirectoryId(project.authorized_directory_id ? String(project.authorized_directory_id) : ""); setSkills(project.skills.join(", ")); setOutcomes(project.outcomes.join(", ")); setMilestonesText((project.milestones ?? []).map(item => String(item.title ?? "")).filter(Boolean).join("\n")); }
  async function updateMilestone(project: Project, index: number, changes: Record<string, unknown>) { const milestones = [...(project.milestones ?? [])]; milestones[index] = { ...milestones[index], ...changes }; try { await api.updateProject(project.id, { milestones }); await load(); onNotice("里程碑已更新。"); } catch (e) { onError(e instanceof Error ? e.message : "里程碑更新失败"); } }
  async function remove(project: Project) { if (!window.confirm(`确定删除项目“${project.title}”？关联任务不会被删除，但项目关联会被解除。`)) return; try { await api.deleteProject(project.id); await load(); onNotice("项目已删除。"); } catch (e) { onError(getApiErrorMessage(e)); } }
  return <section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">项目与成果</h2><p className="sf-surface-description">成果、技能证据与求职项目</p></div><span className="sf-surface-metadata">{projects.length} 个项目</span></div><form className="stack-form" onSubmit={save}><input aria-label="项目标题" value={title} onChange={e => setTitle(e.target.value)} placeholder="例如：学习工作站" /><textarea aria-label="项目描述" value={description} onChange={e => setDescription(e.target.value)} rows={3} placeholder="记录项目目标、成果和证据…" /><input aria-label="项目技能" value={skills} onChange={e => setSkills(e.target.value)} placeholder="技能，用逗号分隔，例如 FastAPI, SQLite" /><input aria-label="项目成果" value={outcomes} onChange={e => setOutcomes(e.target.value)} placeholder="成果，用逗号分隔，例如完成 API、写出部署文档" /><textarea aria-label="项目里程碑" value={milestonesText} onChange={e => setMilestonesText(e.target.value)} rows={3} placeholder="每行一个里程碑，例如：完成第一版 API" /><div className="form-footer"><button type="button" className="ghost-button" onClick={clearForm}>清空</button><button className="primary-button" disabled={!title.trim()}>{selected ? "保存项目" : "创建项目"}</button></div></form><div className="project-list">{projects.map(project => { const projectTasks = tasks.filter(task => task.project_id === project.id); const projectNotes = notes.filter(note => note.linked_project_ids?.includes(project.id)); const projectTopics = topics.filter(topic => projectNotes.some(note => note.linked_topic_ids?.includes(topic.id)) || projectTasks.some(task => task.topic_id === topic.id)); return <article className="topic-card project-card" key={project.id}><div className="project-card-header"><div><strong>{project.title}</strong><small>{project.status} · {project.skills.join(" · ") || "尚未填写技能"}</small></div><div><button className="ghost-button" onClick={() => edit(project)}>编辑</button><button className="ghost-button" onClick={() => void openProject(project.id)}>深化工作台</button><button className="ghost-button" onClick={() => void remove(project)}>删除</button></div></div><p>{project.description || "尚未填写描述"}</p><div className="project-evidence-grid"><div><span className="stat-label">成果</span><p>{project.outcomes?.join("、") || "尚未记录成果"}</p></div><div><span className="stat-label">关联任务</span><p>{projectTasks.length ? projectTasks.map(task => task.title).join("、") : "暂无关联任务"}</p></div><div><span className="stat-label">关联笔记</span><p>{projectNotes.length ? projectNotes.map(note => note.title).join("、") : "暂无关联笔记"}</p></div><div><span className="stat-label">关联知识</span><p>{projectTopics.length ? projectTopics.map(topic => topic.name).join("、") : "暂无关联主题"}</p></div></div>{project.milestones?.length ? <div className="milestone-list"><span className="stat-label">旧版里程碑</span>{project.milestones.map((milestone, index) => <div className="milestone-row" key={`${project.id}-${index}`}><strong>{String(milestone.title ?? `里程碑 ${index + 1}`)}</strong><select aria-label={`里程碑状态 ${project.id}-${index}`} value={String(milestone.status ?? "pending")} onChange={event => void updateMilestone(project, index, { status: event.target.value })}><option value="pending">待开始</option><option value="in_progress">进行中</option><option value="completed">已完成</option></select><input aria-label={`里程碑证据 ${project.id}-${index}`} value={String(milestone.evidence ?? "")} onChange={event => void updateMilestone(project, index, { evidence: event.target.value })} placeholder="成果证据" /></div>)}</div> : null}</article>; })}</div>{expandedProject !== null && <section className="project-deep-dive"><div className="sf-surface-header"><div><h3 className="sf-section-title">里程碑看板与时间线</h3><p className="sf-surface-description">独立记录完成状态和成果证据</p></div><button className="ghost-button" onClick={() => setExpandedProject(null)}>收起</button></div><div className="inline-form"><input aria-label="新里程碑标题" value={newMilestone} onChange={event => setNewMilestone(event.target.value)} placeholder="添加一个可验收里程碑" /><button type="button" className="primary-button" onClick={() => void addMilestone(expandedProject)}>添加</button></div><div className="board-columns">{Object.entries(boards[expandedProject]?.columns ?? {}).map(([status, rows]) => <div className="board-column" key={status}><strong>{status === "pending" ? "待开始" : status === "in_progress" ? "进行中" : status === "completed" ? "已完成" : "阻塞"} · {rows.length}</strong>{rows.map(row => <div className="board-item" key={row.id}><b>{row.title}</b><select aria-label={`里程碑状态 ${row.id}`} value={row.status} onChange={event => void updateEntityMilestone(expandedProject, row.id, { status: event.target.value })}><option value="pending">待开始</option><option value="in_progress">进行中</option><option value="completed">已完成</option><option value="blocked">阻塞</option></select><textarea aria-label={`里程碑证据 ${row.id}`} rows={2} defaultValue={row.evidence} onBlur={event => void updateEntityMilestone(expandedProject, row.id, { evidence: event.target.value })} placeholder="填写成果证据" /></div>)}</div>)}</div><div className="timeline-list">{(timelines[expandedProject]?.items ?? []).map(item => <div className="timeline-row" key={`${item.type}-${item.id}`}><span>{item.date ?? "未排期"}</span><strong>{item.title}</strong><small>{item.type === "milestone" ? "里程碑" : "任务"} · {item.status}</small></div>)}</div><GitHubProjectPanel projectId={expandedProject} onNotice={onNotice} onError={onError} /></section>}</section>;
}

export function ReviewScheduleWorkspace({ onNotice, onError }: Props) {
  const [preview, setPreview] = useState<import("./types").ReviewSchedule | null>(null);
  const [busy, setBusy] = useState(false);
  async function propose() { setBusy(true); try { setPreview(await api.scheduleReviews(false)); } catch (e) { onError(getApiErrorMessage(e)); } finally { setBusy(false); } }
  async function confirm() { setBusy(true); try { const result = await api.scheduleReviews(true); setPreview(result); onNotice(`已安排 ${result.created_reviews.length} 项复盘。`); } catch (e) { onError(getApiErrorMessage(e)); } finally { setBusy(false); } }
  return <section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">主动复盘安排</h2><p className="sf-surface-description">根据尚未安排复盘的学习记录生成安排，确认后才会写入。</p></div><button className="ghost-button" onClick={() => void propose()} disabled={busy}>{busy ? "计算中…" : "生成复盘安排"}</button></div>{preview && <div className="sf-utility-surface"><strong>{preview.recommendations.length ? `发现 ${preview.recommendations.length} 项待安排复盘` : "当前没有新的复盘安排"}</strong>{preview.recommendations.map(item => <div className="report-point" key={`${item.daily_log_id}-${item.review_date}`}><strong>学习记录 #{item.daily_log_id} · {item.review_date}</strong><p>{item.reason}</p><small>{item.note}</small></div>)}{preview.requires_confirmation && <button className="primary-button" onClick={() => void confirm()} disabled={busy}>确认并安排</button>}</div>}</section>;
}

export function ReviewWorkspace({ onNotice, onError }: Props) {
  const [reviews, setReviews] = useState<import("./types").Review[]>([]);
  const [quality, setQuality] = useState<Record<number, number>>({});
  async function load() { try { setReviews(await api.dueReviews()); } catch (e) { onError(e instanceof Error ? e.message : "复习任务加载失败"); } }
  useEffect(() => { void load(); }, []);
  async function complete(id: number) { try { await api.updateReview(id, "completed", quality[id] ?? 4); await load(); onNotice("复习已完成，下一次复习间隔已更新。"); } catch (e) { onError(e instanceof Error ? e.message : "复习更新失败"); } }
  return <section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">到期复习</h2><p className="sf-surface-description">按到期日期复习学习证据，并记录回忆质量</p></div><span className="sf-surface-metadata">{reviews.length} 项到期</span></div>{reviews.length ? reviews.map(review => <div className="task-row" key={review.id}><div><strong>学习记录 #{review.daily_log_id}</strong><small>{review.review_date} · {review.note || "复习并写下回忆要点"} · 当前间隔 {review.interval_days} 天</small></div><select aria-label={`复习质量 ${review.id}`} value={quality[review.id] ?? 4} onChange={event => setQuality(current => ({ ...current, [review.id]: Number(event.target.value) }))}><option value={0}>完全忘记</option><option value={2}>困难</option><option value={3}>一般</option><option value={4}>良好</option><option value={5}>轻松</option></select><button className="primary-button" onClick={() => void complete(review.id)}>完成复习</button></div>) : <div className="empty"><p>当前没有到期复习。</p></div>}</section>;
}

export function RestoreWorkspace({ onNotice, onError }: Props) {
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [snapshots, setSnapshots] = useState<import("./types").BackupSnapshot[]>([]);
  const [batches, setBatches] = useState<import("./types").RestoreBatch[]>([]);
  const [selectedSnapshot, setSelectedSnapshot] = useState<number | null>(null);
  const [diff, setDiff] = useState<import("./types").BackupDiff | null>(null);
  const [fieldDiff, setFieldDiff] = useState<import("./types").BackupFieldDiff | null>(null);
  const [mergePreview, setMergePreview] = useState<import("./types").BackupMergeResponse | null>(null);
  const [mergeSelections, setMergeSelections] = useState<Record<string, string[]>>({});
  const [mergeBatches, setMergeBatches] = useState<import("./types").BackupMergeBatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncPassphrase, setSyncPassphrase] = useState("");
  const [syncText, setSyncText] = useState("");
  const [syncPreview, setSyncPreview] = useState<import("./types").SyncPreview | null>(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [cloudPreview, setCloudPreview] = useState<Record<string, unknown> | null>(null);
  const [cloudDirection, setCloudDirection] = useState<"push" | "pull" | null>(null);

  async function loadHistory() {
    try {
      const [snapshotData, batchData, mergeBatchData] = await Promise.all([api.backupSnapshots(), api.restoreBatches(), api.backupMergeBatches()]);
      setSnapshots(snapshotData);
      setBatches(batchData);
      setMergeBatches(mergeBatchData);
    } catch (e) { onError(e instanceof Error ? e.message : "备份历史加载失败"); }
  }
  useEffect(() => { void loadHistory(); }, []);
  async function createSnapshot() {
    setLoading(true);
    try { await api.createBackupSnapshot("手动快照"); await loadHistory(); onNotice("备份版本已创建。"); }
    catch (e) { onError(e instanceof Error ? e.message : "创建备份版本失败"); }
    finally { setLoading(false); }
  }
  async function exportSyncBundle() {
    if (syncPassphrase.length < 12) { onError("同步包口令至少需要 12 个字符。"); return; }
    setSyncBusy(true);
    try {
      const result = await api.syncExport(syncPassphrase);
      downloadJson(`learning-workstation-sync-${new Date().toISOString().slice(0, 10)}.json`, result.bundle);
      setSyncText(JSON.stringify(result.bundle, null, 2));
      onNotice("加密同步包已生成并下载；请通过安全渠道传输。" );
    } catch (e) { onError(getApiErrorMessage(e)); }
    finally { setSyncBusy(false); }
  }
  async function previewSyncBundle() {
    if (syncPassphrase.length < 12) { onError("同步包口令至少需要 12 个字符。"); return; }
    try { setSyncPreview(await api.syncPreview(JSON.parse(syncText), syncPassphrase)); }
    catch (e) { onError(e instanceof SyntaxError ? "同步包 JSON 格式无效。" : getApiErrorMessage(e)); }
  }
  async function applySyncBundle() {
    if (!syncPreview) return;
    setSyncBusy(true);
    try {
      const result = await api.syncApply(JSON.parse(syncText), syncPassphrase, true);
      setSyncPreview(null); setSyncText(""); await loadHistory();
      onNotice(`同步完成：新增 ${Object.values((result.restored_counts ?? {}) as Record<string, number>).reduce((total, value) => total + value, 0)} 条记录。`);
    } catch (e) { onError(e instanceof SyntaxError ? "同步包 JSON 格式无效。" : getApiErrorMessage(e)); }
    finally { setSyncBusy(false); }
  }
  async function previewCloud(direction: "push" | "pull") {
    if (syncPassphrase.length < 12) { onError("同步包口令至少需要 12 个字符。"); return; }
    setSyncBusy(true);
    try {
      const result = direction === "push" ? await api.cloudSyncPush(syncPassphrase, false) : await api.cloudSyncPull(syncPassphrase, false);
      setCloudDirection(direction); setCloudPreview(result);
    } catch (e) { onError(getApiErrorMessage(e)); }
    finally { setSyncBusy(false); }
  }
  async function applyCloud() {
    if (!cloudDirection) return;
    setSyncBusy(true);
    try {
      const result = cloudDirection === "push" ? await api.cloudSyncPush(syncPassphrase, true) : await api.cloudSyncPull(syncPassphrase, true);
      setCloudPreview(null); setCloudDirection(null); await loadHistory();
      onNotice(cloudDirection === "push" ? "加密同步包已上传到云端。" : `云端同步完成：新增 ${Object.values((result.restored_counts ?? {}) as Record<string, number>).reduce((total, value) => total + value, 0)} 条记录。`);
    } catch (e) { onError(getApiErrorMessage(e)); }
    finally { setSyncBusy(false); }
  }
  async function previewRestore() { try { const result = await api.restoreBackup(JSON.parse(text), false); setPreview(result.preview as Record<string, unknown>); } catch (e) { onError(e instanceof Error ? e.message : "备份格式无效"); } }
  async function confirmRestore() { try { const result = await api.restoreBackup(JSON.parse(text), true); setPreview(null); setText(""); await loadHistory(); onNotice(`已完成恢复批次 #${String(result.restore_batch_id ?? "")}`); } catch (e) { onError(e instanceof Error ? e.message : "恢复失败"); } }
  async function compareSnapshots() {
    if (!selectedSnapshot || snapshots.length < 2) return;
    const other = snapshots.find(item => item.id !== selectedSnapshot);
    if (!other) return;
    try {
      setDiff(await api.backupDiff(other.id, selectedSnapshot));
      setFieldDiff(await api.backupFieldDiff(other.id, selectedSnapshot));
    } catch (e) { onError(e instanceof Error ? e.message : "备份差异比较失败"); }
  }
  async function previewMerge() {
    try { setMergePreview(await api.mergeBackup(JSON.parse(text), false)); } catch (e) { onError(e instanceof Error ? e.message : "合并预览失败"); }
  }
  async function confirmMerge() {
    try {
      const selections = Object.entries(mergeSelections).map(([key, fields]) => { const separator = key.indexOf("::"); return { entity_type: key.slice(0, separator), match_key: key.slice(separator + 2), fields }; });
      const result = await api.mergeBackup(JSON.parse(text), true, selections);
      setMergePreview(null); setMergeSelections({}); setText(""); await loadHistory();
      onNotice(`字段级合并完成：更新 ${result.affected_records ?? 0} 条记录。`);
    } catch (e) { onError(e instanceof Error ? e.message : "合并执行失败"); }
  }
  async function revertMergeBatch(batchId: number) {
    try {
      const previewResult = await api.revertBackupMergeBatch(batchId, false);
      const confirmed = window.confirm(`将撤销合并批次中的 ${String((previewResult.preview as Record<string, unknown> | undefined)?.patch_count ?? 0)} 条记录，是否继续？`);
      if (!confirmed) return;
      await api.revertBackupMergeBatch(batchId, true); await loadHistory(); onNotice("合并批次已撤销。");
    } catch (e) { onError(e instanceof Error ? e.message : "撤销合并失败"); }
  }
  async function revertBatch(batchId: number) {
    try {
      const previewResult = await api.revertRestoreBatch(batchId, false);
      const counts = (previewResult.preview ?? {}) as Record<string, number>;
      const confirmed = window.confirm(`将撤销本批次新增记录：${Object.entries(counts).map(([key, value]) => `${key} ${value}`).join("、") || "无可撤销记录"}。是否继续？`);
      if (!confirmed) return;
      await api.revertRestoreBatch(batchId, true); await loadHistory(); onNotice("恢复批次已撤销。");
    } catch (e) { onError(e instanceof Error ? e.message : "撤销恢复失败"); }
  }
  return <div className="restore-workspace">
    <section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">多设备加密同步</h2><p className="sf-surface-description">使用口令生成可迁移同步包；目标设备预览后才会追加数据。</p></div><span className="sf-surface-metadata">本地优先</span></div><div className="stack-form"><label>同步包口令<input aria-label="同步包口令" type="password" value={syncPassphrase} onChange={event => setSyncPassphrase(event.target.value)} placeholder="至少 12 个字符，不会保存" autoComplete="new-password" /></label><div className="form-footer"><span>内容使用口令加密；不会覆盖或删除目标设备数据。</span><button type="button" className="primary-button" disabled={syncBusy || syncPassphrase.length < 12} onClick={() => void exportSyncBundle()}>{syncBusy ? "处理中…" : "生成加密同步包"}</button></div><label>加密同步包 JSON<textarea aria-label="加密同步包 JSON" rows={7} value={syncText} onChange={event => { setSyncText(event.target.value); setSyncPreview(null); }} placeholder="在另一设备粘贴同步包 JSON…" /></label><div className="form-footer"><span>预览阶段不会写入数据。</span><button type="button" className="ghost-button" disabled={syncBusy || !syncText.trim() || syncPassphrase.length < 12} onClick={() => void previewSyncBundle()}>预览同步差异</button></div>{syncPreview && <div className="sf-utility-surface"><strong>同步预览</strong><p>{syncPreview.warning}</p><pre>{JSON.stringify({ preview: syncPreview.preview, diff: syncPreview.diff }, null, 2)}</pre><button type="button" className="primary-button" disabled={syncBusy} onClick={() => void applySyncBundle()}>确认追加到本设备</button></div>}<div className="form-footer"><span>云端仅保存加密包，上传或拉取都需要确认。</span><button type="button" className="ghost-button" disabled={syncBusy || syncPassphrase.length < 12} onClick={() => void previewCloud("push")}>预览云端上传</button><button type="button" className="ghost-button" disabled={syncBusy || syncPassphrase.length < 12} onClick={() => void previewCloud("pull")}>从云端预览</button></div>{cloudPreview && <div className="sf-utility-surface"><strong>{cloudDirection === "push" ? "云端上传预览" : "云端拉取预览"}</strong><pre>{JSON.stringify(cloudPreview, null, 2)}</pre><button type="button" className="primary-button" disabled={syncBusy} onClick={() => void applyCloud()}>{cloudDirection === "push" ? "确认上传加密包" : "确认追加云端数据"}</button></div>}</div></section>
    <section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">导入备份</h2><p className="sf-surface-description">追加模式 · 预览、确认、可撤销</p></div><button className="ghost-button" onClick={() => void createSnapshot()} disabled={loading}>{loading ? "创建中…" : "创建当前快照"}</button></div><textarea rows={8} value={text} onChange={e => setText(e.target.value)} placeholder="粘贴 JSON 备份内容…" /><div className="form-footer"><span>不会覆盖现有数据；恢复前必须先预览。</span><button className="primary-button" disabled={!text.trim()} onClick={() => void previewRestore()}>预览追加恢复</button><button className="ghost-button" disabled={!text.trim()} onClick={() => void previewMerge()}>预览字段级合并</button></div>{preview && <div className="sf-utility-surface"><strong>恢复预览</strong><pre>{JSON.stringify(preview, null, 2)}</pre><button className="primary-button" onClick={() => void confirmRestore()}>确认追加恢复</button></div>}{mergePreview && <div className="sf-utility-surface"><strong>字段级合并预览</strong><p>{mergePreview.warning}</p>{mergePreview.preview?.patches?.map((patch, index) => { const selectionKey = `${patch.entity_type}::${String(patch.match_key)}`; const selectedFields = mergeSelections[selectionKey] ?? patch.conflicts.map(item => item.field); return <div className="adjustment-change-row" key={index}><div><strong>{patch.label}</strong><small>{patch.entity_type} · {patch.conflicts.length} 个冲突字段</small>{patch.conflicts.map(item => <label key={item.field} className="merge-field-option"><input type="checkbox" checked={selectedFields.includes(item.field)} onChange={event => setMergeSelections(current => ({ ...current, [selectionKey]: event.target.checked ? [...selectedFields, item.field] : selectedFields.filter(field => field !== item.field) }))} />{item.field}: {String(item.current ?? "")} → {String(item.backup ?? "")}</label>)}</div></div>; }) ?? <p>没有可合并的已存在记录。</p>}<button className="primary-button" onClick={() => void confirmMerge()}>确认选中字段</button></div>}</section>
    <section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">备份版本</h2><p className="sf-surface-description">按内容哈希去重，保存本地快照摘要</p></div><span className="sf-surface-metadata">{snapshots.length} 个版本</span></div>{snapshots.length ? <div className="backup-list">{snapshots.map(snapshot => <label className={`backup-row ${selectedSnapshot === snapshot.id ? "selected" : ""}`} key={snapshot.id}><input type="radio" name="backup-snapshot" checked={selectedSnapshot === snapshot.id} onChange={() => setSelectedSnapshot(snapshot.id)} /><span><strong>#{snapshot.id} · {snapshot.label}</strong><small>{new Date(snapshot.created_at).toLocaleString()} · {snapshot.source} · {snapshot.sha256.slice(0, 12)}…</small></span><em>{Object.values(snapshot.summary).reduce((total, value) => total + value, 0)} 条记录</em></label>)}</div> : <div className="empty"><p>还没有保存的备份版本。</p></div>}<div className="form-footer"><span>选择一个版本后，与另一版本比较</span><button className="ghost-button" disabled={!selectedSnapshot || snapshots.length < 2} onClick={() => void compareSnapshots()}>比较差异</button></div>{diff && <div className="sf-utility-surface"><strong>版本差异：{diff.left.label} → {diff.right.label}</strong><pre>{JSON.stringify(diff.diff, null, 2)}</pre></div>}{fieldDiff && <div className="sf-utility-surface"><strong>字段级差异</strong>{Object.entries(fieldDiff.summary).filter(([, value]) => (value.added + value.removed + value.changed) > 0).map(([key, value]) => <p key={key}><strong>{key}</strong>：新增 {value.added} · 移除 {value.removed} · 字段变更 {value.changed}</p>)}{Object.entries(fieldDiff.records).filter(([, rows]) => rows.length).map(([key, rows]) => <div key={key}><strong>{key}</strong>{rows.slice(0, 8).map(row => <div className="adjustment-change-row" key={row.match_key}><div><strong>{row.label}</strong><small>{row.kind === "changed" ? `${row.fields?.length ?? 0} 个字段变化` : row.kind === "added" ? "仅存在于新版本" : "仅存在于旧版本"}</small></div>{row.kind === "changed" && <div className="change-values">{row.fields?.map(field => `${field.field}: ${String(field.before ?? "")} → ${String(field.after ?? "")}`).join("；")}</div>}</div>)}</div>)}</div>}</section>
    <section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">恢复记录</h2><p className="sf-surface-description">撤销只影响该批次实际新增的数据</p></div><span className="sf-surface-metadata">{batches.length} 个批次</span></div>{batches.length ? <div className="backup-list">{batches.map(batch => <div className="backup-row" key={batch.id}><span><strong>恢复批次 #{batch.id} · {batch.status}</strong><small>{new Date(batch.created_at).toLocaleString()} · 新增 {Object.values(batch.restored_counts).reduce((total, value) => total + value, 0)} 条</small></span>{batch.status !== "reverted" && <button className="ghost-button" onClick={() => void revertBatch(batch.id)}>预览并撤销</button>}</div>)}</div> : <div className="empty"><p>还没有恢复记录。</p></div>}</section><section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">合并审计</h2><p className="sf-surface-description">字段级合并可按批次撤销，后续修改会被保护</p></div><span className="sf-surface-metadata">{mergeBatches.length} 个批次</span></div>{mergeBatches.length ? <div className="backup-list">{mergeBatches.map(batch => <div className="backup-row" key={batch.id}><span><strong>合并批次 #{batch.id} · {batch.status}</strong><small>{new Date(batch.created_at).toLocaleString()} · {batch.patch_count} 条记录</small></span>{batch.status !== "reverted" && <button className="ghost-button" onClick={() => void revertMergeBatch(batch.id)}>预览并撤销</button>}</div>)}</div> : <div className="empty"><p>还没有字段级合并记录。</p></div>}</section>
  </div>;
}
