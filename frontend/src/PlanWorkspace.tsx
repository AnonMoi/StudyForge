import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api, getApiErrorMessage } from "./api";
import type { Goal, Stage, Task, TaskImpactPreview, TaskStatus, TaskTimerState, TaskVerification } from "./types";
import PlanAdjustmentProposalWorkspace from "./PlanAdjustmentProposal";

type Props = { onNotice: (message: string) => void; onError: (message: string) => void };

function StageDetailsWorkspace({ onNotice, onError }: Props) {
  const [stages, setStages] = useState<Stage[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [capabilities, setCapabilities] = useState("");
  const [prerequisites, setPrerequisites] = useState("");

  async function load() {
    try {
      const data = await api.stages();
      setStages(data);
      if (selectedId === null && data[0]) {
        setSelectedId(data[0].id);
        setCapabilities(data[0].capability_targets.join("\n"));
        setPrerequisites(data[0].prerequisites.join("\n"));
      }
    } catch (error) { onError(getApiErrorMessage(error)); }
  }

  useEffect(() => { void load(); }, []);

  function selectStage(id: number) {
    const stage = stages.find(item => item.id === id);
    if (!stage) return;
    setSelectedId(id);
    setCapabilities(stage.capability_targets.join("\n"));
    setPrerequisites(stage.prerequisites.join("\n"));
  }

  async function save() {
    if (selectedId === null) return;
    try {
      await api.updateStage(selectedId, {
        capability_targets: capabilities.split("\n").map(item => item.trim()).filter(Boolean),
        prerequisites: prerequisites.split("\n").map(item => item.trim()).filter(Boolean),
      });
      await load();
      onNotice("这一阶段的学习重点已保存。");
    } catch (error) { onError(getApiErrorMessage(error)); }
  }

  return <section className="plan-stage-details sf-open-section"><div className="sf-surface-header"><div><h3 className="sf-section-title">补充阶段重点</h3><p className="sf-surface-description">写清这一阶段要学会什么、开始前需要会什么，之后安排任务会更准确。</p></div><span className="sf-surface-metadata">{stages.length} 个阶段</span></div>{stages.length ? <div className="stack-form"><label>选择阶段<select aria-label="选择要补充的学习阶段" value={selectedId ?? ""} onChange={event => selectStage(Number(event.target.value))}>{stages.map(stage => <option key={stage.id} value={stage.id}>{stage.title}</option>)}</select></label><label>这一阶段要学会什么<textarea aria-label="阶段学习重点" rows={3} value={capabilities} onChange={event => setCapabilities(event.target.value)} placeholder="每行写一项，例如：能独立设计一组 REST API" /></label><label>开始前需要会什么<textarea aria-label="阶段前置知识" rows={3} value={prerequisites} onChange={event => setPrerequisites(event.target.value)} placeholder="每行写一项；没有也可以留空" /></label><button type="button" className="primary-button" onClick={() => void save()}>保存学习重点</button></div> : <div className="empty"><p>创建学习阶段后，可以在这里补充它的学习重点。</p></div>}</section>;
}

const statusNames: Record<string, string> = {
  active: "进行中", not_started: "未开始", in_progress: "进行中", pending_verification: "等你记录结果",
  completed: "已完成", needs_review: "需要再看", mastered: "已经掌握", paused: "已暂停", adjusted: "已调整",
};

function statusName(status: string) {
  return statusNames[status] ?? status;
}

function localDateKey(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function PlanWorkspace({ onNotice, onError }: Props) {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [stages, setStages] = useState<Stage[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [goalTitle, setGoalTitle] = useState("");
  const [goalDescription, setGoalDescription] = useState("");
  const [stageTitle, setStageTitle] = useState("");
  const [selectedGoal, setSelectedGoal] = useState("");
  const [editingGoalId, setEditingGoalId] = useState<number | null>(null);
  const [editingStageId, setEditingStageId] = useState<number | null>(null);
  const [taskTitle, setTaskTitle] = useState("");
  const [selectedStage, setSelectedStage] = useState("");
  const [weekKey, setWeekKey] = useState(() => { const today = new Date(); const monday = new Date(today); monday.setDate(today.getDate() - ((today.getDay() || 7) - 1)); return localDateKey(monday); });
  const [taskType, setTaskType] = useState("practice");
  const [expectedOutcome, setExpectedOutcome] = useState("");
  const [acceptanceCriteria, setAcceptanceCriteria] = useState("");
  const [taskImpact, setTaskImpact] = useState<TaskImpactPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [verificationTask, setVerificationTask] = useState<Task | null>(null);
  const [verificationStatus, setVerificationStatus] = useState<"completed" | "needs_review" | "mastered">("completed");
  const [verificationEvidence, setVerificationEvidence] = useState("");
  const [verificationNote, setVerificationNote] = useState("");
  const [actualMinutes, setActualMinutes] = useState("");
  const [verificationHistory, setVerificationHistory] = useState<TaskVerification[]>([]);
  const [timerStates, setTimerStates] = useState<Record<number, TaskTimerState>>({});
  const [timerBusy, setTimerBusy] = useState<Record<number, boolean>>({});
  const timerStatesRef = useRef(timerStates);
  const timerBusyRef = useRef(timerBusy);
  const timerRequestVersionRef = useRef<Record<number, number>>({});

  const load = async () => {
    try {
      const [goalData, stageData, taskData] = await Promise.all([api.goals(), api.stages(), api.tasks()]);
      setGoals(goalData); setStages(stageData); setTasks(taskData);
      if (!selectedGoal && goalData[0]) setSelectedGoal(String(goalData[0].id));
      if (!selectedStage && stageData[0]) setSelectedStage(String(stageData[0].id));
      const timerResults = await Promise.all(taskData.map(async task => {
        try { return [task.id, await api.taskTimer(task.id)] as const; }
        catch { return null; }
      }));
      setTimerStates(current => {
        const next = { ...current };
        timerResults.forEach(result => { if (result) next[result[0]] = result[1]; });
        return next;
      });
    } catch (error) { onError(error instanceof Error ? error.message : "学习计划加载失败"); }
  };
  useEffect(() => { void load(); }, []);

  useEffect(() => {
    timerStatesRef.current = timerStates;
  }, [timerStates]);
  useEffect(() => {
    timerBusyRef.current = timerBusy;
  }, [timerBusy]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      const runningTaskIds = Object.values(timerStatesRef.current)
        .filter(state => state.state === "running")
        .map(state => state.task_id)
        .filter(taskId => !timerBusyRef.current[taskId]);
      if (runningTaskIds.length === 0) return;
      void Promise.all(runningTaskIds.map(async taskId => {
        const version = timerRequestVersionRef.current[taskId] ?? 0;
        try { return [taskId, version, await api.taskTimer(taskId)] as const; }
        catch { return null; }
      })).then(results => {
        setTimerStates(current => {
          const next = { ...current };
          results.forEach(result => {
            if (result && (timerRequestVersionRef.current[result[0]] ?? 0) === result[1]) {
              next[result[0]] = result[2];
            }
          });
          return next;
        });
      });
    }, 1000);
    return () => window.clearInterval(interval);
  }, []);

  const goalStages = useMemo(() => stages.filter(stage => String(stage.goal_id) === selectedGoal), [stages, selectedGoal]);
  const stageName = (stageId: number | null) => stages.find(stage => stage.id === stageId)?.title ?? "未关联阶段";

  async function createGoal(event: FormEvent) {
    event.preventDefault(); if (!goalTitle.trim()) return; setBusy(true);
    try { const goal = editingGoalId === null ? await api.createGoal({ title: goalTitle.trim(), description: goalDescription.trim() }) : await api.updateGoal(editingGoalId, { title: goalTitle.trim(), description: goalDescription.trim() }); setGoalTitle(""); setGoalDescription(""); setEditingGoalId(null); setSelectedGoal(String(goal.id)); await load(); onNotice(editingGoalId === null ? "学习目标已创建。" : "学习目标已更新。"); }
    catch (error) { onError(error instanceof Error ? error.message : "创建目标失败"); } finally { setBusy(false); }
  }
  async function createStage(event: FormEvent) {
    event.preventDefault(); if (!selectedGoal || !stageTitle.trim()) return; setBusy(true);
    try { const stage = editingStageId === null ? await api.createStage(Number(selectedGoal), { title: stageTitle.trim(), order_index: goalStages.length + 1 }) : await api.updateStage(editingStageId, { title: stageTitle.trim() }); setStageTitle(""); setEditingStageId(null); setSelectedStage(String(stage.id)); await load(); onNotice(editingStageId === null ? "学习阶段已创建。" : "学习阶段已更新。"); }
    catch (error) { onError(error instanceof Error ? error.message : "创建阶段失败"); } finally { setBusy(false); }
  }
  function editGoal(goal: Goal) { setEditingGoalId(goal.id); setGoalTitle(goal.title); setGoalDescription(goal.description); setSelectedGoal(String(goal.id)); }
  function editStage(stage: Stage) { setEditingStageId(stage.id); setStageTitle(stage.title); setSelectedGoal(String(stage.goal_id)); setSelectedStage(String(stage.id)); }
  async function removeGoal(goal: Goal) {
    if (!window.confirm(`确认删除目标“${goal.title}”及其阶段吗？关联任务会保留但解除阶段关系。`)) return;
    try { await api.deleteGoal(goal.id); if (editingGoalId === goal.id) { setEditingGoalId(null); setGoalTitle(""); setGoalDescription(""); } await load(); onNotice("学习目标已删除。"); }
    catch (error) { onError(error instanceof Error ? error.message : "删除目标失败"); }
  }
  async function removeStage(stage: Stage) {
    if (!window.confirm(`确认删除阶段“${stage.title}”吗？关联任务会保留但解除阶段关系。`)) return;
    try { await api.deleteStage(stage.id); if (editingStageId === stage.id) { setEditingStageId(null); setStageTitle(""); } await load(); onNotice("学习阶段已删除。"); }
    catch (error) { onError(error instanceof Error ? error.message : "删除阶段失败"); }
  }
  async function previewTask(event: FormEvent) {
    event.preventDefault(); if (!taskTitle.trim()) return; setBusy(true);
    try { setTaskImpact(await api.previewTaskImpact({ title: taskTitle.trim(), stage_id: selectedStage ? Number(selectedStage) : null, due_date: new Date().toISOString().slice(0, 10), estimated_minutes: 30, week_key: weekKey || null, task_type: taskType })); onNotice("已检查这项任务的安排，确认后就会加入计划。"); }
    catch (error) { onError(error instanceof Error ? error.message : "暂时无法检查这项任务的安排"); } finally { setBusy(false); }
  }
  async function confirmTask() {
    if (!taskImpact || !taskTitle.trim()) return; setBusy(true);
    try { await api.createTask({ title: taskTitle.trim(), stage_id: selectedStage ? Number(selectedStage) : null, due_date: new Date().toISOString().slice(0, 10), estimated_minutes: 30, status: "not_started", week_key: weekKey || null, task_type: taskType, expected_outcome: expectedOutcome.trim(), acceptance_criteria: acceptanceCriteria.trim() }); setTaskTitle(""); setExpectedOutcome(""); setAcceptanceCriteria(""); setTaskImpact(null); await load(); onNotice("计划任务已确认加入。"); }
    catch (error) { onError(error instanceof Error ? error.message : "创建任务失败"); } finally { setBusy(false); }
  }
  async function updateStatus(task: Task, status: TaskStatus) {
    if (status === "completed" || status === "mastered" || status === "needs_review") {
      await openVerification(task);
      return;
    }
    try { await api.updateTask(task.id, { status }); await load(); onNotice("任务状态已更新。"); }
    catch (error) { onError(error instanceof Error ? error.message : "更新任务失败"); }
  }

  function formatTimer(seconds: number) {
    const total = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remaining = total % 60;
    return [hours, minutes, remaining].map((value, index) => index === 0 ? String(value).padStart(2, "0") : String(value).padStart(2, "0")).join(":");
  }

  function timerLabel(state: TaskTimerState | undefined) {
    if (!state) return "未开始";
    if (state.state === "running") return "进行中";
    if (state.state === "paused") return "已暂停";
    return state.accumulated_seconds > 0 ? "已停止" : "未开始";
  }

  async function operateTaskTimer(taskId: number, operation: "start" | "pause" | "resume" | "stop") {
    timerRequestVersionRef.current[taskId] = (timerRequestVersionRef.current[taskId] ?? 0) + 1;
    setTimerBusy(current => ({ ...current, [taskId]: true }));
    try {
      const operationApi = { start: api.startTaskTimer, pause: api.pauseTaskTimer, resume: api.resumeTaskTimer, stop: api.stopTaskTimer }[operation];
      const state = await operationApi(taskId);
      setTimerStates(current => ({ ...current, [taskId]: state }));
      if (operation === "stop") await load();
      onNotice(operation === "start" ? "任务计时已开始。" : operation === "pause" ? "任务计时已暂停。" : operation === "resume" ? "任务计时已继续。" : "任务计时已停止。");
    } catch (error) {
      onError(getApiErrorMessage(error));
    } finally {
      setTimerBusy(current => ({ ...current, [taskId]: false }));
    }
  }

  async function openVerification(task: Task) {
    setVerificationTask(task);
    setVerificationStatus(task.status === "mastered" ? "mastered" : "completed");
    try {
      setVerificationHistory(await api.taskVerifications(task.id));
    } catch (error) {
      setVerificationHistory([]);
      onError(error instanceof Error ? error.message : "完成记录加载失败");
    }
  }

  async function submitVerification(event: FormEvent) {
    event.preventDefault();
    if (!verificationTask || !verificationEvidence.trim()) return;
    try {
      await api.verifyTask(verificationTask.id, { target_status: verificationStatus, evidence: verificationEvidence.trim(), note: verificationNote.trim(), actual_minutes: actualMinutes ? Number(actualMinutes) : null });
      setVerificationTask(null); setVerificationHistory([]); setVerificationEvidence(""); setVerificationNote(""); setActualMinutes(""); await load(); onNotice("任务完成情况已保存。");
    } catch (error) { onError(error instanceof Error ? error.message : "完成情况保存失败"); }
  }

  return <div className="plan-workspace">
    <section className="plan-main-panel sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">我的学习计划</h2><p className="sf-surface-description">先确定方向，再把它拆成最近能完成的任务。</p></div><span className="sf-surface-metadata">{goals.length} 个目标 · {tasks.length} 项任务</span></div>
      <div className="plan-grid">
        <form className="stack-form" onSubmit={createGoal}><strong>{editingGoalId === null ? "我想做到什么" : "修改学习目标"}</strong><input aria-label="目标标题" value={goalTitle} onChange={event => setGoalTitle(event.target.value)} placeholder="例如：能够独立完成一个 FastAPI 项目" /><textarea aria-label="目标描述" value={goalDescription} onChange={event => setGoalDescription(event.target.value)} rows={3} placeholder="为什么想做、做到什么程度，就写在这里…" /><div className="button-row"><button className="primary-button" disabled={busy || !goalTitle.trim()}>{editingGoalId === null ? "添加目标" : "保存修改"}</button>{editingGoalId !== null && <button type="button" className="ghost-button" onClick={() => { setEditingGoalId(null); setGoalTitle(""); setGoalDescription(""); }}>取消</button>}</div></form>
        <form className="stack-form" onSubmit={createStage}><strong>{editingStageId === null ? "最近先走到哪一步" : "修改当前阶段"}</strong><select aria-label="选择目标" value={selectedGoal} onChange={event => setSelectedGoal(event.target.value)}><option value="">先选择一个目标</option>{goals.map(goal => <option key={goal.id} value={goal.id}>{goal.title}</option>)}</select><input aria-label="阶段标题" value={stageTitle} onChange={event => setStageTitle(event.target.value)} placeholder="例如：掌握 FastAPI 路由与数据校验" /><div className="button-row"><button className="primary-button" disabled={busy || !selectedGoal || !stageTitle.trim()}>{editingStageId === null ? "添加阶段" : "保存修改"}</button>{editingStageId !== null && <button type="button" className="ghost-button" onClick={() => { setEditingStageId(null); setStageTitle(""); }}>取消</button>}</div></form>
      </div>
      {(goals.length > 0 || stages.length > 0) && <div className="plan-hierarchy"><div className="sf-surface-header"><h3 className="sf-section-title">目标和当前阶段</h3><span className="sf-surface-metadata">可以随学习进度调整</span></div>{goals.map(goal => <div className="plan-hierarchy-goal" key={goal.id}><div className="task-row-main"><div><strong>{goal.title}</strong><small>{statusName(goal.status)} · {goal.description || "还没有补充说明"}</small></div><div className="button-row"><button type="button" className="ghost-button" onClick={() => editGoal(goal)}>修改</button><button type="button" className="ghost-button" onClick={() => void removeGoal(goal)}>删除</button></div></div><div className="plan-hierarchy-stages">{stages.filter(stage => stage.goal_id === goal.id).map(stage => <div className="task-row" key={stage.id}><div><strong>{stage.title}</strong><small>{statusName(stage.status)} · {stage.capability_targets.length ? `准备学会：${stage.capability_targets.join("、")}` : "还没有补充学习重点"}</small></div><div className="button-row"><button type="button" className="ghost-button" onClick={() => editStage(stage)}>修改</button><button type="button" className="ghost-button" onClick={() => void removeStage(stage)}>删除</button></div></div>)}</div></div>)}</div>}
      <div className="plan-task-heading"><strong>安排一项最近要做的事</strong><small>先检查它和当前目标、时间安排是否合适，再加入任务清单。</small></div><form className="inline-form plan-task-form" onSubmit={previewTask}><input aria-label="任务标题" value={taskTitle} onChange={event => setTaskTitle(event.target.value)} placeholder="例如：完成一组 FastAPI 路由练习" /><select aria-label="任务阶段" value={selectedStage} onChange={event => setSelectedStage(event.target.value)}><option value="">暂不关联阶段</option>{goalStages.map(stage => <option key={stage.id} value={stage.id}>{stage.title}</option>)}</select><select aria-label="任务类型" value={taskType} onChange={event => setTaskType(event.target.value)}><option value="practice">动手练习</option><option value="review">复习整理</option><option value="output">完成产出</option><option value="reading">阅读理解</option></select><input aria-label="计划周" type="date" value={weekKey} onChange={event => setWeekKey(event.target.value)} /><input aria-label="预期结果" value={expectedOutcome} onChange={event => setExpectedOutcome(event.target.value)} placeholder="做完后会留下什么（可选）" /><input aria-label="完成标准" value={acceptanceCriteria} onChange={event => setAcceptanceCriteria(event.target.value)} placeholder="怎样算真正做完（可选）" /><button className="primary-button" disabled={busy || !taskTitle.trim()}>加入前检查</button></form>
      {taskImpact && <div className="task-impact-preview sf-utility-surface" aria-live="polite"><div className="sf-surface-header"><div><strong className="sf-surface-title">加入前检查：{taskImpact.title}</strong><p className="sf-surface-description">现在还没有加入计划，你可以先看看安排是否合适。</p></div><span className="sf-surface-metadata">{taskImpact.impact_level === "high" ? "安排偏满" : taskImpact.impact_level === "medium" ? "需要留意" : "安排合适"}</span></div><p>对应方向：{taskImpact.relation.goal?.title ?? "暂未关联目标"} · {taskImpact.relation.stage?.title ?? "暂未关联阶段"}{taskImpact.relation.topic ? ` · ${taskImpact.relation.topic.name}` : ""}{taskImpact.relation.project ? ` · 项目：${taskImpact.relation.project.title}` : ""}</p><p>开始前最好会：{taskImpact.prerequisites.length ? taskImpact.prerequisites.join("、") : "没有特别要求"}</p><p>本周原有 {taskImpact.schedule_impact.existing_estimated_minutes} 分钟，加入后约 {taskImpact.schedule_impact.after_estimated_minutes} 分钟；目前还有 {taskImpact.schedule_impact.existing_active_task_count} 项任务在进行。</p><ul>{taskImpact.recommendations.map(item => <li key={item}>{item}</li>)}</ul><div className="button-row"><button type="button" className="primary-button" disabled={busy} onClick={() => void confirmTask()}>加入任务清单</button><button type="button" className="ghost-button" disabled={busy} onClick={() => setTaskImpact(null)}>再改一下</button></div></div>}
    </section>
    <section className="plan-task-list-panel sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">最近要做的事</h2><p className="sf-surface-description">开始、计时，做完后简单记下结果。</p></div><span className="sf-surface-metadata">{tasks.length ? `${tasks.length} 项任务` : "还没有任务"}</span></div>{tasks.length ? <div className="task-list">{tasks.map(task => { const timer = timerStates[task.id]; const isBusy = timerBusy[task.id] ?? false; return <div className={`task-row ${task.status === "completed" || task.status === "mastered" ? "completed" : ""}`} key={task.id}><div className="task-row-main"><div><strong>{task.title}</strong><small>{stageName(task.stage_id)} · {task.due_date ?? "没有截止日期"} · {statusName(task.status)}{task.acceptance_criteria ? ` · 做完标准：${task.acceptance_criteria}` : ""}</small></div><span className="priority">优先级 {task.priority}</span></div><div className="task-timer" aria-live="polite"><div className="task-timer-status"><strong>{formatTimer(timer?.accumulated_seconds ?? 0)}</strong><span className={`task-timer-state ${timer?.state ?? "stopped"}`}>{timerLabel(timer)}</span>{timer?.actual_minutes !== null && timer?.actual_minutes !== undefined && <small>已记下 {timer.actual_minutes} 分钟</small>}</div><div className="task-timer-actions">{(!timer || timer.state === "stopped") && <button className="secondary-button" disabled={isBusy} onClick={() => void operateTaskTimer(task.id, "start")}>开始计时</button>}{timer?.state === "running" && <><button className="secondary-button" disabled={isBusy} onClick={() => void operateTaskTimer(task.id, "pause")}>暂停</button><button className="secondary-button" disabled={isBusy} onClick={() => void operateTaskTimer(task.id, "stop")}>结束计时</button></>}{timer?.state === "paused" && <><button className="secondary-button" disabled={isBusy} onClick={() => void operateTaskTimer(task.id, "resume")}>继续</button><button className="secondary-button" disabled={isBusy} onClick={() => void operateTaskTimer(task.id, "stop")}>结束计时</button></>}</div></div><div className="task-actions"><select aria-label={`更新 ${task.title} 状态`} value={task.status} onChange={event => void updateStatus(task, event.target.value as TaskStatus)}><option value="not_started">未开始</option><option value="in_progress">进行中</option><option value="pending_verification">等我记录结果</option><option value="completed">已完成</option><option value="needs_review">需要再看</option><option value="mastered">已经掌握</option><option value="paused">已暂停</option><option value="adjusted">已调整</option></select><button className="secondary-button" onClick={() => void openVerification(task)}>记录完成情况</button></div></div>; })}</div> : <div className="empty"><p>先在上面安排一项最近准备完成的事。</p></div>}{verificationTask && <form className="verification-form sf-utility-surface" onSubmit={submitVerification}><strong>记录完成情况：{verificationTask.title}</strong>{verificationHistory.length > 0 && <div className="verification-history"><small>最近的完成记录</small>{verificationHistory.slice(0, 3).map(item => <div className="verification-history-item" key={item.id}><span>{statusName(item.target_status)} · {item.actual_minutes ?? "未记录"} 分钟 · {new Date(item.verified_at).toLocaleString()}</span><p>{item.evidence}</p>{item.note && <small>{item.note}</small>}</div>)}</div>}<select aria-label="完成结果" value={verificationStatus} onChange={event => setVerificationStatus(event.target.value as "completed" | "needs_review" | "mastered")}><option value="completed">已经完成</option><option value="needs_review">还需要再看</option><option value="mastered">已经掌握</option></select><textarea aria-label="完成结果" value={verificationEvidence} onChange={event => setVerificationEvidence(event.target.value)} rows={3} placeholder="写下实际做了什么、留下了什么结果，例如练习、笔记、代码或链接…" /><input aria-label="实际用时" type="number" min="0" max="1440" value={actualMinutes} onChange={event => setActualMinutes(event.target.value)} placeholder="实际用了多少分钟（可选）" /><textarea aria-label="补充说明" value={verificationNote} onChange={event => setVerificationNote(event.target.value)} rows={2} placeholder="还有什么想补充的（可选）" /><div className="button-row"><button className="primary-button" disabled={!verificationEvidence.trim()}>保存完成情况</button><button type="button" className="secondary-button" onClick={() => setVerificationTask(null)}>取消</button></div></form>}</section>
    <StageDetailsWorkspace onNotice={onNotice} onError={onError} />
    <PlanAdjustmentProposalWorkspace onNotice={onNotice} onError={onError} />
  </div>;
}
