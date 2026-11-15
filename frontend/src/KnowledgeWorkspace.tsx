import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api, getApiErrorMessage } from "./api";
import type { AnalyticsSummary, KnowledgeGraph, KnowledgeTopic, ScanJob } from "./types";
import KnowledgeGraphCanvas from "./KnowledgeGraphCanvas";
import PageHeader from "./PageHeader";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

export function KnowledgeWorkspace({ onNotice, onError }: Props) {
  const [topics, setTopics] = useState<KnowledgeTopic[]>([]);
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [definition, setDefinition] = useState("");
  const [query, setQuery] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [relationType, setRelationType] = useState("related");
  const [showWeakOnly, setShowWeakOnly] = useState(false);
  const [showOrphansOnly, setShowOrphansOnly] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ name: "", domain: "", definition: "", self_level: "有印象", tags: "", prerequisites: "" });
  const [verifyForm, setVerifyForm] = useState({ level: 0, evidence: "", source_type: "user_verification" });

  const load = async () => {
    try { const [topicData, graphData] = await Promise.all([api.topics(), api.graph()]); setTopics(topicData); setGraph(graphData); }
    catch (e) { onError(getApiErrorMessage(e)); }
  };
  useEffect(() => { void load(); }, []);
  async function create(event: FormEvent) { event.preventDefault(); if (!name.trim()) return; try { await api.createTopic({ name: name.trim(), domain: domain || "待整理", definition }); setName(""); setDomain(""); setDefinition(""); await load(); onNotice("知识主题已创建。"); } catch (e) { onError(getApiErrorMessage(e)); } }
  async function createRelation(event: FormEvent) { event.preventDefault(); if (!sourceId || !targetId || sourceId === targetId) return; try { await api.createRelation(Number(sourceId), Number(targetId), relationType); setSourceId(""); setTargetId(""); await load(); onNotice("知识关系已建立。"); } catch (e) { onError(getApiErrorMessage(e)); } }
  async function removeRelation(id: number) { if (!window.confirm("删除这条知识关系？此操作不会删除主题。")) return; try { await api.deleteRelation(id); await load(); onNotice("知识关系已删除。"); } catch (e) { onError(getApiErrorMessage(e)); } }
  function beginEdit(topic: KnowledgeTopic) { setEditingId(topic.id); setEditForm({ name: topic.name, domain: topic.domain, definition: topic.definition, self_level: topic.self_level, tags: topic.tags.join(", "), prerequisites: topic.prerequisites.join(", ") }); }
  async function saveTopic(topicId: number) { try { await api.updateTopic(topicId, { name: editForm.name.trim(), domain: editForm.domain.trim() || "待整理", definition: editForm.definition, self_level: editForm.self_level, tags: editForm.tags.split(",").map(item => item.trim()).filter(Boolean), prerequisites: editForm.prerequisites.split(",").map(item => Number(item.trim())).filter(item => Number.isInteger(item) && item > 0) }); setEditingId(null); await load(); onNotice("知识主题已更新。"); } catch (e) { onError(getApiErrorMessage(e)); } }
  async function verifyTopic(topicId: number) { if (!verifyForm.evidence.trim()) return; try { await api.verifyTopic(topicId, { verified_level: verifyForm.level, evidence: verifyForm.evidence.trim(), source_type: verifyForm.source_type }); setVerifyForm({ level: 0, evidence: "", source_type: "user_verification" }); await load(); onNotice("知识主题验证证据已保存。"); } catch (e) { onError(getApiErrorMessage(e)); } }
  const filtered = useMemo(() => topics.filter(topic => `${topic.name} ${topic.domain} ${topic.definition}`.toLowerCase().includes(query.toLowerCase())), [topics, query]);
  const topicName = (id: number) => topics.find(topic => topic.id === id)?.name ?? `#${id}`;
  return <div className="knowledge-workspace"><section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">岗位方向分析</h2><p className="sf-surface-description">根据已确认的岗位方向标出相关主题和前置缺口。</p></div><span className="sf-surface-metadata">{graph?.analysis?.job_direction ?? "未设置"}</span></div><p>{graph?.analysis?.job_relevant_topics?.join("、") || "暂无匹配主题"}</p><small>需要补强：{graph?.analysis?.job_direction_gaps?.map(item => `${item.name}（${item.reason}）`).join("、") || "暂无"}</small></section>
    <section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">主题与掌握度</h2><p className="sf-surface-description">主题、定义、关系与掌握度</p></div><span className="sf-surface-metadata">{topics.length} 个主题 · {graph?.edges.length ?? 0} 条关系</span></div>
      <form className="stack-form" onSubmit={create}><input aria-label="知识主题名称" value={name} onChange={e => setName(e.target.value)} placeholder="例如：FastAPI 依赖注入" /><input aria-label="知识领域" value={domain} onChange={e => setDomain(e.target.value)} placeholder="领域，例如：后端开发" /><textarea aria-label="知识定义" value={definition} onChange={e => setDefinition(e.target.value)} rows={3} placeholder="用自己的话写下定义…" /><button className="primary-button" disabled={!name.trim()}>创建主题</button></form>
      <div className="notes-toolbar"><input aria-label="搜索知识主题" value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索主题…" /></div>
      <div className="topic-grid">{filtered.map(topic => <article className="topic-card" key={topic.id}>{editingId === topic.id ? <div className="stack-form"><input aria-label="编辑主题名称" value={editForm.name} onChange={e => setEditForm({ ...editForm, name: e.target.value })} /><input aria-label="编辑主题领域" value={editForm.domain} onChange={e => setEditForm({ ...editForm, domain: e.target.value })} /><textarea aria-label="编辑主题定义" value={editForm.definition} onChange={e => setEditForm({ ...editForm, definition: e.target.value })} rows={3} /><input aria-label="编辑主题自评" value={editForm.self_level} onChange={e => setEditForm({ ...editForm, self_level: e.target.value })} /><input aria-label="编辑主题标签" value={editForm.tags} onChange={e => setEditForm({ ...editForm, tags: e.target.value })} placeholder="标签，用逗号分隔" /><input aria-label="编辑前置主题" value={editForm.prerequisites} onChange={e => setEditForm({ ...editForm, prerequisites: e.target.value })} placeholder="前置主题 ID，用逗号分隔" /><div className="button-row"><button className="primary-button" disabled={!editForm.name.trim()} onClick={() => void saveTopic(topic.id)}>保存</button><button className="ghost-button" onClick={() => setEditingId(null)}>取消</button></div></div> : <><strong>{topic.name}</strong><small>{topic.domain} · 自评 {topic.self_level}</small><p>{topic.definition || "尚未填写定义"}</p><div className="button-row"><span className="tag">验证等级 {topic.verified_level}/8</span><button className="ghost-button" onClick={() => beginEdit(topic)}>编辑主题</button></div><details><summary>添加验证证据</summary><div className="stack-form"><label>验证等级<select value={verifyForm.level} onChange={e => setVerifyForm({ ...verifyForm, level: Number(e.target.value) })}>{Array.from({ length: 9 }, (_, index) => <option key={index} value={index}>{index}/8</option>)}</select></label><input aria-label="验证来源类型" value={verifyForm.source_type} onChange={e => setVerifyForm({ ...verifyForm, source_type: e.target.value })} /><textarea aria-label="验证证据" value={verifyForm.evidence} onChange={e => setVerifyForm({ ...verifyForm, evidence: e.target.value })} rows={2} placeholder="填写练习、项目、解释或技术校验依据" /><button className="primary-button" disabled={!verifyForm.evidence.trim()} onClick={() => void verifyTopic(topic.id)}>保存验证</button></div></details></>}</article>)}</div>{!filtered.length && <div className="empty"><p>还没有匹配的知识主题。</p></div>}
    </section>
    <section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">关系管理</h2><p className="sf-surface-description">建立前置知识和相关主题连接</p></div></div><form className="inline-form relation-form" onSubmit={createRelation}><select aria-label="关系源主题" value={sourceId} onChange={e => setSourceId(e.target.value)}><option value="">源主题</option>{topics.map(topic => <option key={topic.id} value={topic.id}>{topic.name}</option>)}</select><select aria-label="关系类型" value={relationType} onChange={e => setRelationType(e.target.value)}><option value="related">相关</option><option value="prerequisite">前置知识</option><option value="extends">扩展</option></select><select aria-label="关系目标主题" value={targetId} onChange={e => setTargetId(e.target.value)}><option value="">目标主题</option>{topics.map(topic => <option key={topic.id} value={topic.id}>{topic.name}</option>)}</select><button className="primary-button" disabled={!sourceId || !targetId || sourceId === targetId}>建立关系</button></form>{graph?.edges.length ? <div className="relation-list">{graph.edges.map(edge => <div className="task-row" key={edge.id}><div><strong>{topicName(edge.source_topic_id)} → {topicName(edge.target_topic_id)}</strong><small>{edge.relation_type}</small></div><button className="ghost-button" onClick={() => void removeRelation(edge.id)}>删除</button></div>)}</div> : <div className="empty"><p>建立关系后会显示在这里。</p></div>}</section>
    <section className="sf-open-section"><div className="sf-surface-header"><h2 className="sf-section-title">知识分析</h2><span className="sf-surface-metadata">节点 {graph?.nodes.length ?? 0} · 边 {graph?.edges.length ?? 0}</span></div><dl className="knowledge-analysis-grid">{[["薄弱主题", graph?.analysis?.weak_topics ?? []], ["孤立主题", graph?.analysis?.orphan_topics ?? []], ["学过但未实践", graph?.analysis?.learned_without_practice ?? []], ["实践但未形成笔记", graph?.analysis?.practice_without_notes ?? []], ["前置知识缺口", graph?.analysis?.prerequisite_gaps ?? []]].map(([label, values]) => <div className="knowledge-analysis-cell" key={String(label)}><dt>{label}</dt><dd>{(values as string[]).join("、") || "暂无"}</dd></div>)}</dl></section>
    <section className="sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">交互式知识图谱</h2><p className="sf-surface-description">支持拖拽、缩放、筛选，以及查看主题之间的关系路径。</p></div><span className="sf-surface-metadata">节点 {graph?.nodes.length ?? 0} · 边 {graph?.edges.length ?? 0}</span></div><div className="graph-filter-row"><label><input aria-label="仅显示薄弱主题" type="checkbox" checked={showWeakOnly} onChange={e => setShowWeakOnly(e.target.checked)} />仅显示薄弱主题</label><label><input aria-label="仅显示孤立主题" type="checkbox" checked={showOrphansOnly} onChange={e => setShowOrphansOnly(e.target.checked)} />仅显示孤立主题</label></div>{graph ? <KnowledgeGraphCanvas graph={graph} query={query} showWeakOnly={showWeakOnly} showOrphansOnly={showOrphansOnly} /> : <div className="empty"><p>正在加载图谱…</p></div>}</section>
    <section className="sf-open-section"><div className="sf-surface-header"><h2 className="sf-section-title">基础图谱</h2><span className="sf-surface-metadata">列表视图</span></div><div className="graph-list">{graph?.nodes.map(node => <div className={`graph-node ${node.weak ? "weak" : ""}`} key={node.id}><strong>{node.name}</strong><small>{node.domain} · 验证 {node.verified_level}/8 · 连接 {node.degree ?? 0} · 实践 {node.practice_count ?? 0}</small></div>)}</div></section>
  </div>;
}

