import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { KnowledgeTopic, TeachingAttempt, TeachingRecommendations, TeachingSession } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };
type BusyAction = "create" | "generate" | "answer" | "evaluate" | null;

function sessionProgress(session: TeachingSession) {
  const latest = session.attempts[session.attempts.length - 1];
  if (!latest) return "还没开始练习";
  if (latest.evaluated_at) return "已经回看";
  if (latest.answered_at) return "等你对照";
  return "正在练习";
}

function answerSummary(attempt: TeachingAttempt) {
  if ((attempt.score ?? 0) >= 4) return "已经讲得比较完整";
  if (attempt.score === 3) return "主线说到了，还差几个关键点";
  return "先把定义和机制补齐";
}

function naturalError(errorType: string | null) {
  if (!errorType) return null;
  const labels: Record<string, string> = {
    未作答: "这次还没有留下回答",
    关键概念遗漏: "还有关键概念没说到",
    概念理解不足: "定义和机制还需要再理一遍",
  };
  return labels[errorType] ?? `有一处理解需要再确认：${errorType}`;
}

export default function TeachingWorkspace({ onNotice, onError }: Props) {
  const [sessions, setSessions] = useState<TeachingSession[]>([]);
  const [topics, setTopics] = useState<KnowledgeTopic[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [topicId, setTopicId] = useState("");
  const [explanation, setExplanation] = useState("");
  const [answer, setAnswer] = useState("");
  const [recommendations, setRecommendations] = useState<TeachingRecommendations | null>(null);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [loading, setLoading] = useState(true);

  const selected = useMemo(() => sessions.find(item => item.id === selectedId) ?? null, [sessions, selectedId]);
  const currentAttempt = selected?.attempts.find(item => !item.evaluated_at) ?? selected?.attempts[selected.attempts.length - 1] ?? null;

  async function load(showLoading = false) {
    if (showLoading) setLoading(true);
    try {
      const [sessionData, topicData] = await Promise.all([api.teachingSessions(), api.topics()]);
      setSessions(sessionData);
      setTopics(topicData);
      if (selectedId && sessionData.some(item => item.id === selectedId)) return;
      setSelectedId(sessionData[0]?.id ?? null);
    } catch (error) {
      onError(error instanceof Error ? error.message : "这页暂时没加载出来，请稍后再试。");
    } finally {
      if (showLoading) setLoading(false);
    }
  }

  useEffect(() => { void load(true); }, []);

  async function createSession() {
    if (!title.trim()) return;
    setBusy("create");
    try {
      const created = await api.createTeachingSession({ title: title.trim(), topic_id: topicId ? Number(topicId) : null, explanation: explanation.trim() });
      setTitle("");
      setTopicId("");
      setExplanation("");
      setSelectedId(created.id);
      await load();
      onNotice("这节自学课已经建好，可以开始准备讲解了。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "这节自学课没有建成功，请再试一次。");
    } finally {
      setBusy(null);
    }
  }

  async function generate() {
    if (!selected) return;
    setBusy("generate");
    try {
      await api.generateTeachingMaterial(selected.id);
      await load();
      onNotice("讲解和练习已经准备好，先读一遍再开始回答。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "讲解暂时没有准备好，请稍后再试。");
    } finally {
      setBusy(null);
    }
  }

  async function submitAnswer() {
    if (!selected || !currentAttempt || !answer.trim()) return;
    setBusy("answer");
    try {
      await api.answerTeachingAttempt(selected.id, currentAttempt.id, answer.trim());
      setAnswer("");
      await load();
      onNotice("回答已经留下，接下来看看哪里还没说清。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "回答没有保存下来，请再试一次。");
    } finally {
      setBusy(null);
    }
  }

  async function evaluate() {
    if (!selected || !currentAttempt) return;
    setBusy("evaluate");
    try {
      await api.evaluateTeachingAttempt(selected.id, currentAttempt.id);
      const data = await api.teachingRecommendations(selected.id);
      setRecommendations(data);
      await load();
      onNotice("已经对照完，可以从还没说清的地方继续练。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "这次没有对照成功，请稍后再试。");
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <div className="teaching-loading" role="status"><strong>正在打开自学课</strong><span>课程和练习马上就好。</span></div>;
  }

  const covered = currentAttempt?.evaluation_details.covered_rubric ?? [];
  const missing = currentAttempt?.evaluation_details.missing_rubric ?? [];
  const misconceptions = currentAttempt?.evaluation_details.misconceptions ?? [];
  const errorNote = naturalError(currentAttempt?.error_type ?? null);

  return <div className="teaching-workspace">
    <header className="teaching-page-heading">
      <div>
        <h2>把一个概念讲清楚</h2>
        <p>先读一遍，再用自己的话回答。最后只看哪里已经说到、哪里还需要补。</p>
      </div>
      <div className="teaching-overview" aria-label="自学课概况">
        <strong>{sessions.length ? `${sessions.length} 节自学课` : "还没有自学课"}</strong>
        <span>{selected ? `现在在看：${selected.title}` : "从一个最近想弄懂的问题开始"}</span>
      </div>
    </header>

    <div className="teaching-desk">
      <aside className="teaching-sidebar">
        <div className="teaching-sidebar-heading">
          <div><h3>我的自学课</h3><p>每节课只解决一个问题。</p></div>
          <span>{sessions.length} 节</span>
        </div>

        <form className="teaching-new-lesson" onSubmit={event => { event.preventDefault(); void createSession(); }}>
          <label>这次想弄懂什么
            <input aria-label="这次想弄懂什么" value={title} onChange={event => setTitle(event.target.value)} placeholder="例如：React 为什么会批量更新状态" />
          </label>
          <label>和哪个知识主题有关
            <select aria-label="和哪个知识主题有关" value={topicId} onChange={event => setTopicId(event.target.value)}>
              <option value="">暂时不关联</option>
              {topics.map(topic => <option key={topic.id} value={topic.id}>{topic.name}</option>)}
            </select>
          </label>
          <label>我现在卡在哪里
            <textarea aria-label="我现在卡在哪里" rows={3} value={explanation} onChange={event => setExplanation(event.target.value)} placeholder="可选。写下已经知道的，或最想解开的疑问。" />
          </label>
          <button className="primary-button" disabled={!title.trim() || busy !== null}>{busy === "create" ? "正在新建…" : "新建这节课"}</button>
        </form>

        {sessions.length > 0 ? <nav className="teaching-session-list" aria-label="我的自学课">
          {sessions.map(session => <button type="button" key={session.id} aria-current={selectedId === session.id ? "page" : undefined} className={`teaching-session-row ${selectedId === session.id ? "selected" : ""}`} onClick={() => { setSelectedId(session.id); setRecommendations(null); setAnswer(""); }}>
            <strong>{session.title}</strong>
            <small>{sessionProgress(session)} · {session.attempts.length ? `${session.attempts.length} 次练习` : "等待开始"}</small>
          </button>)}
        </nav> : <div className="teaching-session-empty"><strong>先建一节课</strong><p>标题写成一个具体问题，会更容易练明白。</p></div>}
      </aside>

      <main className="teaching-main">
        {selected ? <>
          <header className="teaching-lesson-header">
            <div><h2>{selected.title}</h2><p>{sessionProgress(selected)}</p></div>
            <button type="button" className="ghost-button" disabled={busy !== null} onClick={() => void generate()}>{busy === "generate" ? "正在准备…" : currentAttempt ? "重新整理讲解" : "准备讲解和练习"}</button>
          </header>

          <ol className="teaching-flow">
            <li className={selected.explanation ? "is-done" : "is-current"}>
              <section>
                <div className="teaching-step-heading"><span>1</span><h3>先读一遍</h3></div>
                {selected.explanation ? <p className="teaching-explanation-copy">{selected.explanation}</p> : <div className="teaching-step-empty"><strong>这里还没有讲解</strong><p>准备好以后，先完整读一遍，不用急着记住每句话。</p></div>}
              </section>
            </li>

            <li className={!currentAttempt ? "is-waiting" : currentAttempt.evaluated_at ? "is-done" : "is-current"}>
              <section>
                <div className="teaching-step-heading"><span>2</span><h3>合上讲解，自己回答</h3></div>
                {currentAttempt ? <>
                  <p className="teaching-question">{currentAttempt.prompt}</p>
                  {currentAttempt.rubric.length > 0 && <details className="teaching-answer-clues"><summary>回答时可以留意这几件事</summary><ul>{currentAttempt.rubric.map(item => <li key={item}>{item}</li>)}</ul></details>}
                  {currentAttempt.answered_at ? <blockquote className="teaching-saved-answer"><strong>我刚才的回答</strong><p>{currentAttempt.user_answer}</p></blockquote> : <form className="teaching-answer-form" onSubmit={event => { event.preventDefault(); void submitAnswer(); }}>
                    <label>用自己的话写下来<textarea aria-label="用自己的话写下来" rows={7} value={answer} onChange={event => setAnswer(event.target.value)} placeholder="先别照抄上面的句子。可以从定义、为什么、一个例子开始。" /></label>
                    <div className="teaching-answer-footer"><span>不要求一次写对，先留下你现在真正理解的部分。</span><button className="primary-button" disabled={busy !== null || !answer.trim()}>{busy === "answer" ? "正在保存…" : "留下我的回答"}</button></div>
                  </form>}
                  {currentAttempt.answered_at && !currentAttempt.evaluated_at && <div className="teaching-check-action"><p>回答已经保存。现在把它和这道题真正关心的内容对照一下。</p><button type="button" className="primary-button" disabled={busy !== null} onClick={() => void evaluate()}>{busy === "evaluate" ? "正在对照…" : "看看哪里还没说清"}</button></div>}
                </> : <div className="teaching-step-empty"><strong>先准备讲解和练习</strong><p>读完讲解后，这里会出现一道需要你亲自回答的问题。</p></div>}
              </section>
            </li>

            <li className={currentAttempt?.evaluated_at ? "is-current" : "is-waiting"}>
              <section>
                <div className="teaching-step-heading"><span>3</span><h3>对照一下，再决定怎么练</h3></div>
                {currentAttempt?.evaluated_at ? <div className="teaching-feedback">
                  <strong className="teaching-answer-summary">{answerSummary(currentAttempt)}</strong>
                  <p>{currentAttempt.feedback}</p>
                  {errorNote && <p className="teaching-error-note">{errorNote}</p>}
                  {(covered.length > 0 || missing.length > 0) && <div className="teaching-rubric-result">
                    <section><h4>已经说到</h4>{covered.length ? <ul>{covered.map(item => <li key={item}>{item}</li>)}</ul> : <p>这次还没有完整说到预设要点。</p>}</section>
                    <section><h4>还可以补上</h4>{missing.length ? <ul>{missing.map(item => <li key={item}>{item}</li>)}</ul> : <p>预设要点已经说全了，可以试着补一个反例。</p>}</section>
                  </div>}
                  {misconceptions.length > 0 && <div className="teaching-misconceptions"><strong>再确认一下</strong><ul>{misconceptions.map(item => <li key={item}>{item}</li>)}</ul></div>}
                  <div className="teaching-next-step"><strong>下一次可以这样练</strong><p>{currentAttempt.recommendation || "隔几天再用自己的话讲一遍，看看是否还能保持清楚。"}</p></div>
                  {recommendations && recommendations.recommendations.length > 1 && <div className="teaching-more-practice"><strong>这节课里还值得再练</strong><ul>{recommendations.recommendations.slice(1).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div>}
                  <details className="teaching-feedback-source"><summary>这段反馈是怎么整理的</summary><p>{currentAttempt.evaluation_source === "structured_model" ? "学习助手按照题目、你的回答和回答要点整理。它可能看漏内容，最终以你的理解和实际验证为准。" : "当前按这道题预先写好的回答要点逐项对照，没有调用在线服务。"}</p></details>
                </div> : <div className="teaching-step-empty"><strong>回答后再来看这里</strong><p>这里不会只给一个分数，而会告诉你哪里说到了、哪里还需要补。</p></div>}
              </section>
            </li>
          </ol>
        </> : <div className="teaching-main-empty"><strong>选一个问题，认真讲给自己听</strong><p>左边新建一节自学课，或者继续之前没讲完的内容。</p></div>}
      </main>
    </div>
  </div>;
}
