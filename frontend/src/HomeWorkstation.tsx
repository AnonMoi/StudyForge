import { FormEvent, useState } from "react";
import type { Dashboard, LearningReminder } from "./types";

type HomeWorkstationProps = {
  dashboard: Dashboard;
  taskTitle: string;
  logText: string;
  saving: boolean;
  updatingTaskId: number | null;
  reminders: LearningReminder[];
  desktopNotifications: boolean;
  backgroundPushEnabled: boolean;
  notificationPermission: NotificationPermission;
  onTaskTitleChange: (value: string) => void;
  onLogTextChange: (value: string) => void;
  onAddTask: (event: FormEvent<HTMLFormElement>) => void;
  onAddLog: (event: FormEvent<HTMLFormElement>) => void;
  onToggleTask: (task: Dashboard["today_tasks"][number]) => void;
  onNavigate: (view: string) => void;
  onOpenAssistant: () => void;
  onEnableDesktopNotifications: () => void;
  onDisableDesktopNotifications: () => void;
  onEnableBackgroundPush: () => void;
  onDisableBackgroundPush: () => void;
  onTestBackgroundPush: () => void;
  onRefreshReminders: () => void;
  onAcknowledgeReminder: (reminder: LearningReminder) => void;
};

function ArrowIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none"><path d="M5 12h13m-5-5 5 5-5 5" /></svg>;
}

function AnnaPortrait() {
  const [failed, setFailed] = useState(false);
  if (failed) return <span className="home-anna-fallback" aria-label="八奈见杏菜">杏</span>;
  return <img src="/characters/anna/main-upscaled-x4.png" alt="八奈见杏菜" onError={() => setFailed(true)} />;
}

