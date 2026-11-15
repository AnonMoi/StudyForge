import { FormEvent, useEffect, useState } from "react";
import { api, getApiErrorMessage } from "./api";
import type { JobAnalysis, JobAnalysisResult } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

function learningStage(level: number) {
  if (level >= 7) return "已经能独立运用";
  if (level >= 5) return "能在任务中使用";
  if (level >= 3) return "正在形成稳定理解";
  if (level > 0) return "刚开始积累";
  return "还没有留下验证记录";
}

function projectStatus(status: string) {
  return ({ active: "正在进行", in_progress: "正在进行", completed: "已经完成", paused: "暂时停下", planned: "准备开始", archived: "已经收起" } as Record<string, string>)[status] ?? "已经记录";
}

function shortDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "日期未知" : date.toLocaleDateString("zh-CN", { year: "numeric", month: "short", day: "numeric" });
}

function AnalysisResult({ analysis }: { analysis: JobAnalysisResult }) {
  const evidenceCount = analysis.matched_topics.length + analysis.matched_capabilities.length + analysis.project_evidence.length;
  const otherRecommendations = analysis.recommendations.filter(item => !analysis.gaps.some(gap => item.includes(`“${gap}”`)));
  return <div className="job-readiness-result">
    <div className="job-readiness-summary">
      <h3>{analysis.extracted_skills.length ? `这份岗位明确写了 ${analysis.extracted_skills.length} 项能力要求` : "这份描述里还没有足够明确的技能要求"}</h3>
      <p>{analysis.extracted_skills.length ? evidenceCount ? `在现有学习记录里找到了 ${evidenceCount} 处相关依据；没有依据的部分会单独列出来。` : "现有学习记录里还没有找到直接相关的依据，可以先从最具体的一项要求开始准备。" : "可以补上技术栈、工作内容或任职要求，再重新对照一次。"}</p>
    </div>

    <section className="job-readiness-section" aria-labelledby="job-requirements-title">
      <div className="job-readiness-section-heading"><h4 id="job-requirements-title">岗位说明里真正写了什么</h4><p>这里只列出原文中能够明确识别的技能，不补写招聘方没有说过的要求。</p></div>
      {analysis.extracted_skills.length ? <ul className="job-requirement-list">{analysis.extracted_skills.map(skill => <li key={skill}>{skill}</li>)}</ul> : <p className="job-readiness-empty">暂时没有找到明确技能词，可以回到岗位说明补充更完整的职责和任职要求。</p>}
    </section>

    <section className="job-readiness-section" aria-labelledby="job-evidence-title">
      <div className="job-readiness-section-heading"><h4 id="job-evidence-title">我已经有哪些依据</h4><p>知识、能力和项目只在与岗位原文有交集时出现。</p></div>
      {evidenceCount ? <div className="job-evidence-list">
        {analysis.matched_topics.map(topic => <article className="job-evidence-row" key={`topic-${topic.id}`}><div><span>知识主题</span><strong>{topic.name}</strong></div><p>{learningStage(topic.verified_level)}；与岗位里的“{topic.matched_skills.join("、") || topic.name}”有关。</p></article>)}
        {analysis.matched_capabilities.map(capability => <article className="job-evidence-row" key={`capability-${capability.id}`}><div><span>能力记录</span><strong>{capability.name}</strong></div><p>{learningStage(capability.level)}；对应“{capability.matched_skills.join("、") || capability.name}”。</p></article>)}
        {analysis.project_evidence.map(project => <article className="job-evidence-row" key={`project-${project.id}`}><div><span>项目经历</span><strong>{project.title}</strong></div><p>{projectStatus(project.status)}；能说明“{project.matched_skills.join("、")}”{project.outcomes.length ? `，已有成果：${project.outcomes.join("、")}` : "，但还没有写下具体成果"}。</p></article>)}
      </div> : <p className="job-readiness-empty">现有知识、能力和项目记录里，还没有与这份岗位直接重合的内容。</p>}
    </section>

    <section className="job-readiness-section job-readiness-gaps" aria-labelledby="job-gaps-title">
      <div className="job-readiness-section-heading"><h4 id="job-gaps-title">还需要补什么</h4><p>“待补”表示目前没有找到可复核依据，不等于你一定不会。</p></div>
      {analysis.gaps.length ? <div className="job-gap-list">{analysis.gaps.map(gap => <article key={gap}><strong>{gap}</strong><p>{analysis.recommendations.find(item => item.includes(`“${gap}”`)) ?? `为“${gap}”留下一次练习、项目成果或技术说明。`}</p></article>)}</div> : <p className="job-readiness-empty">现有记录能覆盖这次识别到的要求。投递前仍要回到原岗位说明逐条确认。</p>}
    </section>

    {otherRecommendations.length ? <section className="job-readiness-section" aria-labelledby="job-next-title"><div className="job-readiness-section-heading"><h4 id="job-next-title">可以从这里开始</h4></div><ul className="job-next-list">{otherRecommendations.map(item => <li key={item}>{item}</li>)}</ul></section> : null}

    <details className="job-analysis-method"><summary>这份对照是怎么来的</summary><p>它只读取你粘贴的岗位说明，并与保存在本机的知识主题、能力记录和项目经历做关键词对照。结果可能漏掉同义表达，也不代表招聘方的判断。</p></details>
  </div>;
}

