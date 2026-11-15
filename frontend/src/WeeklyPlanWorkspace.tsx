import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "./api";
import type { Task, WeeklyPlan, WeeklySummary } from "./types";

type Props = {
  onNotice: (message: string) => void;
  onError: (message: string) => void;
};

function localDateKey(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function weekRange(value: string) {
  const selected = new Date(`${value}T00:00:00`);
  const day = selected.getDay() || 7;
  const monday = new Date(selected);
  monday.setDate(selected.getDate() - day + 1);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return { start: localDateKey(monday), end: localDateKey(sunday) };
}

function readableWeek(start: string, end: string) {
  const format = (value: string) => new Date(`${value}T00:00:00`).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
  return `${format(start)}—${format(end)}`;
}

function readableDate(value: string | null) {
  if (!value) return "本周内完成";
  return new Date(`${value}T00:00:00`).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function taskTypeLabel(value: string) {
  const labels: Record<string, string> = {
    practice: "动手练习",
    review: "复习整理",
    output: "要完成的成果",
    reading: "阅读理解",
    project: "项目推进",
    other: "其它安排",
  };
  return labels[value] ?? "其它安排";
}

function taskStatusLabel(value: Task["status"]) {
  const labels: Record<Task["status"], string> = {
    not_started: "还没开始",
    in_progress: "正在进行",
    pending_verification: "等我记下结果",
    completed: "已经完成",
    needs_review: "还要再看",
    mastered: "已经掌握",
    paused: "暂时放下",
    adjusted: "时间已调整",
  };
  return labels[value];
}

function priorityLabel(value: number) {
  if (value >= 4) return "先做";
  if (value <= 2) return "可以稍后";
  return "按计划";
}

export default function WeeklyPlanWorkspace({ onNotice, onError }: Props) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedDate, setSelectedDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [plan, setPlan] = useState<WeeklyPlan | null>(null);
  const [summary, setSummary] = useState<WeeklySummary | null>(null);
  const [objective, setObjective] = useState("");
  const [outputs, setOutputs] = useState("");
  const [reflection, setReflection] = useState("");
  const [blockers, setBlockers] = useState("");
  const [saving, setSaving] = useState(false);
  const [completingTaskId, setCompletingTaskId] = useState<number | null>(null);
  const [completionEvidence, setCompletionEvidence] = useState("");

  const range = weekRange(selectedDate);
  const weekKey = range.start;

  async function load() {
    try {
      const [taskData, summaryData] = await Promise.all([api.tasks(), api.weeklySummary(weekKey)]);
      setTasks(taskData);
      setSummary(summaryData);
      setPlan(summaryData.plan);
      setObjective(summaryData.plan?.objective ?? "");
      setOutputs((summaryData.plan?.expected_outputs ?? []).join("\n"));
      setReflection(summaryData.plan?.reflection ?? "");
      setBlockers(summaryData.plan?.blockers ?? "");
    } catch (error) {
      onError(error instanceof Error ? error.message : "暂时读不到这一周的安排");
    }
  }

  useEffect(() => {
    void load();
  }, [weekKey]);

  const weekTasks = summary?.tasks ?? tasks.filter(task => task.week_key === weekKey);
  const completed = summary?.completed_count ?? weekTasks.filter(task => task.status === "completed" || task.status === "mastered").length;
  const minutes = summary?.estimated_minutes ?? weekTasks.reduce((total, task) => total + (task.estimated_minutes ?? 0), 0);
  const completionRate = summary?.completion_rate ?? (weekTasks.length ? Math.round(completed / weekTasks.length * 100) : 0);
  const grouped = useMemo(
    () => weekTasks.reduce<Record<string, Task[]>>((result, task) => {
      const key = task.task_type || "other";
      (result[key] ??= []).push(task);
      return result;
    }, {}),
    [weekTasks],
  );

  async function savePlan(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      const payload = {
        objective: objective.trim(),
        expected_outputs: outputs.split("\n").map(item => item.trim()).filter(Boolean),
        reflection: reflection.trim(),
        blockers: blockers.trim(),
      };
      if (plan) await api.updateWeeklyPlan(plan.id, payload);
      else await api.createWeeklyPlan({ week_key: weekKey, ...payload });
      await load();
      onNotice("这一周的安排已经保存。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "这一周暂时没有保存成功");
    } finally {
      setSaving(false);
    }
  }

  async function reopenTask(task: Task) {
    try {
      await api.updateTask(task.id, { status: "not_started" });
      await load();
      onNotice("这项任务已经放回本周待办。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "暂时无法重新打开这项任务");
    }
  }

  function startCompleting(task: Task) {
    setCompletingTaskId(task.id);
    setCompletionEvidence("");
  }

  async function completeTask(event: FormEvent, task: Task) {
    event.preventDefault();
    if (!completionEvidence.trim()) return;
    try {
      await api.verifyTask(task.id, { target_status: "completed", evidence: completionEvidence.trim() });
      setCompletingTaskId(null);
      setCompletionEvidence("");
      await load();
      onNotice("完成情况已经记下来了。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "完成情况暂时没有保存成功");
    }
  }

  return (
    <div className="weekly-plan-workspace">
      <header className="weekly-plan-heading sf-surface-header">
        <div>
          <h2 className="sf-section-title">这一周怎么安排</h2>
          <p className="sf-surface-description">先写清最重要的一件事，做完后再回来记下这一周实际发生了什么。</p>
        </div>
        <label className="week-picker">
          <span>查看哪一周</span>
          <input aria-label="周计划日期" type="date" value={selectedDate} onChange={event => setSelectedDate(event.target.value)} />
          <strong>{readableWeek(range.start, range.end)}</strong>
        </label>
      </header>

      <section className="weekly-rhythm sf-open-section" aria-label="本周学习节奏">
        <div className="weekly-progress-copy">
          <span>本周进度</span>
          <strong>{weekTasks.length ? `已完成 ${completed} / ${weekTasks.length} 项` : "还没有安排任务"}</strong>
          <div className="weekly-progress-track" role="progressbar" aria-label="本周任务进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={completionRate}>
            <span style={{ width: `${Math.min(100, completionRate)}%` }} />
          </div>
        </div>
        <dl>
          <div><dt>预计投入</dt><dd>{minutes ? `${minutes} 分钟` : "还没估算"}</dd></div>
          <div><dt>实际记录</dt><dd>{summary?.actual_minutes ? `${summary.actual_minutes} 分钟` : "还没记录"}</dd></div>
          <div><dt>留下成果</dt><dd>{summary?.output_count ? `${summary.output_count} 项` : "还没有"}</dd></div>
        </dl>
      </section>

      <form className="weekly-plan-sheet sf-open-section" onSubmit={savePlan}>
        <section>
          <div className="weekly-sheet-heading">
            <strong>开始这一周之前</strong>
            <span>把方向写清楚就够了</span>
          </div>
          <label>
            <span>这周最重要的一件事</span>
            <textarea aria-label="本周目标" rows={3} value={objective} onChange={event => setObjective(event.target.value)} placeholder="例如：把 SQL 窗口函数的边界情况真正弄懂" />
          </label>
          <label>
            <span>做完后希望留下些什么</span>
            <textarea aria-label="本周产出" rows={4} value={outputs} onChange={event => setOutputs(event.target.value)} placeholder="每行写一项，例如：一份错题整理、两道完整练习" />
          </label>
        </section>
        <section>
          <div className="weekly-sheet-heading">
            <strong>一周结束时再写</strong>
            <span>没有内容时可以先留空</span>
          </div>
          <label>
            <span>这一周实际怎么样</span>
            <textarea aria-label="周复盘" rows={4} value={reflection} onChange={event => setReflection(event.target.value)} placeholder="哪些事情做成了？哪种方法对你有用？" />
          </label>
          <label>
            <span>哪里卡住了，下周怎么接着做</span>
            <textarea aria-label="本周阻塞" rows={3} value={blockers} onChange={event => setBlockers(event.target.value)} placeholder="例如：练习时间太碎，下周先固定两个完整时段" />
          </label>
        </section>
        <footer>
          <span>{plan?.updated_at ? `上次保存：${new Date(plan.updated_at).toLocaleString()}` : "这一周还没有保存过"}</span>
          <button className="primary-button" disabled={saving}>{saving ? "正在保存…" : "保存这一周"}</button>
        </footer>
      </form>

      <section className="weekly-task-ledger sf-open-section">
        <div className="weekly-task-heading sf-surface-header">
          <div>
            <h3 className="sf-section-title">本周要做的事</h3>
            <p className="sf-surface-description">做完一项时，简单写下实际完成了什么。</p>
          </div>
          <span className="sf-surface-metadata">{weekTasks.length ? `${weekTasks.length} 项` : "还没有任务"}</span>
        </div>

        {Object.keys(grouped).length ? (
          <div className="weekly-groups">
            {Object.entries(grouped).map(([type, items]) => (
              <section className="weekly-group" key={type}>
                <header><h4>{taskTypeLabel(type)}</h4><span>{items.length} 项</span></header>
                {items.map(task => {
                  const finished = task.status === "completed" || task.status === "mastered";
                  return (
                    <div className={`weekly-task-item ${finished ? "completed" : ""}`} key={task.id}>
                      <div className="weekly-task-row">
                        <button
                          type="button"
                          className="check-box-button"
                          aria-label={finished ? `重新打开 ${task.title}` : `记录完成情况：${task.title}`}
                          onClick={() => finished ? void reopenTask(task) : startCompleting(task)}
                        >
                          <span className="check-box">{finished ? "✓" : ""}</span>
                        </button>
                        <div className="weekly-task-copy">
                          <strong>{task.title}</strong>
                          <small>{readableDate(task.due_date)} · {taskStatusLabel(task.status)}</small>
                          <p>{task.expected_outcome || "做完后可以补一句实际结果。"}</p>
                          {task.agent_feedback && <small>补充说明：{task.agent_feedback}</small>}
                        </div>
                        <span className={`weekly-task-priority priority-${task.priority}`}>{priorityLabel(task.priority)}</span>
                      </div>
                      {completingTaskId === task.id && (
                        <form className="weekly-completion-note sf-utility-surface" onSubmit={event => void completeTask(event, task)}>
                          <label>
                            <span>这项任务实际完成了什么？</span>
                            <textarea aria-label={`完成情况：${task.title}`} rows={3} value={completionEvidence} onChange={event => setCompletionEvidence(event.target.value)} placeholder="例如：完成了两道练习，并把容易混淆的边界条件写进错题笔记" autoFocus />
                          </label>
                          <div className="button-row">
                            <button className="primary-button" disabled={!completionEvidence.trim()}>记为完成</button>
                            <button type="button" className="secondary-button" onClick={() => setCompletingTaskId(null)}>取消</button>
                          </div>
                        </form>
                      )}
                    </div>
                  );
                })}
              </section>
            ))}
          </div>
        ) : (
          <div className="empty weekly-plan-empty">
            <strong>这周还没有安排任务</strong>
            <p>可以去“学习计划”安排一件本周准备完成的事。</p>
          </div>
        )}
      </section>
    </div>
  );
}