export default function HomeWorkstation(props: HomeWorkstationProps) {
  const { dashboard } = props;
  const nextTask = dashboard.today_tasks.find(task => task.status !== "completed") ?? null;
  const suggestion = dashboard.agent_suggestions?.[0] ?? null;
  const completedCount = dashboard.today_tasks.filter(task => task.status === "completed").length;
  const pendingReminders = props.reminders.filter(reminder => reminder.status === "pending");
  const focusTitle = nextTask?.title ?? dashboard.current_goal?.title ?? "先写下一件今天能完成的事";
  const focusDetail = nextTask
    ? `${nextTask.estimated_minutes ?? 30} 分钟 · ${dashboard.current_stage?.title ?? "今日学习"}`
    : dashboard.current_stage?.title ?? "把任务缩小到 30 分钟内可推进的一步";
  const annaMessage = suggestion?.detail
    ?? (nextTask ? `先把“${nextTask.title}”推进一小步，完成后记下结果。` : "先定下一件具体的小事。开始以后，我再陪你看下一步。");

  return <div className="home-workstation" data-design-contract="Operate Workbench; calm campus paper; next-step-first; Anna contextual companion">
    <main className="home-workspace" aria-label="今日学习工作区">
      <section className="home-focus sf-working-surface" aria-labelledby="home-focus-title">
        <div className="home-focus-copy">
          <span>继续学习</span>
          <h3 className="sf-surface-title sf-surface-title--prominent" id="home-focus-title">{focusTitle}</h3>
          <p className="sf-surface-description">{focusDetail}</p>
        </div>
        <button type="button" className="sf-button sf-button--primary home-focus-action" onClick={() => props.onNavigate("plan")}>
          {nextTask ? "打开计划" : "安排第一步"}<ArrowIcon />
        </button>
      </section>

      <section className="home-section home-today sf-open-section" aria-labelledby="home-today-title">
        <header className="home-section-heading sf-surface-header">
          <div><h3 className="sf-section-title" id="home-today-title">今天先完成什么？</h3><p className="sf-surface-description">{completedCount} 项完成 · {dashboard.today_tasks.length - completedCount} 项待推进</p></div>
          <button type="button" className="sf-button sf-button--tertiary home-text-action" onClick={() => props.onNavigate("plan")}>查看计划 <ArrowIcon /></button>
        </header>
        <form className="home-task-entry sf-composite-field" onSubmit={props.onAddTask}>
          <span className="home-task-command-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" /></svg></span>
          <label className="sr-only" htmlFor="task-input">添加今日任务</label>
          <input className="sf-field" id="task-input" value={props.taskTitle} onChange={event => props.onTaskTitleChange(event.target.value)} placeholder="添加一件 30 分钟内可推进的事" />
          <button type="submit" className="sf-button sf-button--tertiary" disabled={props.saving || !props.taskTitle.trim()}>添加任务</button>
        </form>
        <div className="home-task-list" aria-label="今日任务列表">
          {dashboard.today_tasks.length ? dashboard.today_tasks.map(task => {
            const completed = task.status === "completed";
            return <article className={`home-task-row ${completed ? "is-complete" : ""}`} key={task.id}>
              <button type="button" className="home-task-check" aria-label={completed ? `重新打开任务：${task.title}` : `查看任务：${task.title}`} aria-pressed={completed} disabled={props.updatingTaskId === task.id} onClick={() => props.onToggleTask(task)}><span>{completed ? "✓" : ""}</span></button>
              <button type="button" className="home-task-copy" onClick={() => props.onNavigate("plan")}>
                <strong>{task.title}</strong>
                <small>{task.estimated_minutes ?? "—"} 分钟 · {completed ? "已完成" : task.status === "in_progress" ? "进行中" : "待完成"}</small>
              </button>
              <span className="home-task-priority">{task.priority >= 4 ? "先做" : task.priority <= 2 ? "稍后" : "按计划"}</span>
            </article>;
          }) : <div className="home-empty-row"><strong>今天还没有任务</strong><p>在上方写下一件足够具体、可以验证结果的事。</p></div>}
        </div>
      </section>

      <div className="home-desk-grid">
        <section className="home-section home-recent sf-open-section" aria-labelledby="home-recent-title">
          <header className="home-section-heading sf-surface-header">
            <div><h3 className="sf-section-title" id="home-recent-title">最近记录</h3><p className="sf-surface-description">从真实记录接回学习上下文</p></div>
            <button type="button" className="sf-button sf-button--tertiary home-text-action" onClick={() => props.onNavigate("logs")}>全部记录 <ArrowIcon /></button>
          </header>
          <div className="home-log-list">
            {dashboard.recent_logs.slice(0, 3).map(log => <button type="button" className="home-log-row" key={log.id} onClick={() => props.onNavigate("logs")}>
              <time>{new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date(`${log.log_date}T00:00:00`))}</time>
              <span><strong>{log.raw_text}</strong><small>{log.extracted_duration ? `${log.extracted_duration} 分钟` : "原始记录"}{log.extracted_outputs.length ? ` · ${log.extracted_outputs.length} 项产出` : ""}</small></span>
              <ArrowIcon />
            </button>)}
            {!dashboard.recent_logs.length && <div className="home-recent-empty">
              <span className="home-timeline-origin" aria-hidden="true" />
              <div><strong>记录从下一次完成开始</strong><p>完成一段学习后，把事实原样记下来。</p></div>
              <button type="button" className="sf-button sf-button--tertiary sf-button--compact" onClick={() => document.getElementById("daily-log-text")?.focus()}>写下第一条</button>
            </div>}
          </div>
        </section>

        <section className="home-capture sf-utility-surface" aria-labelledby="home-capture-title">
          <header className="sf-surface-header"><div><h3 className="sf-surface-title" id="home-capture-title">快速记录</h3><p className="sf-surface-description">刚才实际做了什么？先写事实，稍后再整理。</p></div></header>
          <form className="sf-composite-field" onSubmit={props.onAddLog}>
            <label className="sr-only" htmlFor="daily-log-text">今天实际学了什么</label>
            <textarea className="sf-field" id="daily-log-text" value={props.logText} onChange={event => props.onLogTextChange(event.target.value)} rows={5} placeholder="例如：完成了栈的练习，用时 35 分钟；边界条件还不确定。" />
            <div><span>临时工作面 · 按原文保存</span><button type="submit" className="sf-button sf-button--primary" disabled={props.saving || !props.logText.trim()}>{props.saving ? "保存中" : "存入记录"}</button></div>
          </form>
        </section>
      </div>

      <section className="home-section home-reminders sf-open-section" aria-labelledby="home-reminders-title">
        <header className="home-section-heading sf-surface-header">
          <div><h3 className="sf-section-title" id="home-reminders-title">学习提醒</h3><p className="sf-surface-description">只做提示，不会替你修改计划或记录</p></div>
          <details className="home-reminder-settings">
            <summary className="sf-button sf-button--tertiary">提醒设置</summary>
            <div>
              {props.desktopNotifications
                ? <button type="button" className="sf-button sf-button--tertiary" onClick={props.onDisableDesktopNotifications}>关闭桌面提醒</button>
                : <button type="button" className="sf-button sf-button--tertiary" disabled={props.notificationPermission === "denied" || !("Notification" in window)} onClick={props.onEnableDesktopNotifications}>{props.notificationPermission === "denied" ? "桌面提醒已被关闭" : "启用桌面提醒"}</button>}
              {props.backgroundPushEnabled
                ? <><button type="button" className="sf-button sf-button--tertiary" onClick={props.onTestBackgroundPush}>试发提醒</button><button type="button" className="sf-button sf-button--tertiary" onClick={props.onDisableBackgroundPush}>关闭后台提醒</button></>
                : <button type="button" className="sf-button sf-button--tertiary" onClick={props.onEnableBackgroundPush}>启用后台提醒</button>}
              <button type="button" className="sf-button sf-button--tertiary" onClick={props.onRefreshReminders}>刷新提醒</button>
            </div>
          </details>
        </header>
        <div className="home-reminder-list">
          {pendingReminders.slice(0, 3).map(reminder => <article className="home-reminder-row" key={reminder.id}>
            <span>{reminder.reminder_type === "daily_review" ? "今天" : reminder.reminder_type === "weekly_review" ? "本周" : "阶段"}</span>
            <div><strong>{reminder.title}</strong><small>{reminder.detail}</small></div>
            <button type="button" className="sf-button sf-button--tertiary sf-button--compact" onClick={() => props.onAcknowledgeReminder(reminder)}>知道了</button>
          </article>)}
          {!pendingReminders.length && <div className="home-empty-row home-empty-compact"><strong>现在没有需要处理的提醒。</strong></div>}
        </div>
      </section>
    </main>

    <aside className="home-companion sf-companion-surface" aria-labelledby="home-anna-title">
      <header className="home-companion-heading sf-surface-header">
        <div><h3 className="sf-surface-title" id="home-anna-title">八奈见杏菜</h3><p className="sf-surface-description">学习伙伴</p></div>
        <button type="button" className="sf-button sf-button--tertiary sf-button--icon home-companion-menu" aria-label="打开学习伙伴对话" onClick={props.onOpenAssistant}><span /><span /><span /></button>
      </header>
      <div className="home-anna-stage"><AnnaPortrait /></div>
      <blockquote className="home-anna-dialogue"><p>{annaMessage}</p></blockquote>
      <div className="home-companion-context">
        <span>现在一起推进</span>
        <strong>{dashboard.current_stage?.title ?? focusTitle}</strong>
        <small>{completedCount}/{dashboard.today_tasks.length || 0} 项完成{dashboard.due_reviews?.length ? ` · ${dashboard.due_reviews.length} 项待复习` : ""}</small>
      </div>
      <div className="home-companion-actions">
        {suggestion && <button type="button" className="sf-button sf-button--tertiary home-anna-suggestion" onClick={() => props.onNavigate(suggestion.route)}><span><small>杏菜建议</small><strong>{suggestion.title}</strong></span><ArrowIcon /></button>}
        <button type="button" className="sf-button sf-button--secondary home-anna-primary" onClick={props.onOpenAssistant}>和杏菜聊聊 <ArrowIcon /></button>
      </div>
      <footer><span>所有学习数据保存在你的工作站</span></footer>
    </aside>
  </div>;
}
