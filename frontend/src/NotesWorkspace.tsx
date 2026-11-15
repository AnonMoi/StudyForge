import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, downloadJson } from "./api";
import type { KnowledgeTopic, Note, NoteAgentReview, Project, Task } from "./types";
import MarkdownRenderer from "./MarkdownRenderer";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

const NOTE_FIELD_NAMES: Record<string, string> = {
  title: "标题",
  content: "正文",
  tags: "标签",
  folder: "分类",
  linked_topic_ids: "关联知识",
  linked_task_ids: "关联任务",
  linked_project_ids: "关联项目",
};

function visibleFolder(folder: string) {
  return folder === "Inbox" ? "收集箱" : folder;
}

function storedFolder(folder: string) {
  return folder.trim() === "收集箱" ? "Inbox" : folder;
}

export default function NotesWorkspace({ onNotice, onError }: Props) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");
  const [folder, setFolder] = useState("收集箱");
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const [versions, setVersions] = useState<import("./types").NoteVersion[]>([]);
  const [diff, setDiff] = useState<import("./types").NoteVersionDiff | null>(null);
  const [blogDrafts, setBlogDrafts] = useState<import("./types").BlogDraft[]>([]);
  const [blogPreview, setBlogPreview] = useState<import("./types").BlogDraftGenerateResponse["preview"] | null>(null);
  const [blogBusy, setBlogBusy] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [topics, setTopics] = useState<KnowledgeTopic[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [agentReview, setAgentReview] = useState<NoteAgentReview | null>(null);
  const [agentBusy, setAgentBusy] = useState(false);
  const [qualitySummary, setQualitySummary] = useState<{ reviewed_notes: number; unreviewed_notes: number; average_quality_score: number | null } | null>(null);
  const selected = notes.find((note) => note.id === selectedId) ?? null;

  async function loadNotes() {
    try {
      const [loaded, taskData, topicData, projectData, quality] = await Promise.all([api.notes(), api.tasks(), api.topics(), api.projects(), api.noteQualitySummary()]);
      setNotes(loaded);
      setTasks(taskData); setTopics(topicData); setProjects(projectData); setQualitySummary(quality);
      if (selectedId !== null && !loaded.some((note) => note.id === selectedId)) setSelectedId(null);
    } catch (err) {
      onError(err instanceof Error ? err.message : "笔记加载失败");
    }
  }
  useEffect(() => { void loadNotes(); }, []);

  const filteredNotes = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return notes;
    return notes.filter((note) => `${note.title} ${note.content} ${note.tags.join(" ")}`.toLowerCase().includes(normalized));
  }, [notes, query]);

  function selectNote(note: Note) {
    setSelectedId(note.id);
    setTitle(note.title);
    setContent(note.content);
    setTags(note.tags.join(", "));
    setFolder(visibleFolder(note.folder ?? "Inbox"));
    void api.noteVersions(note.id).then(setVersions).catch(() => setVersions([]));
    void api.blogDrafts(note.id).then(setBlogDrafts).catch(() => setBlogDrafts([]));
    setBlogPreview(null);
    setAgentReview(null);
  }
  async function analyzeNote() {
    if (!selected) return;
    setAgentBusy(true);
    try { const response = await api.analyzeNote(selected.id); setAgentReview(response.review); onNotice("整理建议已经准备好，确认后再应用到笔记。"); }
    catch (err) { onError(err instanceof Error ? err.message : "暂时没能整理这篇笔记"); }
    finally { setAgentBusy(false); }
  }
  async function confirmAgentReview(apply_fields: string[]) {
    if (!selected) return;
    setAgentBusy(true);
    try { const response = await api.analyzeNote(selected.id, true, apply_fields); if (response.note) { setNotes(current => current.map(note => note.id === response.note!.id ? response.note! : note)); selectNote(response.note); } setAgentReview(null); await loadNotes(); onNotice(apply_fields.length ? "摘要和标签已经更新到笔记。" : "检查结果已保存，笔记内容没有改动。"); }
    catch (err) { onError(err instanceof Error ? err.message : "整理结果没有保存成功"); }
    finally { setAgentBusy(false); }
  }

  async function restoreVersion(versionNumber: number, fields?: string[]) {
    if (!selected) return;
    try {
      const restored = await api.restoreNoteVersion(selected.id, versionNumber, fields);
      setNotes((current) => current.map((note) => note.id === restored.id ? restored : note));
      selectNote(restored);
      onNotice(`已恢复到版本 ${versionNumber}。`);
    } catch (err) {
      onError(err instanceof Error ? err.message : "版本恢复失败");
    }
  }
  async function compareVersion(versionNumber: number) {
    if (!selected || !versions[0] || versions[0].version_number === versionNumber) return;
    try { setDiff(await api.noteVersionDiff(selected.id, versionNumber, versions[0].version_number)); }
    catch (err) { onError(err instanceof Error ? err.message : "版本比较失败"); }
  }

  function newNote() {
    setSelectedId(null);
    setTitle("");
    setContent("");
    setTags("");
    setFolder("收集箱");
    setVersions([]);
    setBlogDrafts([]);
    setBlogPreview(null);
  }
  async function generateBlogDraft() {
    if (!selected) return;
    setBlogBusy(true);
    try {
      const response = await api.generateBlogDraft(selected.id);
      setBlogPreview(response.preview ?? null);
      onNotice("博客草稿已经准备好，确认后会另存一份。");
    } catch (err) { onError(err instanceof Error ? err.message : "暂时没能整理成博客草稿"); }
    finally { setBlogBusy(false); }
  }
  async function confirmBlogDraft() {
    if (!selected) return;
    setBlogBusy(true);
    try {
      const response = await api.generateBlogDraft(selected.id, true);
      if (response.draft) setBlogDrafts(current => [response.draft!, ...current]);
      setBlogPreview(null);
      onNotice("博客草稿已另存，原笔记没有改动。");
    } catch (err) { onError(err instanceof Error ? err.message : "博客草稿没有保存成功"); }
    finally { setBlogBusy(false); }
  }
  async function exportBlogDraft(draftId: number, format: "md" | "txt" | "html") {
    try {
      const blob = await api.blogDraftExportBlob(draftId, format);
      const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `blog-draft-${draftId}.${format}`; anchor.click(); URL.revokeObjectURL(url);
      onNotice(`博客草稿已导出为 ${format.toUpperCase()}。`);
    } catch (err) { onError(err instanceof Error ? err.message : "博客草稿导出失败"); }
  }
  async function saveNote(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    try {
      const saved = selected
        ? await api.updateNote(selected.id, { title: title.trim(), content, tags: tags.split(",").map(item => item.trim()).filter(Boolean), folder: storedFolder(folder), linked_topic_ids: selected.linked_topic_ids, linked_task_ids: selected.linked_task_ids, linked_project_ids: selected.linked_project_ids })
        : await api.createNote({ title: title.trim(), content, tags: tags.split(",").map(item => item.trim()).filter(Boolean), folder: storedFolder(folder) });
      setNotes((current) => selected ? current.map((note) => note.id === saved.id ? saved : note) : [saved, ...current]);
      setSelectedId(saved.id);
      onNotice(selected ? "笔记已更新。" : "笔记已保存到本地。");
    } catch (err) {
      onError(err instanceof Error ? err.message : "笔记保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="notes-layout notes-workspace">
      <div className="notes-list-panel sf-open-section">
        <div className="sf-surface-header"><div><h2 className="sf-section-title">我的笔记</h2><p className="sf-surface-description">找回以前写过的内容，或者从一张空白页开始。</p></div><span className="sf-surface-metadata">{notes.length} 篇</span></div>
        {qualitySummary && <small className="notes-review-summary">{qualitySummary.reviewed_notes} 篇检查过 · {qualitySummary.unreviewed_notes} 篇还没检查</small>}
        <div className="notes-toolbar">
          <input className="sf-field" aria-label="搜索笔记" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题、内容或标签…" />
          <button type="button" className="secondary-button" onClick={newNote}>写新笔记</button>
        </div>
        <div className="note-list">
          {filteredNotes.length ? filteredNotes.map((note) => (
            <button type="button" className={`note-list-item ${note.id === selectedId ? "selected" : ""}`} key={note.id} onClick={() => selectNote(note)}>
              <span className="note-list-title"><strong>{note.title}</strong><small>{visibleFolder(note.folder ?? "Inbox")}</small></span>
              <span className="note-list-excerpt">{note.content.slice(0, 88) || "这篇笔记还没有正文。"}</span>
              <span className="note-list-meta"><span>{note.tags.length ? note.tags.join(" · ") : "还没有标签"}</span><small>{note.ai_review_status === "reviewed" ? "已检查" : "还没检查"}</small></span>
            </button>
          )) : <Empty text={notes.length ? "没有找到相符的笔记，换个关键词试试。" : "这里还没有笔记。先写下最近学会的一件事吧。"} />}
        </div>
      </div>
      <div className="note-editor-panel sf-open-section">
        <div className="sf-surface-header"><div><h2 className="sf-section-title">{selected ? "继续写这篇笔记" : "写一篇新笔记"}</h2><p className="sf-surface-description">先把自己的理解写清楚，整理和派生工具随时可以用。</p></div><span className="sf-surface-metadata">{selected ? "正在编辑" : "空白页"}</span></div>
        <form onSubmit={saveNote}>
          <label className="field-label note-title-field">标题<input className="sf-field" aria-label="笔记标题" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：窗口函数容易写错的三个地方" /></label>
          <div className="note-meta-fields"><label className="field-label">放在哪里<input className="sf-field" aria-label="笔记文件夹" value={folder} onChange={(event) => setFolder(event.target.value)} placeholder="例如：收集箱、SQL、课程项目" /></label><label className="field-label">标签<input className="sf-field" aria-label="笔记标签" value={tags} onChange={(event) => setTags(event.target.value)} placeholder="用逗号分开，例如 SQL, 数据库" /></label></div>
          {selected && <div className="note-utility-bar"><span>把这篇笔记继续用起来</span><div className="button-row"><button type="button" className="ghost-button" onClick={() => downloadJson(`${selected.title || "note"}.json`, selected)}>下载备份</button><button type="button" className="ghost-button" onClick={() => void analyzeNote()} disabled={agentBusy}>{agentBusy ? "正在整理…" : "看看整理建议"}</button><button type="button" className="ghost-button" onClick={() => void (async () => { try { const cardPreview = await api.generateReviewCards(selected.id, false); if (cardPreview.reused) { onNotice("这篇笔记已经做过复习卡片，可以直接去复习。"); return; } if (!window.confirm(`这篇笔记可以做成 ${cardPreview.preview.length} 张复习卡片，要加入复习区吗？`)) return; const result = await api.generateReviewCards(selected.id, true); onNotice(`${result.cards.length} 张复习卡片已经加入复习区。`); } catch (error) { onError(error instanceof Error ? error.message : "复习卡片没有生成成功"); } })()}>做成复习卡片</button><button type="button" className="ghost-button" onClick={() => void generateBlogDraft()} disabled={blogBusy}>{blogBusy ? "正在整理…" : "写成博客草稿"}</button></div></div>}
          {selected && <details className="note-connections"><summary>关联学习内容</summary><p>需要时再把笔记和知识、任务或项目连起来。按住 Ctrl 可以选择多项。</p><div className="note-links-grid"><label>知识主题<select className="sf-field" aria-label="关联知识主题" multiple value={selected.linked_topic_ids.map(String)} onChange={event => { const ids = Array.from(event.target.selectedOptions).map(option => Number(option.value)); setNotes(current => current.map(note => note.id === selected.id ? { ...note, linked_topic_ids: ids } : note)); }}><option value="">请选择主题</option>{topics.map(topic => <option key={topic.id} value={topic.id}>{topic.name}</option>)}</select></label><label>学习任务<select className="sf-field" aria-label="关联任务" multiple value={selected.linked_task_ids.map(String)} onChange={event => { const ids = Array.from(event.target.selectedOptions).map(option => Number(option.value)); setNotes(current => current.map(note => note.id === selected.id ? { ...note, linked_task_ids: ids } : note)); }}><option value="">请选择任务</option>{tasks.map(task => <option key={task.id} value={task.id}>{task.title}</option>)}</select></label><label>项目<select className="sf-field" aria-label="关联项目" multiple value={selected.linked_project_ids.map(String)} onChange={event => { const ids = Array.from(event.target.selectedOptions).map(option => Number(option.value)); setNotes(current => current.map(note => note.id === selected.id ? { ...note, linked_project_ids: ids } : note)); }}><option value="">请选择项目</option>{projects.map(project => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label></div></details>}
          <label className="note-body-field"><span>正文</span>{!preview ? <textarea className="sf-field" aria-label="笔记内容" value={content} onChange={(event) => setContent(event.target.value)} placeholder="先写你真正弄懂了什么，再记例子、代码和还没解决的问题。支持 Markdown。" rows={15} /> : <MarkdownRenderer content={content} />}</label>
          <div className="form-footer"><span>保存在本机 · {selected ? `${versions.length} 次修改记录` : "保存后会留下修改记录"}</span><button type="button" className="ghost-button" onClick={() => setPreview(value => !value)}>{preview ? "编辑" : "预览"}</button><button className="primary-button" disabled={saving || !title.trim()}>{saving ? "保存中…" : selected ? "保存修改" : "保存笔记"}</button></div>
          {agentReview && <div className="note-agent-review sf-utility-surface"><div className="note-review-heading"><div><strong>可以怎么整理</strong><p>这只是辅助建议，应用前先看看是否符合你的原意。</p></div><span>仅供参考</span></div><p className="note-review-summary">{agentReview.summary || "暂时没有合适的摘要建议。"}</p><p><strong>可以补充的标签：</strong>{agentReview.suggested_tags.join("、") || "暂时没有"}</p>{agentReview.technical_issues.length > 0 && <p><strong>建议核对：</strong>{agentReview.technical_issues.join("；")}</p>}{agentReview.missing_prerequisites.length > 0 && <p><strong>可能还要补充：</strong>{agentReview.missing_prerequisites.join("、")}</p>}{agentReview.review_questions.length > 0 && <div className="note-review-questions"><strong>回看时可以问自己</strong><ul>{agentReview.review_questions.map(question => <li key={question}>{question}</li>)}</ul></div>}<div className="button-row"><button type="button" className="primary-button" onClick={() => void confirmAgentReview(["summary", "tags"])} disabled={agentBusy}>采用摘要和标签</button><button type="button" className="ghost-button" onClick={() => void confirmAgentReview([])} disabled={agentBusy}>只保存检查结果</button><button type="button" className="ghost-button" onClick={() => setAgentReview(null)}>先不用</button></div></div>}
          {blogPreview && <div className="version-list blog-draft-preview"><strong>准备保存的博客草稿</strong><small>{blogPreview.warning}</small><MarkdownRenderer content={blogPreview.content} /><div className="form-footer"><button type="button" className="ghost-button" onClick={() => setBlogPreview(null)}>先不保存</button><button type="button" className="primary-button" onClick={() => void confirmBlogDraft()} disabled={blogBusy}>{blogBusy ? "保存中…" : "另存为博客草稿"}</button></div></div>}
          {selected && versions.length > 0 && <details className="note-history"><summary>修改记录 · {versions.length}</summary><div className="version-list">{versions.map((version) => <div className="version-row" key={version.id}><span>第 {version.version_number} 版 · {new Date(version.created_at).toLocaleString()}</span><div className="button-row"><button type="button" className="ghost-button" onClick={() => void compareVersion(version.version_number)}>看看变化</button><button type="button" className="ghost-button" onClick={() => void restoreVersion(version.version_number)}>恢复这一版</button><button type="button" className="ghost-button" onClick={() => void restoreVersion(version.version_number, ["content"])}>只恢复正文</button></div></div>)}</div></details>}
          {blogDrafts.length > 0 && <details className="note-history"><summary>另存的博客草稿 · {blogDrafts.length}</summary><div className="version-list">{blogDrafts.map((draft) => <div className="version-row" key={draft.id}><span>{draft.title} · {new Date(draft.created_at).toLocaleString()}</span><div className="button-row"><button type="button" className="ghost-button" onClick={() => void exportBlogDraft(draft.id, "md")}>Markdown</button><button type="button" className="ghost-button" onClick={() => void exportBlogDraft(draft.id, "html")}>网页</button><button type="button" className="ghost-button" onClick={() => void exportBlogDraft(draft.id, "txt")}>纯文本</button></div></div>)}</div></details>}
          {diff && <div className="version-list note-version-diff"><strong>第 {diff.from_version} 版与第 {diff.to_version} 版的变化</strong>{Object.entries(diff.fields).length ? Object.entries(diff.fields).map(([field, value]) => <div className="version-row" key={field}><span>{NOTE_FIELD_NAMES[field] ?? field}</span><small>{String(value.before).slice(0, 160)} → {String(value.after).slice(0, 160)}</small></div>) : <small>这两个版本没有其它字段变化。</small>}{diff.content_diff.hunks.length > 0 && <div className="line-diff" aria-label="笔记正文行级差异"><div className="line-diff-header"><span>正文变化</span><small>第 {diff.from_version} 版 · {diff.content_diff.before_line_count} 行 → 第 {diff.to_version} 版 · {diff.content_diff.after_line_count} 行</small></div>{diff.content_diff.hunks.map((hunk, index) => <div className="diff-hunk" key={`${hunk.kind}-${hunk.before_start}-${hunk.after_start}-${index}`}><div className="diff-pane diff-before"><small>原来 · 第 {hunk.before_start} 行</small>{hunk.before_lines.length ? hunk.before_lines.map((line, lineIndex) => <div className="diff-line removed" key={`before-${lineIndex}`}>− {line || " "}</div>) : <div className="diff-line empty">（没有内容）</div>}</div><div className="diff-pane diff-after"><small>后来 · 第 {hunk.after_start} 行</small>{hunk.after_lines.length ? hunk.after_lines.map((line, lineIndex) => <div className="diff-line added" key={`after-${lineIndex}`}>＋ {line || " "}</div>) : <div className="diff-line empty">（没有内容）</div>}</div></div>)}</div>}{diff.content_diff.hunks.length === 0 && <small>正文没有逐行变化。</small>}</div>}
        </form>
      </div>
    </section>
  );
}
function Empty({ text }: { text: string }) { return <div className="empty"><p>{text}</p></div>; }