export default function JobAnalysisWorkspace({ onNotice, onError }: Props) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [preview, setPreview] = useState<JobAnalysisResult | null>(null);
  const [history, setHistory] = useState<JobAnalysis[]>([]);
  const [selected, setSelected] = useState<JobAnalysis | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [busyAction, setBusyAction] = useState<"preview" | "save" | "">("");

  async function load() {
    setLoadingHistory(true);
    try { setHistory(await api.jobAnalyses()); }
    catch (error) { onError(getApiErrorMessage(error)); }
    finally { setLoadingHistory(false); }
  }
  useEffect(() => { void load(); }, []);

  async function analyze(confirmed: boolean) {
    if (!title.trim() || description.trim().length < 20) return;
    setBusyAction(confirmed ? "save" : "preview");
    try {
      const result = await api.analyzeJob(title.trim(), description.trim(), confirmed);
      if (confirmed) {
        setPreview(null);
        setTitle("");
        setDescription("");
        await load();
        onNotice("这份岗位对照已经保存在本机，没有改动你的能力和项目记录。");
      } else {
        setSelected(null);
        setPreview(result.analysis);
      }
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusyAction(""); }
  }

  function submitPreview(event: FormEvent) {
    event.preventDefault();
    void analyze(false);
  }

  return <div className="job-analysis-workspace">
    <header className="job-analysis-heading">
      <div><h2>拿一份岗位说明，看看还差什么</h2><p>把招聘要求和自己真正做过的练习、项目、笔记放在一起对照。</p></div>
      <span>{history.length ? `已经保存 ${history.length} 份` : "还没有保存过"}</span>
    </header>

    <div className="job-readiness-desk">
      <main className="job-analysis-main">
        {selected ? <section className="job-saved-analysis">
          <div className="job-analysis-main-heading"><div><span>保存于 {shortDate(selected.created_at)}</span><h3>{selected.title}</h3><p>这是当时保存的对照结果，不会跟着后来的学习记录自动改变。</p></div><button className="ghost-button" type="button" onClick={() => setSelected(null)}>对照新岗位</button></div>
          <AnalysisResult analysis={selected} />
        </section> : <>
          <section className="job-analysis-editor">
            <div className="job-analysis-main-heading"><div><h3>把岗位说明贴在这里</h3><p>尽量保留职责、任职要求和技术栈，越完整越容易找到真实交集。</p></div></div>
            <p className="job-analysis-boundary"><strong>内容只交给本机。</strong>第一次只生成对照结果，由你确认后才会保存；不会自动改动你的能力记录、项目状态或学习计划。</p>
            <form className="job-analysis-form" onSubmit={submitPreview}>
              <label>岗位名称<input aria-label="岗位名称" maxLength={240} value={title} onChange={event => setTitle(event.target.value)} placeholder="例如：Python 后端实习生" /></label>
              <label>岗位说明<textarea aria-label="岗位说明" maxLength={30000} rows={10} value={description} onChange={event => setDescription(event.target.value)} placeholder="粘贴岗位职责、任职要求和技术栈……" /></label>
              <div className="job-analysis-form-footer"><span>{description.trim().length < 20 ? `还需要至少 ${20 - description.trim().length} 个字` : `已经写下 ${description.trim().length} 个字`}</span><button className="primary-button" type="submit" disabled={Boolean(busyAction) || !title.trim() || description.trim().length < 20}>{busyAction === "preview" ? "正在对照…" : "先看看这份岗位"}</button></div>
            </form>
          </section>

          {preview ? <section className="job-analysis-preview" aria-live="polite">
            <div className="job-analysis-main-heading"><div><span>还没有保存</span><h3>{preview.title}</h3><p>先检查要求和依据是否符合原岗位说明，再决定要不要留下这份对照。</p></div><button className="ghost-button" type="button" onClick={() => setPreview(null)} disabled={Boolean(busyAction)}>重新修改</button></div>
            <AnalysisResult analysis={preview} />
            <div className="job-analysis-confirm"><p><strong>保存的是这次对照快照。</strong>它不会把待补项自动加入计划，也不会改变已有能力记录。</p><button className="primary-button" type="button" disabled={Boolean(busyAction)} onClick={() => void analyze(true)}>{busyAction === "save" ? "正在保存…" : "留下这份对照"}</button></div>
          </section> : null}
        </>}
      </main>

      <aside className="job-analysis-archive" aria-label="保存过的岗位">
        <div><h3>保存过的岗位</h3><p>重新打开一份旧对照，看看当时有哪些依据和待补项。</p></div>
        {loadingHistory ? <p className="job-history-state" role="status">正在读取保存记录…</p> : history.length ? <div className="job-history-list">{history.map(item => <button className={`job-history-row ${selected?.id === item.id ? "selected" : ""}`} key={item.id} type="button" onClick={() => { setPreview(null); setSelected(selected?.id === item.id ? null : item); }}><strong>{item.title}</strong><span>{shortDate(item.created_at)}</span><small>{item.extracted_skills.length} 项明确要求 · {item.gaps.length} 项待补</small></button>)}</div> : <p className="job-history-state">保存第一份岗位对照后，会在这里留下记录。</p>}
      </aside>
    </div>
  </div>;
}
