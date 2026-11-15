import { FormEvent, useEffect, useState } from "react";
import { api, getApiErrorMessage } from "./api";
import type { CodeRun, PracticeAttempt, PracticeExercise } from "./types";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

export default function PracticeWorkspace({ onNotice, onError }: Props) {
  const [exercises, setExercises] = useState<PracticeExercise[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [filter, setFilter] = useState<"all" | "algorithm" | "sql">("all");
  const [answer, setAnswer] = useState("");
  const [stdin, setStdin] = useState("");
  const [runResult, setRunResult] = useState<CodeRun | null>(null);
  const [attempt, setAttempt] = useState<PracticeAttempt | null>(null);
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [exerciseType, setExerciseType] = useState<"algorithm" | "sql">("algorithm");
  const [prompt, setPrompt] = useState("");
  const [difficulty, setDifficulty] = useState<"easy" | "medium" | "hard">("medium");
  const [validation, setValidation] = useState('{"cases":[{"stdin":"","expected_stdout":""}]}');

  async function load() {
    try {
      const data = await api.exercises(filter === "all" ? undefined : filter);
      setExercises(data);
      setSelectedId(current => current && data.some(item => item.id === current) ? current : data[0]?.id ?? null);
    } catch (error) { onError(getApiErrorMessage(error)); }
  }
  useEffect(() => { void load(); }, [filter]);
  const selected = exercises.find(item => item.id === selectedId) ?? null;

  function resetResult() { setAttempt(null); setRunResult(null); }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selected || !answer.trim()) return;
    setBusy(true);
    try {
      const result = await api.submitExerciseAttempt(selected.id, selected.exercise_type === "algorithm" ? { code: answer } : { query: answer });
      setAttempt(result); onNotice(result.passed ? "练习通过，已保存证据。" : "练习结果已保存，请根据反馈补强。");
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }
  async function run(confirmed: boolean) {
    if (!answer.trim()) return;
    setBusy(true);
    try {
      const result = await api.runCode({ code: answer, stdin, confirmed });
      if (!("status" in result)) { const ok = window.confirm(`${result.warning}\n\n确认在本机受限环境执行？`); if (ok) await run(true); return; }
      setRunResult(result); onNotice(result.status === "passed" ? "代码运行通过。" : "代码运行已结束，请检查输出。 ");
    } catch (error) { onError(getApiErrorMessage(error)); }
    finally { setBusy(false); }
  }
  async function create(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || !prompt.trim()) return;
    try {
      const spec = JSON.parse(validation) as Record<string, unknown>;
      await api.createExercise({ title: title.trim(), exercise_type: exerciseType, prompt: prompt.trim(), difficulty, validation_spec: spec });
      setTitle(""); setPrompt(""); setShowCreate(false); await load(); onNotice("练习已创建。");
    } catch (error) { onError(error instanceof Error && error.name === "SyntaxError" ? "校验配置不是有效 JSON。" : getApiErrorMessage(error)); }
  }
  function chooseType(type: "algorithm" | "sql") {
    setExerciseType(type);
    setValidation(type === "algorithm" ? '{"cases":[{"stdin":"","expected_stdout":""}]}' : '{"schema_sql":"CREATE TABLE items (id INTEGER, name TEXT);","seed_sql":"INSERT INTO items VALUES (1, \'示例\');","expected_rows":[[1,"示例"]]}');
  }

  return <div className="practice-workbench">
    <section className="practice-context sf-open-section"><div><h2 className="sf-section-title">算法与 SQL 练习</h2><p className="sf-surface-description">提交结果会作为学习证据保存。</p></div><div className="button-row"><select aria-label="练习类型筛选" value={filter} onChange={event => setFilter(event.target.value as typeof filter)}><option value="all">全部练习</option><option value="algorithm">算法</option><option value="sql">SQL</option></select><button type="button" className="primary-button" onClick={() => setShowCreate(current => !current)}>{showCreate ? "关闭创建" : "新建练习"}</button></div></section>
    {showCreate && <section className="practice-create sf-utility-surface stack-form"><div className="sf-surface-header"><h3 className="sf-surface-title">新建练习</h3><span className="sf-surface-metadata">校验配置</span></div><input aria-label="练习标题" value={title} onChange={event => setTitle(event.target.value)} placeholder="例如：两数之和" /><select aria-label="新建练习类型" value={exerciseType} onChange={event => chooseType(event.target.value as "algorithm" | "sql")}><option value="algorithm">算法</option><option value="sql">SQL</option></select><select aria-label="练习难度" value={difficulty} onChange={event => setDifficulty(event.target.value as typeof difficulty)}><option value="easy">简单</option><option value="medium">中等</option><option value="hard">困难</option></select><textarea aria-label="练习题目" rows={3} value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="题目要求、输入输出说明…" /><textarea aria-label="练习校验配置" rows={6} value={validation} onChange={event => setValidation(event.target.value)} /><div className="form-footer"><span>算法使用 cases；SQL 使用 schema_sql、seed_sql、expected_rows。</span><button className="primary-button" onClick={event => void create(event)}>保存练习</button></div></section>}
    <div className="practice-layout"><nav className="practice-problem-list sf-open-section" aria-label="练习题目列表"><div className="sf-surface-header"><h3 className="sf-section-title">练习列表</h3><span className="sf-surface-metadata">{exercises.length} 项</span></div>{exercises.length ? exercises.map(item => <button type="button" className={`practice-problem-row ${selectedId === item.id ? "selected" : ""}`} aria-current={selectedId === item.id ? "true" : undefined} key={item.id} onClick={() => { setSelectedId(item.id); setAnswer(""); resetResult(); }}><span className="tag">{item.exercise_type === "algorithm" ? "算法" : "SQL"}</span><span><strong>{item.title}</strong><small>{item.difficulty} · {item.prompt.slice(0, 70)}</small></span></button>) : <div className="empty"><p>还没有练习，先创建一题。</p></div>}</nav>
      <section className="practice-editor-region" aria-label="练习编辑区">{selected ? <><div className="practice-region-header"><div><h3>{selected.title}</h3><p>{selected.exercise_type === "algorithm" ? "标准输入输出校验" : "隔离 SQLite 只读查询校验"}</p></div><span className="tag">{selected.difficulty}</span></div><article className="practice-problem-statement"><p>{selected.prompt}</p>{selected.hints?.length > 0 && <details><summary>查看提示</summary>{selected.hints.map((hint, index) => <p key={index}>{hint}</p>)}</details>}</article><form className="stack-form" onSubmit={submit}><textarea aria-label="练习答案" rows={12} value={answer} onChange={event => { setAnswer(event.target.value); resetResult(); }} placeholder={selected.exercise_type === "algorithm" ? "输入 Python 代码…" : "输入 SELECT 或 WITH 查询…"} />{selected.exercise_type === "algorithm" && <textarea aria-label="标准输入" rows={3} value={stdin} onChange={event => setStdin(event.target.value)} placeholder="本地运行时的标准输入（可选）" />}<div className="button-row"><button className="primary-button" disabled={busy || !answer.trim()}>{busy ? "提交中…" : "提交并校验"}</button>{selected.exercise_type === "algorithm" && <button type="button" className="ghost-button" disabled={busy || !answer.trim()} onClick={() => void run(false)}>运行代码</button>}</div></form>{attempt && <ResultBox title={attempt.passed ? "练习通过" : "需要补强"} status={attempt.status} feedback={attempt.feedback} stdout={attempt.stdout} stderr={attempt.stderr} />}{runResult && <ResultBox title={runResult.status === "passed" ? "运行通过" : "运行结果"} status={runResult.status} feedback={`${runResult.duration_ms} ms · ${runResult.policy.network ?? "受限执行"}`} stdout={runResult.stdout} stderr={runResult.stderr} />}</> : <div className="empty"><p>选择一个练习开始。</p></div>}</section></div>
    <section className="practice-sandbox"><div className="practice-region-header"><div><h3>代码执行沙箱</h3><p>本机 Python 受限执行，默认禁止网络和危险文件操作。</p></div><span>最多 5 秒</span></div><textarea aria-label="沙箱代码" rows={7} value={answer} onChange={event => setAnswer(event.target.value)} placeholder="输入需要单独验证的 Python 代码…" /><textarea aria-label="沙箱输入" rows={2} value={stdin} onChange={event => setStdin(event.target.value)} placeholder="标准输入" /><button className="primary-button" disabled={busy || !answer.trim()} onClick={() => void run(false)}>执行并查看输出</button>{runResult && <ResultBox title="最近一次执行" status={runResult.status} feedback={`${runResult.duration_ms} ms`} stdout={runResult.stdout} stderr={runResult.stderr} />}</section>
  </div>;
}

function ResultBox({ title, status, feedback, stdout, stderr }: { title: string; status: string; feedback: string; stdout: string; stderr: string }) {
  return <div className={`practice-execution-result ${status}`} role="status" aria-live="polite"><div className="practice-result-header"><strong>{title}</strong><span>{status}</span></div><p>{feedback}</p>{stdout && <pre>{stdout}</pre>}{stderr && <pre className="error-text">{stderr}</pre>}</div>;
}