export function AnalyticsWorkspace({ onNotice, onError }: Props) {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const rhythmScrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true);
    api.analytics(days)
      .then(data => { if (active) setSummary(data); })
      .catch(e => { if (active) onError(e instanceof Error ? e.message : "这次没能读到复盘数据，请稍后再试。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [days]);
  useEffect(() => {
    if (loading || !summary) return;
    const frame = window.requestAnimationFrame(() => {
      const container = rhythmScrollRef.current;
      if (container) container.scrollLeft = container.scrollWidth;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [days, loading, summary]);
  const maxMinutes = Math.max(1, ...(summary?.daily.map(item => item.minutes) ?? [1]));
  const metrics = summary?.metrics;
  const period = useMemo(() => (summary?.daily ?? []).reduce((total, item) => ({
    minutes: total.minutes + item.minutes,
    outputs: total.outputs + item.outputs,
    logs: total.logs + item.logs,
    completedTasks: total.completedTasks + item.completed_tasks,
    activeDays: total.activeDays + (item.minutes > 0 || item.logs > 0 || item.outputs > 0 ? 1 : 0),
  }), { minutes: 0, outputs: 0, logs: 0, completedTasks: 0, activeDays: 0 }), [summary]);
  const rangeLabel = `最近 ${days} 天`;
  const topicReview = (quality: number | null) => quality == null ? "还没有回看记录" : quality >= 4 ? "回想得比较顺" : quality >= 3 ? "正在慢慢变熟" : "回想时还有些吃力";
  const teachingReview = (score: number | null) => score == null ? "还没有尝试讲解" : score >= 4 ? "已经能讲得比较完整" : score >= 3 ? "主要思路已经说到了" : "还需要补清定义和步骤";
  const capabilityStage = (level: number) => level >= 7 ? "已经能独立运用" : level >= 5 ? "能在任务中使用" : level >= 3 ? "正在形成稳定理解" : level > 0 ? "刚开始积累" : "还没有留下评估";
  const observations = metrics ? [
    metrics.due_tasks ? `有 ${metrics.due_tasks} 项任务设置了截止日期，其中 ${metrics.overdue_tasks} 项已经逾期。` : "目前还没有设置截止日期的任务。",
    `计划里有 ${metrics.theory_tasks} 项偏理解的任务、${metrics.practice_tasks} 项动手任务。`,
    `已经留下 ${metrics.input_items} 条学习记录，并写下 ${metrics.output_items} 项成果。`,
    metrics.practice_attempts ? `完成了 ${metrics.practice_attempts} 次练习作答，约 ${Math.round((metrics.practice_pass_rate ?? 0) * 100)}% 通过。` : "还没有练习作答记录。",
    metrics.project_milestones ? `${metrics.project_count} 个项目共拆出 ${metrics.project_milestones} 个里程碑，已经完成 ${metrics.completed_milestones} 个。` : "还没有把项目拆成可跟进的里程碑。",
    metrics.repeated_error_cards ? `${metrics.repeated_error_cards} 张回看卡记录过重复出错，适合优先回看。` : "暂时没有记录到反复出现的错误。",
  ] : [];

  return <div className="analytics-workspace">
    <PageHeader mode="reading" title="统计复盘" description="翻一翻这段时间真正留下来的学习记录。" titleId="analytics-page-title" actions={<div className="analytics-page-actions"><label>查看范围<select aria-label="统计时间范围" value={days} onChange={event => setDays(Number(event.target.value))}><option value={14}>最近 14 天</option><option value={30}>最近 30 天</option><option value={90}>最近 90 天</option></select></label><button className="ghost-button" onClick={async () => { try { const data = await api.backup(); api.downloadBackup(data); onNotice("数据备份已下载。"); } catch (e) { onError(e instanceof Error ? e.message : "这次没能下载备份，请稍后再试。"); } }}>下载数据备份</button></div>} />
    <article className="analytics-sheet sf-writing-surface">

      {loading ? <div className="analytics-loading" role="status"><strong>正在整理这段时间的记录</strong><span>学习时间、任务和回看结果会一起汇总。</span></div> : <>
        <section className="analytics-period sf-open-section" aria-labelledby="analytics-period-title">
          <div className="analytics-section-heading sf-surface-header"><div><h2 className="sf-section-title" id="analytics-period-title">这段时间留下了什么</h2><p className="sf-surface-description">{rangeLabel}共记录 {period.minutes} 分钟学习，留下 {period.outputs} 项成果，完成 {period.completedTasks} 项任务。</p></div></div>
          <dl className="analytics-ledger">
            <div><dt>有学习记录的日子</dt><dd>{period.activeDays}<small>天</small></dd></div>
            <div><dt>写下的学习日志</dt><dd>{period.logs}<small>条</small></dd></div>
            <div><dt>今天已经学习</dt><dd>{summary?.today_minutes ?? 0}<small>分钟</small></dd></div>
            <div><dt>这周已经学习</dt><dd>{summary?.week_minutes ?? 0}<small>分钟</small></dd></div>
          </dl>
        </section>

        <section className="analytics-section sf-open-section" aria-labelledby="analytics-rhythm-title">
          <div className="analytics-section-heading sf-surface-header"><div><h2 className="sf-section-title" id="analytics-rhythm-title">每天的学习节奏</h2><p className="sf-surface-description">{period.activeDays ? `${rangeLabel}里有 ${period.activeDays} 天留下记录，最高的一天学习了 ${maxMinutes} 分钟。` : `${rangeLabel}还没有学习记录。`}</p></div></div>
          <figure className="analytics-rhythm"><figcaption className="sr-only">{rangeLabel}每日学习分钟数</figcaption><div className="analytics-rhythm-scroll" ref={rhythmScrollRef}><div className="analytics-rhythm-bars" style={{ minWidth: `${Math.max(560, (summary?.daily.length ?? 0) * 26)}px` }}>{summary?.daily.map((item, index) => <div className={`analytics-day ${item.minutes ? "has-record" : ""}`} key={item.date} aria-label={`${item.date}，学习 ${item.minutes} 分钟，完成 ${item.completed_tasks} 项任务`}><div className="analytics-day-track"><span style={{ height: `${item.minutes ? Math.max(7, item.minutes / maxMinutes * 100) : 2}%` }} /></div><time dateTime={item.date}>{index % (days === 90 ? 10 : days === 30 ? 5 : 2) === 0 || index === (summary?.daily.length ?? 1) - 1 ? item.date.slice(5).replace("-", "/") : ""}</time></div>)}</div></div></figure>
        </section>

        <section className="analytics-section sf-open-section" aria-labelledby="analytics-attention-title">
          <div className="analytics-section-heading sf-surface-header"><div><h2 className="sf-section-title" id="analytics-attention-title">哪些地方值得留意</h2><p className="sf-surface-description">这里只陈述已有记录，不替你给学习状态下结论。</p></div></div>
          {observations.length ? <ul className="analytics-observations">{observations.map(item => <li key={item}><p>{item}</p></li>)}</ul> : <p className="analytics-empty-copy">还没有足够的过程记录可供回看。</p>}
        </section>

        <section className="analytics-section sf-open-section" aria-labelledby="analytics-topics-title">
          <div className="analytics-section-heading sf-surface-header"><div><h2 className="sf-section-title" id="analytics-topics-title">最近在学哪些主题</h2><p className="sf-surface-description">按实际投入时间排列，方便找到最近最常接触的内容。</p></div><strong className="sf-surface-metadata">{summary?.topics.length ?? 0} 个主题</strong></div>
          {summary?.topics.length ? <div className="analytics-topic-list">{summary.topics.slice().sort((a, b) => b.minutes - a.minutes || b.task_count - a.task_count).map(item => <article className="analytics-topic-row" key={item.topic_id}><div><span>{item.domain}</span><h4>{item.name}</h4></div><dl><div><dt>投入</dt><dd>{item.minutes} 分钟</dd></div><div><dt>任务</dt><dd>{item.completed_tasks}/{item.task_count} 项完成</dd></div></dl><p>{topicReview(item.average_quality)}；{teachingReview(item.average_score)}。</p></article>)}</div> : <p className="analytics-empty-copy">把日志或任务关联到知识主题后，这里会慢慢形成脉络。</p>}
        </section>

        <section className="analytics-section sf-open-section" aria-labelledby="analytics-capability-title">
          <div className="analytics-section-heading sf-surface-header"><div><h2 className="sf-section-title" id="analytics-capability-title">能力变化</h2><p className="sf-surface-description">根据你保存的练习、项目和讲解记录，看看能力积累到了哪里。</p></div></div>
          {summary?.capabilities.length ? <div className="analytics-capability-list">{summary.capabilities.map(profile => <article className="analytics-capability-row" key={profile.id}><div><h4>{profile.name}</h4><p>{capabilityStage(profile.level)} · {profile.evidence_count ? `已有 ${profile.evidence_count} 条依据` : "还没有保存依据"}</p></div><div className="analytics-capability-progress" role="progressbar" aria-label={`${profile.name}当前进度`} aria-valuemin={0} aria-valuemax={8} aria-valuenow={profile.level}><span style={{ width: `${Math.min(100, profile.level / 8 * 100)}%` }} /></div><strong>{profile.level.toFixed(1)}<small>/8</small></strong></article>)}</div> : <p className="analytics-empty-copy">完成一次练习、项目或自我讲解后，这里才会有可以回看的变化。</p>}
        </section>

        <details className="analytics-system-record sf-utility-surface">
          <summary><span><strong>系统使用记录</strong><small>累计模型调用与费用估算</small></span><span aria-hidden="true">展开</span></summary>
          <div><p>这里是全部时间的累计值，不随上方查看范围变化。</p><dl><div><dt>模型调用</dt><dd>{summary?.model_calls.total ?? 0} 次</dd></div><div><dt>实际用量</dt><dd>{summary?.model_calls.actual_tokens ?? 0} Token</dd></div><div><dt>估算用量</dt><dd>{summary?.model_calls.estimated_tokens ?? 0} Token</dd></div><div><dt>估算费用</dt><dd>¥{(summary?.model_calls.estimated_cost ?? 0).toFixed(4)}</dd></div></dl></div>
        </details>
      </>}
    </article>
  </div>;
}

export function ImportsWorkspace({ onNotice, onError }: Props) {
  const [path, setPath] = useState("");
  const [label, setLabel] = useState("");
  const [localAnalysis, setLocalAnalysis] = useState(true);
  const [cloudTransfer, setCloudTransfer] = useState(false);
  const [writeAccess, setWriteAccess] = useState(false);
  const [excludedExtensions, setExcludedExtensions] = useState("");
  const [allowedExtensions, setAllowedExtensions] = useState("");
  const [excludedPatterns, setExcludedPatterns] = useState("");
  const [query, setQuery] = useState("");
  const [directories, setDirectories] = useState<import("./types").AuthorizedDirectory[]>([]);
  const [changes, setChanges] = useState<Record<number, import("./types").DirectoryChangeAlert[]>>({});
  const [scanJobs, setScanJobs] = useState<Record<number, ScanJob[]>>({});
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [matches, setMatches] = useState<import("./types").ImportSearchResult["matches"]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [latestImportId, setLatestImportId] = useState<number | null>(null);
  const [importPreview, setImportPreview] = useState<import("./types").ImportConfirmResponse | null>(null);
  const [importing, setImporting] = useState(false);
  const [generateTasks, setGenerateTasks] = useState(false);
  const [generateReviews, setGenerateReviews] = useState(false);
  const [editPermissions, setEditPermissions] = useState({ local_analysis: true, cloud_transfer: false, write_access: false, excluded_extensions: "", allowed_extensions: "", excluded_patterns: "" });
  const [writeDirectoryId, setWriteDirectoryId] = useState<number | null>(null);
  const [writePath, setWritePath] = useState("");
  const [writeContent, setWriteContent] = useState("");
  const [cloudDirectoryId, setCloudDirectoryId] = useState<number | null>(null);
  const [cloudPath, setCloudPath] = useState("");
  const [cloudPrompt, setCloudPrompt] = useState("");
  const [cloudPreview, setCloudPreview] = useState<Record<string, unknown> | null>(null);
  const [cloudResult, setCloudResult] = useState<Record<string, unknown> | null>(null);
  const [webUrl, setWebUrl] = useState("");
  const [webResource, setWebResource] = useState<import("./types").WebImportResponse | null>(null);
  const [webPreview, setWebPreview] = useState<import("./types").WebImportConfirmResponse | null>(null);
  const [busyAction, setBusyAction] = useState("");
  const changeAlertIdsRef = useRef<Set<number> | null>(null);

  const load = async () => {
    try {
      const nextDirectories = await api.authorizedDirectories();
      setDirectories(nextDirectories);
      const entries = await Promise.all(nextDirectories.map(async item => {
        const [directoryChanges, jobs] = await Promise.all([api.directoryChanges(item.id), api.scanJobs(item.id)]);
        return [item.id, directoryChanges, jobs] as const;
      }));
      const nextChanges = Object.fromEntries(entries.map(([id, directoryChanges]) => [id, directoryChanges]));
      const pendingAlerts = entries.flatMap(([, directoryChanges]) => directoryChanges);
      const previousIds = changeAlertIdsRef.current;
      const newAlerts = previousIds
        ? pendingAlerts.filter(alert => !previousIds.has(alert.id))
        : [];
      changeAlertIdsRef.current = new Set(pendingAlerts.map(alert => alert.id));
      if (newAlerts.length && typeof window !== "undefined" && "Notification" in window && window.Notification.permission === "granted" && window.localStorage.getItem("learning-workstation.desktop-notifications") === "enabled") {
        const details = newAlerts.slice(0, 3).map(alert => `${alert.change_type === "added" ? "新增" : alert.change_type === "deleted" ? "删除" : "修改"} ${alert.relative_path}`).join("；");
        new window.Notification("文件变化提醒", { body: details, tag: "learning-file-changes" });
      }
      setChanges(nextChanges);
      setScanJobs(Object.fromEntries(entries.map(([id, _directoryChanges, jobs]) => [id, jobs])));
    } catch (e) { onError(e instanceof Error ? e.message : "授权目录加载失败"); }
  };
  useEffect(() => { void load(); }, []);
  const extensionList = (value: string) => value.split(",").map(item => item.trim()).filter(Boolean);
  async function authorize() {
    try {
      await api.authorizeDirectory({ path, label, local_analysis: localAnalysis, cloud_transfer: cloudTransfer, write_access: writeAccess, excluded_extensions: extensionList(excludedExtensions), allowed_extensions: extensionList(allowedExtensions), excluded_patterns: extensionList(excludedPatterns) });
      setPath(""); setLabel(""); setExcludedExtensions(""); setAllowedExtensions(""); setExcludedPatterns(""); setLocalAnalysis(true); setCloudTransfer(false); setWriteAccess(false); await load(); onNotice("目录授权成功，权限已保存。");
    } catch (e) { onError(e instanceof Error ? e.message : "目录授权失败"); }
  }
  async function fetchWebPage() {
    if (!webUrl.trim()) return;
    setBusyAction("web-fetch");
    try {
      const resource = await api.importWeb(webUrl.trim());
      setWebResource(resource);
      setWebPreview(await api.webImportPreview(resource.resource_id));
      onNotice("网页已解析，请确认是否写入知识库。");
    } catch (e) { onError(e instanceof Error ? e.message : "网页解析失败"); }
    finally { setBusyAction(""); }
  }
  async function confirmWebPage() {
    if (!webResource) return;
    setBusyAction("web-confirm");
    try {
      const result = await api.confirmWebImport(webResource.resource_id);
      setWebPreview(null);
      setWebResource({ ...webResource, confirmed: true });
      onNotice(`网页导入完成：新增 ${result.created_topics ?? 0} 个主题，${result.created_notes ?? 0} 篇来源笔记。`);
    } catch (e) { onError(e instanceof Error ? e.message : "网页导入失败"); }
    finally { setBusyAction(""); }
  }
  async function updatePermissions(id: number) {
    try { await api.directoryPermissions(id, { local_analysis: editPermissions.local_analysis, cloud_transfer: editPermissions.cloud_transfer, write_access: editPermissions.write_access, excluded_extensions: extensionList(editPermissions.excluded_extensions), allowed_extensions: extensionList(editPermissions.allowed_extensions), excluded_patterns: extensionList(editPermissions.excluded_patterns) }); setEditingId(null); await load(); onNotice("目录权限已更新。"); }
    catch (e) { onError(e instanceof Error ? e.message : "目录权限更新失败"); }
  }
  async function toggleScan(id: number, enabled: boolean) {
    try { await api.directoryScanSettings(id, enabled); await load(); onNotice(enabled ? "目录扫描已启用。" : "目录扫描已停用。"); }
    catch (e) { onError(e instanceof Error ? e.message : "扫描设置更新失败"); }
  }
  async function acknowledgeChanges(id: number) {
    try { await api.acknowledgeDirectoryChanges(id); await load(); onNotice("文件变化提醒已标记为已读。"); }
    catch (e) { onError(e instanceof Error ? e.message : "变化提醒更新失败"); }
  }
  function updateScanJob(job: ScanJob) {
    setScanJobs(current => {
      const jobs = [...(current[job.directory_id] ?? [])];
      const index = jobs.findIndex(item => item.job_id === job.job_id);
      if (index >= 0) jobs[index] = job;
      else jobs.unshift(job);
      return { ...current, [job.directory_id]: jobs.sort((left, right) => String(right.created_at ?? "").localeCompare(String(left.created_at ?? ""))) };
    });
  }
  async function waitForScanJob(directoryId: number, initial: ScanJob): Promise<ScanJob> {
    let current = initial;
    updateScanJob(current);
    while (current.status === "queued" || current.status === "running") {
      await new Promise(resolve => window.setTimeout(resolve, 300));
      current = await api.scanJob(directoryId, current.job_id);
      updateScanJob(current);
    }
    return current;
  }
  async function finishScanJob(directoryId: number, current: ScanJob) {
    if (current.status === "failed") throw new Error(String(current.error ?? "后台扫描失败"));
    if (current.status === "cancelled") { onNotice("扫描已取消。"); return; }
    const nextReport = (current.result ?? {}) as Record<string, unknown>;
    setReport(nextReport);
    const importId = typeof nextReport.import_id === "number" ? nextReport.import_id : null;
    setLatestImportId(importId);
    setImportPreview(importId ? await api.importPreview(importId) : null);
    await load();
    onNotice("扫描完成，已生成导入预览。");
  }
  async function scan(id: number) {
    try {
      await finishScanJob(id, await waitForScanJob(id, await api.startScanJob(id)));
    } catch (e) { onError(e instanceof Error ? e.message : "扫描失败"); }
  }
  async function cancelScan(directoryId: number, jobId: string) {
    try { updateScanJob(await api.cancelScanJob(directoryId, jobId)); onNotice("扫描任务已取消。"); }
    catch (e) { onError(e instanceof Error ? e.message : "取消扫描失败"); }
  }
  async function retryScan(directoryId: number, jobId: string) {
    try { await finishScanJob(directoryId, await waitForScanJob(directoryId, await api.retryScanJob(directoryId, jobId))); }
    catch (e) { onError(e instanceof Error ? e.message : "重试扫描失败"); }
  }
  async function confirmLatestImport() {
    if (!latestImportId) return;
    setImporting(true);
    try {
      const result = await api.confirmImport(latestImportId, { generate_tasks: generateTasks, generate_reviews: generateReviews });
      setImportPreview(result);
      await load();
      onNotice(`导入完成：新增 ${result.created_topics ?? 0} 个主题，${result.created_notes ?? 0} 篇来源笔记。`);
    } catch (e) { onError(e instanceof Error ? e.message : "确认导入失败"); }
    finally { setImporting(false); }
  }
  async function search() { try { setMatches((await api.searchImportedContent(query)).matches); } catch (e) { onError(e instanceof Error ? e.message : "内容搜索失败"); } }
  async function revoke(id: number) { try { await api.revokeDirectory(id); await load(); onNotice("目录授权已撤销。"); } catch (e) { onError(e instanceof Error ? e.message : "撤销失败"); } }
  async function writeFile() {
    if (!writeDirectoryId || !writePath.trim()) return;
    setBusyAction("write");
    try { const preview = await api.writeDirectoryFile(writeDirectoryId, writePath.trim(), writeContent, false); if (!window.confirm(`${preview.will_overwrite ? "将覆盖已有文件" : "将创建新文件"}：${String(preview.path ?? writePath)}，确认写入？`)) return; const result = await api.writeDirectoryFile(writeDirectoryId, writePath.trim(), writeContent, true); setWriteDirectoryId(null); setWritePath(""); setWriteContent(""); await load(); onNotice(`文件已写入授权目录，批次 ${String(result.batch_id ?? "已记录")} 可撤销。`); }
    catch (e) { onError(e instanceof Error ? e.message : "文件写入失败"); }
    finally { setBusyAction(""); }
  }
  async function previewCloudAnalysis() {
    if (!cloudDirectoryId || !cloudPath.trim() || !cloudPrompt.trim()) return;
    setBusyAction("cloud-preview");
    try { setCloudResult(null); setCloudPreview(await api.cloudAnalyzeDirectoryFile(cloudDirectoryId, cloudPath.trim(), cloudPrompt.trim(), false)); }
    catch (e) { onError(e instanceof Error ? e.message : "云端分析预览失败"); }
    finally { setBusyAction(""); }
  }
  async function confirmCloudAnalysis() {
    if (!cloudDirectoryId || !cloudPath.trim() || !cloudPrompt.trim()) return;
    setBusyAction("cloud-confirm");
    try { setCloudResult(await api.cloudAnalyzeDirectoryFile(cloudDirectoryId, cloudPath.trim(), cloudPrompt.trim(), true)); setCloudPreview(null); onNotice("云端分析已执行，返回内容仅在当前页面展示。"); }
    catch (e) { onError(e instanceof Error ? e.message : "云端分析失败"); }
    finally { setBusyAction(""); }
  }
  return <div className="imports-workspace">
    <section className="import-source-section sf-open-section">
      <div className="sf-surface-header"><div><h2 className="sf-section-title">目录与来源</h2><p className="sf-surface-description">授权目录 · 正文索引 · 权限可审计</p></div><span className="sf-surface-metadata">本地优先</span></div>
      <div className="stack-form import-directory-form sf-utility-surface"><input aria-label="授权目录路径" value={path} onChange={e => setPath(e.target.value)} placeholder="绝对路径，例如 C:\\Users\\..." /><input aria-label="授权目录标签" value={label} onChange={e => setLabel(e.target.value)} placeholder="目录标签（可选）" /><input aria-label="允许扩展名" value={allowedExtensions} onChange={e => setAllowedExtensions(e.target.value)} placeholder="允许扩展名，留空使用默认白名单，例如 .md,.py" /><input aria-label="排除扩展名" value={excludedExtensions} onChange={e => setExcludedExtensions(e.target.value)} placeholder="排除扩展名，例如 .pdf,.zip" /><input aria-label="排除目录或路径模式" value={excludedPatterns} onChange={e => setExcludedPatterns(e.target.value)} placeholder="排除模式，例如 drafts, archive/**" /><label><input aria-label="允许本地分析" type="checkbox" checked={localAnalysis} onChange={e => setLocalAnalysis(e.target.checked)} />允许本地分析</label><label><input aria-label="允许云端发送" type="checkbox" checked={cloudTransfer} onChange={e => setCloudTransfer(e.target.checked)} />允许云端发送（默认关闭）</label><label><input aria-label="允许写入目录" type="checkbox" checked={writeAccess} onChange={e => setWriteAccess(e.target.checked)} />允许写入目录（默认关闭）</label><button className="primary-button" onClick={() => void authorize()} disabled={!path.trim()}>授权目录</button></div>
    </section>
    <section className="web-import-panel sf-open-section">
      <div className="sf-surface-header"><div><h3 className="sf-section-title">网页资料</h3><p className="sf-surface-description">解析后的正文先保存在本地，确认后才创建主题和来源笔记。</p></div><span className="sf-surface-metadata">公网 URL</span></div>
      <div className="inline-form web-import-form"><input aria-label="网页资料地址" value={webUrl} onChange={e => setWebUrl(e.target.value)} placeholder="https://example.com/lesson" /><button className="primary-button" onClick={() => void fetchWebPage()} disabled={busyAction === "web-fetch" || !webUrl.trim()}>{busyAction === "web-fetch" ? "解析中" : "解析网页"}</button></div>
      {webResource && <div className="import-web-preview sf-utility-surface"><strong>{webResource.title || webResource.final_url}</strong><small>{webResource.final_url} · {webResource.content_status} · {webResource.content_length} 字符</small>{webResource.warning && <p className="sf-notice-surface sf-notice-surface--warning">{webResource.warning}</p>}{webResource.confirmed && !webResource.warning && <p className="sf-notice-surface sf-notice-surface--success">已确认导入知识库。</p>}{webPreview?.preview?.[0] && <><small>建议主题：{webPreview.preview[0].suggested_topics.join("、") || "未提取到主题"}</small><div><button className="primary-button" onClick={() => void confirmWebPage()} disabled={busyAction === "web-confirm" || webResource.confirmed}>{busyAction === "web-confirm" ? "导入中" : webResource.confirmed ? "已导入" : "确认并写入知识库"}</button></div></>}</div>}
    </section>
    {Object.values(scanJobs).flat().length ? <section className="scan-job-panel sf-open-section"><div className="sf-surface-header"><div><h3 className="sf-section-title">扫描任务</h3><p className="sf-surface-description">后台任务会在服务重启后自动恢复。</p></div><span className="sf-surface-metadata">{Object.values(scanJobs).flat().length} 条</span></div>{Object.values(scanJobs).flat().map(job => <div className="scan-job-row" key={job.job_id}><div><strong>{directories.find(item => item.id === job.directory_id)?.label || directories.find(item => item.id === job.directory_id)?.path || `目录 #${job.directory_id}`}</strong><small>{job.status === "queued" ? "排队中" : job.status === "running" ? "扫描中" : job.status === "completed" ? "已完成" : job.status === "failed" ? "失败" : job.status === "cancelled" ? "已取消" : job.status} · 进度 {job.progress}% · 尝试 {job.attempts ?? 0}/{job.max_attempts ?? 3}</small>{job.error && <small className="error-text">{job.error}</small>}</div><div className="scan-job-actions"><div className="scan-progress" role="progressbar" aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }} /></div>{(job.status === "queued" || job.status === "running") && <button className="ghost-button" onClick={() => void cancelScan(job.directory_id, job.job_id)}>取消</button>}{(job.status === "failed" || job.status === "cancelled") && <button className="ghost-button" onClick={() => void retryScan(job.directory_id, job.job_id)} disabled={(job.attempts ?? 0) >= (job.max_attempts ?? 3)}>重试</button>}</div></div>)}</section> : null}
    {report && <section className="import-confirmation sf-utility-surface">
      <div className="import-review-header sf-surface-header"><div><h3 className="sf-surface-title">导入确认预览</h3><p className="sf-surface-description">确认后会创建知识主题，并把可读取正文保存为来源笔记。</p><div className="import-options"><label><input aria-label="为导入主题生成学习任务" type="checkbox" checked={generateTasks} onChange={e => setGenerateTasks(e.target.checked)} />为导入主题生成学习任务</label><label><input aria-label="为导入主题生成首次复习" type="checkbox" checked={generateReviews} onChange={e => setGenerateReviews(e.target.checked)} />为导入主题生成首次复习</label></div></div><button className="primary-button" onClick={() => void confirmLatestImport()} disabled={!latestImportId || importing || !importPreview?.preview?.length}>{importing ? "正在导入…" : "确认并写入知识库"}</button></div>
      {importPreview?.preview?.map(item => <article className="import-preview-row" key={item.imported_file_id}><div><strong>{item.relative_path}</strong><small>{item.will_create_note ? "将创建来源笔记" : "仅保存文件索引"} · {item.already_confirmed ? "已确认" : "待确认"}</small></div><p>{item.suggested_topics.join("、") || "未提取到主题"}</p></article>)}
      {importPreview?.executed && <p className="import-result sf-notice-surface sf-notice-surface--success">已处理 {importPreview.confirmed_files ?? 0} 个文件，复用 {importPreview.reused_files ?? 0} 个文件；新增任务 {importPreview.created_tasks ?? 0} 项，新增复习 {importPreview.created_reviews ?? 0} 项。</p>}
    </section>}
    <section className="import-search-section sf-open-section"><div className="sf-surface-header"><h2 className="sf-section-title">正文搜索</h2></div><form className="inline-form import-search-form" onSubmit={event => { event.preventDefault(); void search(); }}><input aria-label="导入正文搜索" value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索已导入的 Markdown/TXT/代码正文…" /><button className="primary-button" disabled={!query.trim()}>搜索</button></form>{matches.map(match => <article className="import-match" key={match.indexed_file_id}><strong>{match.relative_path}</strong><pre>{match.snippet}</pre></article>)}</section>
  </div>;
}
