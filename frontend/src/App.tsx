import { FormEvent, useEffect, useRef, useState } from "react";
import { api, downloadJson, getApiErrorMessage } from "./api";
import type { Dashboard, GlobalSearchResponse, LearningReminder, ModelHealth, SetupStatus } from "./types";
import AgentChat from "./AgentChat";
import AgentChangeWorkspace from "./AgentChangeWorkspace";
import ModelTaskWorkspace from "./ModelTaskWorkspace";
import PlanWorkspace from "./PlanWorkspace";
import LogWorkspace from "./LogWorkspace";
import NotesWorkspace from "./NotesWorkspace";
import { KnowledgeWorkspace, AnalyticsWorkspace, ImportsWorkspace } from "./KnowledgeWorkspace";
import OperationsWorkspace from "./OperationsWorkspace";
import ProjectsWorkspace, { ReviewScheduleWorkspace, ReviewWorkspace, RestoreWorkspace } from "./ProjectsWorkspace";
import ProjectMetadataWorkspace from "./ProjectMetadataWorkspace";
import CapabilitiesWorkspace from "./CapabilitiesWorkspace";
import { ReviewCardsWorkspace } from "./ReviewCardsWorkspace";
import WeeklyPlanWorkspace from "./WeeklyPlanWorkspace";
import TeachingWorkspace from "./TeachingWorkspace";
import ReportsWorkspace from "./ReportsWorkspace";
import PracticeWorkspace from "./PracticeWorkspace";
import InterviewWorkspace from "./InterviewWorkspace";
import JobAnalysisWorkspace from "./JobAnalysisWorkspace";
import PluginWorkspace from "./PluginWorkspace";
import HomeWorkstation from "./HomeWorkstation";
import SetupCenterWorkspace from "./SetupCenterWorkspace";
import PageContainer, { type PageContainerMode } from "./PageContainer";
import PageHeader, { type PageHeaderMode } from "./PageHeader";
import { acquireDocumentScrollLock } from "./documentScrollLock";

const emptyDashboard: Dashboard = { today_tasks: [], recent_logs: [], current_goal: null, current_stage: null, weekly_minutes: 0, output_count: 0, pending_review_count: 0, progress_signal: undefined };
const annaFaceVariant = Math.floor(Math.random() * 2);
type Theme = "light" | "dark";

type NavigationItem = { id: string; icon: string; label: string };
type NavigationDomain = {
  id: "today" | "planning" | "learning" | "review" | "system";
  icon: string;
  label: string;
  description: string;
  items: NavigationItem[];
};

const navigationDomains: NavigationDomain[] = [
  {
    id: "today", icon: "home", label: "今天", description: "决定今天做什么，顺手记下来",
    items: [
      { id: "dashboard", icon: "home", label: "今日总览" },
      { id: "logs", icon: "document", label: "今日记录" },
    ],
  },
  {
    id: "planning", icon: "calendar", label: "规划", description: "把目标拆成今天能完成的事",
    items: [
      { id: "plan", icon: "check", label: "学习计划" },
      { id: "weeklyPlan", icon: "calendar", label: "周计划" },
      { id: "projects", icon: "grid", label: "项目工作台" },
      { id: "jobAnalysis", icon: "target", label: "岗位分析" },
      { id: "interview", icon: "target", label: "模拟面试" },
    ],
  },
  {
    id: "learning", icon: "book", label: "学习", description: "在练习、笔记与讲解中推进",
    items: [
      { id: "practice", icon: "code", label: "练习与沙箱" },
      { id: "notes", icon: "note", label: "笔记库" },
      { id: "knowledge", icon: "map", label: "知识地图" },
      { id: "teaching", icon: "book", label: "教学闭环" },
      { id: "coach", icon: "spark", label: "学习伙伴" },
    ],
  },
  {
    id: "review", icon: "cards", label: "回看", description: "安排复习，看看最近学得怎么样",
    items: [
      { id: "reviews", icon: "clock", label: "今日复习" },
      { id: "reviewCards", icon: "cards", label: "复习卡片" },
      { id: "capabilities", icon: "target", label: "能力画像" },
      { id: "reports", icon: "chart", label: "学习报告" },
      { id: "analytics", icon: "chart", label: "统计复盘" },
    ],
  },
  {
    id: "system", icon: "settings", label: "系统", description: "管理资料、本地服务与运行边界",
    items: [
      { id: "setup", icon: "settings", label: "初始化设置" },
      { id: "imports", icon: "download", label: "文件导入" },
      { id: "restore", icon: "upload", label: "备份恢复" },
      { id: "modelTasks", icon: "model", label: "模型任务" },
      { id: "plugins", icon: "grid", label: "插件系统" },
      { id: "operations", icon: "activity", label: "运行与审计" },
    ],
  },
];

type PageIdentityContract = {
  mode: "implicit" | PageHeaderMode;
  description?: string;
};

const pageIdentityContracts: Record<string, PageIdentityContract> = {
  dashboard: { mode: "implicit" },
  logs: { mode: "reading", description: "写下今天真实发生的学习，再沿时间线回看上下文。" },
  plan: { mode: "standard", description: "确定学习方向，把目标拆成近期可以验证的阶段与任务。" },
  weeklyPlan: { mode: "standard", description: "围绕本周最重要的结果安排任务，并在结束后记录实际进展。" },
  projects: { mode: "implicit" },
  jobAnalysis: { mode: "standard", description: "把岗位要求与已经留下的练习、项目和笔记证据放在一起对照。" },
  interview: { mode: "implicit" },
  practice: { mode: "implicit" },
  notes: { mode: "implicit" },
  knowledge: { mode: "implicit" },
  teaching: { mode: "implicit" },
  coach: { mode: "implicit" },
  reviews: { mode: "implicit" },
  reviewCards: { mode: "implicit" },
  capabilities: { mode: "standard", description: "基于已保存的学习证据回看当前能力，不把一次结果当成定论。" },
  reports: { mode: "reading", description: "把一段时间里的学习事实、成果、卡点和下一步整理成连续回看。" },
  analytics: { mode: "reading", description: "翻一翻这段时间真正留下来的学习记录。" },
  setup: { mode: "standard", description: "确认学习画像、模型路由与同步边界；未完成的设置不会阻塞工作站。" },
  imports: { mode: "standard", description: "授权本地目录或网页资料，预览后再写入知识库。" },
  restore: { mode: "standard", description: "通过加密同步包或本地备份预览差异，再确认追加恢复。" },
  modelTasks: { mode: "standard", description: "查看模型任务分工、路由边界与调用预算。" },
  plugins: { mode: "standard", description: "管理声明式扩展；安装与执行都先预览，再由你确认。" },
  operations: { mode: "standard", description: "查看本地服务、模型调用、账单与结构化变更记录。" },
};

export default function App() {
  const [dashboard, setDashboard] = useState<Dashboard>(emptyDashboard);
  const [model, setModel] = useState<ModelHealth | null>(null);
  const [dashboardStatus, setDashboardStatus] = useState<"loading" | "ready" | "error">("loading");
  const [dashboardLoadError, setDashboardLoadError] = useState("");
  const [activeView, setActiveView] = useState("dashboard");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [setupReminderDismissed, setSetupReminderDismissed] = useState(() => (
    typeof window !== "undefined" && window.sessionStorage.getItem("learning-workstation.setup-reminder") === "dismissed"
  ));
  const [taskTitle, setTaskTitle] = useState("");
  const [logText, setLogText] = useState("");
  const [saving, setSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<GlobalSearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [updatingTaskId, setUpdatingTaskId] = useState<number | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [mobileNavigationMode, setMobileNavigationMode] = useState(() => (
    typeof window !== "undefined" && window.matchMedia("(max-width: 860px)").matches
  ));
  const [sidebarPinned, setSidebarPinned] = useState(() => typeof window !== "undefined" && window.localStorage.getItem("learning-workstation.sidebar") === "pinned");
  const [sidebarHoverSuppressed, setSidebarHoverSuppressed] = useState(false);
  const [selectedDomainId, setSelectedDomainId] = useState<NavigationDomain["id"]>("today");
  const [theme, setTheme] = useState<Theme>(() => {
    if (typeof window === "undefined") return "light";
    const saved = window.localStorage.getItem("learning-workstation.theme");
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [assistantOpen, setAssistantOpen] = useState(false);
  const assistantCloseRef = useRef<HTMLButtonElement | null>(null);
  const assistantDrawerRef = useRef<HTMLElement | null>(null);
  const assistantTriggerRef = useRef<HTMLElement | null>(null);
  const mobileNavToggleRef = useRef<HTMLButtonElement | null>(null);
  const navigationRef = useRef<HTMLElement | null>(null);
  const [isOnline, setIsOnline] = useState(() => typeof navigator === "undefined" || navigator.onLine);
  const [reminders, setReminders] = useState<LearningReminder[]>([]);
  const [desktopNotifications, setDesktopNotifications] = useState(() => {
    if (typeof window === "undefined" || !("Notification" in window)) return false;
    return window.localStorage.getItem("learning-workstation.desktop-notifications") === "enabled" && window.Notification.permission === "granted";
  });
  const [backgroundPushEnabled, setBackgroundPushEnabled] = useState(() => (
    typeof window !== "undefined" && window.localStorage.getItem("learning-workstation.background-push") === "enabled"
  ));
  const [notificationPermission, setNotificationPermission] = useState<NotificationPermission>(() => (
    typeof window !== "undefined" && "Notification" in window ? window.Notification.permission : "default"
  ));
  const reminderIdsRef = useRef<Set<string> | null>(null);
  const desktopNotificationsRef = useRef(desktopNotifications);

  useEffect(() => {
    if (!assistantOpen) return;
    const releaseScrollLock = acquireDocumentScrollLock();
    assistantCloseRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setAssistantOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(assistantDrawerRef.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), textarea:not(:disabled), input:not(:disabled), select:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
      ) ?? []).filter(element => element.getClientRects().length > 0);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      releaseScrollLock();
      if (assistantTriggerRef.current?.isConnected) assistantTriggerRef.current.focus();
    };
  }, [assistantOpen]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("learning-workstation.theme", theme);
  }, [theme]);

  useEffect(() => {
    window.localStorage.setItem("learning-workstation.sidebar", sidebarPinned ? "pinned" : "compact");
  }, [sidebarPinned]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 860px)");
    const syncMode = (event: MediaQueryListEvent | MediaQueryList) => {
      setMobileNavigationMode(event.matches);
      if (!event.matches) setMobileNavOpen(false);
    };
    syncMode(media);
    media.addEventListener("change", syncMode);
    return () => media.removeEventListener("change", syncMode);
  }, []);

  useEffect(() => {
    const domain = navigationDomains.find(candidate => candidate.items.some(item => item.id === activeView));
    if (domain) setSelectedDomainId(domain.id);
  }, [activeView]);

  useEffect(() => { desktopNotificationsRef.current = desktopNotifications; }, [desktopNotifications]);

  useEffect(() => {
    let cancelled = false;
    async function reconcileBackgroundPushState() {
      if (window.localStorage.getItem("learning-workstation.background-push") !== "enabled") return;
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        window.localStorage.removeItem("learning-workstation.background-push");
        if (!cancelled) setBackgroundPushEnabled(false);
        return;
      }
      try {
        const registration = await navigator.serviceWorker.getRegistration();
        if (!registration) return;
        const subscription = await registration?.pushManager.getSubscription();
        if (!subscription && !cancelled) {
          window.localStorage.removeItem("learning-workstation.background-push");
          setBackgroundPushEnabled(false);
        }
      } catch {
        // Keep the local state on a transient browser API failure.
      }
    }
    void reconcileBackgroundPushState();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const online = () => setIsOnline(true);
    const offline = () => setIsOnline(false);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => { window.removeEventListener("online", online); window.removeEventListener("offline", offline); };
  }, []);

  async function loadReminders(announceNew = false) {
    try {
      const next = (await api.reminders()).reminders;
      const previousIds = reminderIdsRef.current;
      const newReminders = announceNew && previousIds
        ? next.filter(item => item.status === "pending" && !previousIds.has(item.id))
        : [];
      reminderIdsRef.current = new Set(next.map(item => item.id));
      setReminders(next);
      if (newReminders.length && desktopNotificationsRef.current && "Notification" in window && window.Notification.permission === "granted") {
        newReminders.slice(0, 3).forEach(item => {
          new window.Notification(item.title, { body: item.detail, tag: `learning-reminder-${item.id}` });
        });
      }
    } catch {
      setReminders([]);
    }
  }

  async function refresh() {
    try {
      const [data, health] = await Promise.all([api.dashboard(), api.modelHealth()]);
      setDashboard(data);
      setModel(health);
      setDashboardStatus("ready");
      setDashboardLoadError("");
    }
    catch (e) {
      const message = getApiErrorMessage(e);
      setDashboardStatus("error");
      setDashboardLoadError(message);
      setError(message);
    }
    await loadReminders();
  }
  async function refreshReminderList() {
    try { await api.refreshReminders(); await loadReminders(true); setNotice("学习提醒已更新。"); } catch (e) { setError(getApiErrorMessage(e)); }
  }
  async function enableDesktopNotifications() {
    if (!("Notification" in window)) {
      setError("当前浏览器不支持桌面提醒，请使用页面内提醒。");
      return;
    }
    const permission = await window.Notification.requestPermission();
    setNotificationPermission(permission);
    if (permission === "granted") {
      window.localStorage.setItem("learning-workstation.desktop-notifications", "enabled");
      setDesktopNotifications(true);
      setNotice("桌面提醒已启用。");
    } else if (permission === "denied") {
      setError("桌面提醒权限已被浏览器拒绝，仍可使用页面内提醒。");
    }
  }
  function disableDesktopNotifications() {
    window.localStorage.removeItem("learning-workstation.desktop-notifications");
    setDesktopNotifications(false);
    setNotice("桌面提醒已关闭，页面内提醒仍会保留。");
  }
  function decodeBase64Url(value: string): ArrayBuffer {
    const padded = `${value}${"=".repeat((4 - value.length % 4) % 4)}`.replace(/-/g, "+").replace(/_/g, "/");
    const binary = window.atob(padded);
    const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
    return bytes.buffer as ArrayBuffer;
  }
  async function enableBackgroundPush() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      setError("当前浏览器不支持后台推送，请使用页面内提醒。");
      return;
    }
    try {
      const config = await api.pushConfig();
      if (!config.enabled || !config.public_key) {
        setError("后台推送尚未配置 VAPID 密钥，仍可使用页面内提醒。");
        return;
      }
      const registration = await navigator.serviceWorker.getRegistration();
      if (!registration) {
        setError("请使用生产版 PWA 后再启用后台推送。");
        return;
      }
      const permission = await window.Notification.requestPermission();
      if (permission !== "granted") {
        setError("浏览器未授予通知权限，后台推送未启用。");
        return;
      }
      const subscription = await registration.pushManager.getSubscription()
        ?? await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: decodeBase64Url(config.public_key) });
      const json = subscription.toJSON();
      if (!json.endpoint || !json.keys?.p256dh || !json.keys.auth) throw new Error("浏览器未返回完整推送订阅信息");
      await api.registerPushSubscription({ endpoint: json.endpoint, p256dh: json.keys.p256dh, auth: json.keys.auth, expiration_time: json.expirationTime });
      window.localStorage.setItem("learning-workstation.background-push", "enabled");
      setBackgroundPushEnabled(true);
      setNotice("后台推送已启用。");
    } catch (e) { setError(getApiErrorMessage(e)); }
  }
  async function disableBackgroundPush() {
    try {
      const registration = await navigator.serviceWorker.getRegistration();
      const subscription = await registration?.pushManager.getSubscription();
      if (subscription?.endpoint) await api.unregisterPushSubscription(subscription.endpoint);
      await subscription?.unsubscribe();
      window.localStorage.removeItem("learning-workstation.background-push");
      setBackgroundPushEnabled(false);
      setNotice("后台推送已关闭。");
    } catch (e) { setError(getApiErrorMessage(e)); }
  }
  async function testBackgroundPush() {
    try {
      const preview = await api.testPush(false);
      if (!preview.requires_confirmation || !window.confirm("发送一条后台推送测试通知？")) return;
      const result = await api.testPush(true);
      setNotice(`后台推送测试已发送：${String(result.sent ?? 0)} 个订阅。`);
    } catch (e) { setError(getApiErrorMessage(e)); }
  }
  async function acknowledgeReminder(reminder: LearningReminder) {
    try { await api.acknowledgeReminder(reminder.id); setReminders(current => current.filter(item => item.id !== reminder.id)); } catch (e) { setError(getApiErrorMessage(e)); }
  }
  async function runGlobalSearch(event: FormEvent) {
    event.preventDefault();
    const query = searchQuery.trim();
    if (!query) { setSearchResults(null); return; }
    setSearching(true);
    try { setSearchResults(await api.globalSearch(query)); }
    catch (e) { setError(getApiErrorMessage(e)); }
    finally { setSearching(false); }
  }

  async function downloadReadableExport(format: "md" | "txt" | "html") {
    try {
      const blob = await api.readableExportBlob(format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `learning-workstation.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
      setNotice(`已导出 ${format.toUpperCase()} 阅读版。`);
    } catch (error) {
      setError(getApiErrorMessage(error));
    }
  }
  useEffect(() => {
    void refresh();
    api.setupStatus().then(setSetup).catch(() => undefined);
    const refreshTimer = window.setInterval(() => { void loadReminders(true); }, 60_000);
    const refreshOnFocus = () => { void loadReminders(true); };
    window.addEventListener("focus", refreshOnFocus);
    return () => { window.clearInterval(refreshTimer); window.removeEventListener("focus", refreshOnFocus); };
  }, []);

  useEffect(() => {
    if (!mobileNavigationMode || !mobileNavOpen) return;
    const releaseScrollLock = acquireDocumentScrollLock();
    const focusTarget = navigationRef.current?.querySelector<HTMLElement>('[aria-current="page"]')
      ?? navigationRef.current?.querySelector<HTMLElement>('button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])');
    focusTarget?.focus();
    const containNavigationFocus = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileNavOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = navigationRef.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", containNavigationFocus);
    return () => {
      document.removeEventListener("keydown", containNavigationFocus);
      releaseScrollLock();
      mobileNavToggleRef.current?.focus();
    };
  }, [mobileNavigationMode, mobileNavOpen]);

  async function addTask(event: FormEvent) {
    event.preventDefault(); if (!taskTitle.trim()) return; setSaving(true);
    const now = new Date();
    const dueDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    try { await api.createTask({ title: taskTitle.trim(), estimated_minutes: 30, due_date: dueDate }); setTaskTitle(""); setNotice("任务已添加。"); await refresh(); }
    catch (e) { setError(getApiErrorMessage(e)); } finally { setSaving(false); }
  }
  async function addLog(event: FormEvent) {
    event.preventDefault(); if (!logText.trim()) return; setSaving(true);
    try { await api.createDailyLog(logText.trim()); setLogText(""); setNotice("学习记录原文已保存。"); await refresh(); }
    catch (e) { setError(getApiErrorMessage(e)); } finally { setSaving(false); }
  }
  async function toggleTask(task: Dashboard["today_tasks"][number]) {
    setUpdatingTaskId(task.id);
    try {
      const completed = task.status === "completed";
      if (completed) {
        await api.updateTask(task.id, { status: "not_started" });
        setNotice("任务已重新打开。");
      } else {
        setActiveView("plan");
        setNotice("请到学习计划中写下完成情况。");
      }
      await refresh();
    } catch (e) { setError(getApiErrorMessage(e)); }
    finally { setUpdatingTaskId(null); }
  }
  const navigate = (view: string, suppressSidebarHover = false) => {
    setActiveView(view);
    setMobileNavOpen(false);
    setSidebarHoverSuppressed(suppressSidebarHover);
    if (suppressSidebarHover && document.activeElement instanceof HTMLElement) document.activeElement.blur();
  };
  const openSetupCenter = () => {
    setSelectedDomainId("system");
    navigate("setup");
  };
  const openAssistant = () => {
    assistantTriggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setMobileNavOpen(false);
    setAssistantOpen(true);
  };
  const dismissSetupReminder = () => {
    setSetupReminderDismissed(true);
    window.sessionStorage.setItem("learning-workstation.setup-reminder", "dismissed");
  };
  const modelSummary = !model
    ? "模型检查中"
    : model.local.available
      ? "本地模型在线"
      : model.cloud.available
        ? "云端模型在线"
        : model.cloud.enabled && model.cloud.configured
           ? "模型暂不可用"
           : "模型未启用";
  const modelAvailable = Boolean(model?.local.available || model?.cloud.available);
  const title: Record<string, string> = { dashboard: "今日总览", coach: "学习伙伴", teaching: "教学闭环", interview: "模拟面试", jobAnalysis: "岗位分析", modelTasks: "模型任务", plugins: "插件系统", operations: "运行与审计", plan: "学习计划", weeklyPlan: "周计划", projects: "项目工作台", practice: "练习与沙箱", reviews: "今日复习", reviewCards: "复习卡片", logs: "今日记录", notes: "笔记库", knowledge: "知识地图", setup: "初始化设置", imports: "文件导入", capabilities: "能力画像", restore: "备份恢复", analytics: "统计复盘", reports: "学习报告" };
  const pageContainerModes: Partial<Record<string, PageContainerMode>> = {
    dashboard: "wide",
    logs: "reading",
    notes: "wide",
    setup: "work",
    plan: "work",
    imports: "work",
    knowledge: "fluid",
    operations: "work",
  };
  const pageContainerMode = pageContainerModes[activeView] ?? "fluid";
  const pageIdentity = pageIdentityContracts[activeView] ?? { mode: "implicit" as const };
  const selectedDomain = navigationDomains.find(domain => domain.id === selectedDomainId) ?? navigationDomains[0];
  const currentDomain = navigationDomains.find(domain => domain.items.some(item => item.id === activeView)) ?? navigationDomains[0];
  const assistantSuggestion = dashboard.agent_suggestions?.[0]
    ? { title: dashboard.agent_suggestions[0].title, detail: dashboard.agent_suggestions[0].detail }
    : dashboard.today_tasks[0]
      ? { title: "先推进今天这一项", detail: dashboard.today_tasks[0].title }
      : null;

  return <div className={`app-shell studyforge-shell ${sidebarPinned ? "sidebar-is-pinned" : "sidebar-is-compact"} ${sidebarHoverSuppressed ? "sidebar-hover-suppressed" : ""}`} data-theme={theme}>
    <aside ref={navigationRef} id="primary-navigation" className={`sidebar ${mobileNavOpen ? "mobile-open" : ""} ${sidebarPinned ? "is-pinned" : ""}`} aria-label="主导航" aria-hidden={assistantOpen || (mobileNavigationMode && !mobileNavOpen) ? true : undefined} aria-modal={mobileNavigationMode && mobileNavOpen ? true : undefined} role={mobileNavigationMode && mobileNavOpen ? "dialog" : undefined} inert={assistantOpen || (mobileNavigationMode && !mobileNavOpen) ? true : undefined} onPointerLeave={() => setSidebarHoverSuppressed(false)}>
      <div className="domain-rail">
        <div className="brand"><span className="brand-mark" aria-hidden="true">学</span><span className="sr-only">学习工作站</span></div>
        <nav aria-label="学习任务域">
          {navigationDomains.map(domain => <button type="button" key={domain.id} className="domain-button" aria-label={domain.label} aria-pressed={selectedDomain.id === domain.id} aria-current={currentDomain.id === domain.id ? "location" : undefined} title={`${domain.label}：${domain.description}`} onClick={() => { setSelectedDomainId(domain.id); setSidebarHoverSuppressed(false); }}><Glyph name={domain.icon} /><span>{domain.label}</span></button>)}
        </nav>
        <button type="button" className="domain-settings" aria-label="打开初始化设置" title="初始化设置" onClick={openSetupCenter}><Glyph name="settings" /></button>
      </div>
      <div className="domain-menu">
        <header><div><strong>{selectedDomain.label}</strong><p>{selectedDomain.description}</p></div><button type="button" className="sf-button sf-button--secondary sf-button--icon sidebar-pin" aria-label={sidebarPinned ? "取消固定导航" : "固定展开导航"} title={sidebarPinned ? "恢复悬停展开" : "固定展开导航"} aria-pressed={sidebarPinned} onClick={event => { const pointerActivation = event.detail > 0; setSidebarPinned(current => !current); setSidebarHoverSuppressed(pointerActivation); if (pointerActivation && document.activeElement instanceof HTMLElement) document.activeElement.blur(); }}><Glyph name="arrow-right" /></button><button type="button" className="sf-button sf-button--secondary sf-button--icon navigation-mobile-close" aria-label="关闭导航" onClick={() => setMobileNavOpen(false)}><Glyph name="arrow-right" /></button></header>
        <nav aria-label={`${selectedDomain.label}工作区`}>
          {selectedDomain.items.map(item => <button type="button" key={item.id} className="nav-item" aria-current={activeView === item.id ? "page" : undefined} onClick={event => navigate(item.id, event.detail > 0)}><Glyph name={item.icon} /><span>{item.label}</span></button>)}
        </nav>
        <div className="sidebar-bottom"><div className="privacy"><span className="status-dot" /><span>本地数据模式<small>学习资料默认不上传</small></span></div></div>
      </div>
    </aside>
    <div className={`mobile-nav-backdrop ${mobileNavOpen ? "visible" : ""}`} aria-hidden="true" onClick={() => setMobileNavOpen(false)} />
       <main className="main-content" aria-hidden={assistantOpen || (mobileNavigationMode && mobileNavOpen) ? true : undefined} inert={assistantOpen || (mobileNavigationMode && mobileNavOpen) ? true : undefined}>
        <header className="topbar">
          <div className="topbar-heading">
            <button ref={mobileNavToggleRef} type="button" className="sf-button sf-button--tertiary sf-button--icon mobile-nav-toggle" aria-label={mobileNavOpen ? "关闭导航" : "打开导航"} aria-expanded={mobileNavOpen} aria-controls="primary-navigation" onClick={() => setMobileNavOpen(current => !current)}><Glyph name="menu" /></button>
            <div className="page-identity" aria-hidden={pageIdentity.mode === "implicit" ? undefined : true}><span>{currentDomain.label} / {title[activeView]}</span>{pageIdentity.mode === "implicit" ? <h1 className="toolbar-route-title">{title[activeView]}</h1> : <strong className="toolbar-route-title">{title[activeView]}</strong>}</div>
          </div>
          <div className="top-actions">
            <form className="global-search sf-composite-field" onSubmit={runGlobalSearch}>
              <input className="sf-field" aria-label="全局搜索" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="搜索任务、笔记、项目" />
              <button type="submit" className="sf-button sf-button--secondary" disabled={searching || !searchQuery.trim()}>{searching ? "搜索中" : "搜索"}</button>
            </form>
            <div className="top-status-cluster sf-status-cluster" aria-label="系统状态">
              <span className={`sf-status-text ${isOnline ? "online" : "offline"}`} role="status" aria-label={isOnline ? "本地服务在线" : "离线，暂停写入"}><i aria-hidden="true" />{isOnline ? "本地在线" : "离线"}</span>
              <span className="top-model-status-item"><span className={`sf-status-text ${modelAvailable ? "available" : "unavailable"}`} role="status" aria-label={`模型状态：${modelSummary}`} title={modelSummary}><i aria-hidden="true" />{modelSummary}</span></span>
            </div>
            <details className="export-menu">
              <summary className="sf-button sf-button--tertiary" aria-label="导出学习数据" title="导出学习数据"><Glyph name="download" /><span>导出</span></summary>
              <div className="export-menu-content"><button type="button" className="ghost-button" disabled={!isOnline} onClick={async () => { try { downloadJson(`learning-workstation-${new Date().toISOString().slice(0, 10)}.json`, await api.exportData()); setNotice("数据已导出。"); } catch (e) { setError(getApiErrorMessage(e)); } }}>完整 JSON</button><button type="button" className="ghost-button" disabled={!isOnline} onClick={() => void downloadReadableExport("md")}>Markdown</button><button type="button" className="ghost-button" disabled={!isOnline} onClick={() => void downloadReadableExport("txt")}>TXT</button><button type="button" className="ghost-button" disabled={!isOnline} onClick={() => void downloadReadableExport("html")}>HTML</button></div>
            </details>
            <button type="button" className="sf-button sf-button--tertiary sf-button--icon theme-toggle" aria-label={theme === "light" ? "切换到深色主题" : "切换到浅色主题"} title={theme === "light" ? "切换到深色主题" : "切换到浅色主题"} onClick={() => setTheme(current => current === "light" ? "dark" : "light")}><Glyph name={theme === "light" ? "moon" : "sun"} /></button>
            <button type="button" className="sf-button sf-button--tertiary avatar top-agent-entry" aria-label="打开八奈见杏菜学习伙伴" title="打开八奈见杏菜学习伙伴" onClick={openAssistant}><AnnaArt variant="face" alt="" /><span>杏菜</span></button>
          </div>
        </header>
      <PageContainer mode={pageContainerMode}>
      {pageIdentity.mode !== "implicit" && activeView !== "analytics" && <PageHeader mode={pageIdentity.mode} title={title[activeView]} description={pageIdentity.description} metadata={activeView === "setup" ? (setup?.completed ? "基础设置已完成" : "基础设置尚未完成") : undefined} titleId={`${activeView}-page-title`} />}
      {notice && <div className="notice success" role="status" aria-live="polite">{notice}<button type="button" aria-label="关闭成功提示" onClick={() => setNotice("")}>×</button></div>}{error && <div className="notice error" role="alert">{error}<button type="button" aria-label="关闭错误提示" onClick={() => setError("")}>×</button></div>}
      {activeView === "dashboard" && setup?.requires_onboarding && !setupReminderDismissed && <aside className="setup-reminder sf-notice-surface sf-notice-surface--warning" aria-label="初始化设置提醒"><span className="setup-reminder-mark" aria-hidden="true" /><div><strong>完成学习工作站的基础设置</strong><p>补充学习画像并确认首版学习主线；现在跳过也不会影响其他功能。</p></div><div className="setup-reminder-actions"><button type="button" className="text-button" onClick={dismissSetupReminder}>以后再说</button><button type="button" className="primary-button" onClick={openSetupCenter}>开始设置</button></div></aside>}
      {searchResults && <section className="search-results sf-open-section"><div className="sf-surface-header"><div><h2 className="sf-section-title">搜索结果</h2><p className="sf-surface-description">找到 {searchResults.total} 项 · 点击即可打开对应页面</p></div><button type="button" className="ghost-button" aria-label="关闭搜索结果" onClick={() => setSearchResults(null)}>关闭</button></div>{searchResults.results.length ? <div className="search-result-list">{searchResults.results.map(result => <button className="search-result-row" key={`${result.kind}-${result.id}`} onClick={() => { setActiveView(result.route); setSearchResults(null); }}><span className="search-kind">{result.kind}</span><span><strong>{result.title}</strong><small>{result.subtitle}</small><em>{result.snippet}</em></span><i>打开</i></button>)}</div> : <div className="empty"><p>没有找到相关内容。</p></div>}</section>}
      {activeView === "reports" && <ReportsWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "coach" && <section className="coach-page"><AgentChat /><AgentChangeWorkspace onNotice={setNotice} onError={setError} /></section>}
      {activeView === "teaching" && <TeachingWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "interview" && <InterviewWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "jobAnalysis" && <JobAnalysisWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "modelTasks" && <ModelTaskWorkspace />}
      {activeView === "plugins" && <PluginWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "operations" && <OperationsWorkspace onError={setError} />}
      {activeView === "setup" && <SetupCenterWorkspace setup={setup} onSetupChange={setSetup} onNotice={setNotice} onError={setError} onNavigate={navigate} />}
      {activeView === "weeklyPlan" && <WeeklyPlanWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "projects" && <><ProjectsWorkspace onNotice={setNotice} onError={setError} /><ProjectMetadataWorkspace onNotice={setNotice} onError={setError} /></>}
      {activeView === "practice" && <PracticeWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "reviews" && <><ReviewScheduleWorkspace onNotice={setNotice} onError={setError} /><ReviewWorkspace onNotice={setNotice} onError={setError} /></>}
      {activeView === "reviewCards" && <ReviewCardsWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "restore" && <RestoreWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "logs" && <LogWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "notes" && <NotesWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "knowledge" && <KnowledgeWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "imports" && <ImportsWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "capabilities" && <CapabilitiesWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "analytics" && <AnalyticsWorkspace onNotice={setNotice} onError={setError} />}
      {activeView === "plan" && <PlanWorkspace onNotice={setNotice} onError={setError} />}
       {activeView === "dashboard" && dashboardStatus === "loading" && <DashboardLoading />}
       {activeView === "dashboard" && dashboardStatus === "error" && <DashboardLoadError message={dashboardLoadError} onRetry={() => { setDashboardStatus("loading"); void refresh(); }} />}
        {activeView === "dashboard" && dashboardStatus === "ready" && <HomeWorkstation
         dashboard={dashboard}
         taskTitle={taskTitle}
         logText={logText}
         saving={saving}
         updatingTaskId={updatingTaskId}
         reminders={reminders}
         desktopNotifications={desktopNotifications}
         backgroundPushEnabled={backgroundPushEnabled}
         notificationPermission={notificationPermission}
         onTaskTitleChange={setTaskTitle}
         onLogTextChange={setLogText}
         onAddTask={addTask}
         onAddLog={addLog}
         onToggleTask={task => void toggleTask(task)}
         onNavigate={navigate}
         onOpenAssistant={openAssistant}
         onEnableDesktopNotifications={() => void enableDesktopNotifications()}
         onDisableDesktopNotifications={disableDesktopNotifications}
         onEnableBackgroundPush={() => void enableBackgroundPush()}
         onDisableBackgroundPush={() => void disableBackgroundPush()}
         onTestBackgroundPush={() => void testBackgroundPush()}
         onRefreshReminders={() => void refreshReminderList()}
          onAcknowledgeReminder={reminder => void acknowledgeReminder(reminder)}
        />}
        </PageContainer>
  </main>
  {assistantOpen && <div className="companion-slot" data-state="open"><div className="companion-slot__backdrop" aria-hidden="true" onClick={() => setAssistantOpen(false)} /><aside ref={assistantDrawerRef} className="companion-slot__drawer" aria-labelledby="assistant-title" role="dialog" aria-modal="true"><div className="companion-slot__header"><div className="anna-identity"><span className="anna-identity__avatar" aria-hidden="true"><AnnaArt variant="face" alt="" /></span><div><strong id="assistant-title">八奈见杏菜</strong><small>学习伙伴 · 对话保存在本机</small></div></div><button ref={assistantCloseRef} type="button" className="sf-button sf-button--tertiary sf-button--icon close-button companion-slot__close" aria-label="关闭学习伙伴" onClick={() => setAssistantOpen(false)}>×</button></div>{assistantSuggestion && <div className="anna-notice"><strong>{assistantSuggestion.title}</strong><p>{assistantSuggestion.detail}</p></div>}<AgentChat personaName="八奈见杏菜" persona="anna" /></aside></div>}
  </div>;
}
function DashboardLoading() {
  return <section className="dashboard-state sf-open-section" role="status" aria-live="polite">
    <div className="dashboard-state-mark" aria-hidden="true" />
    <div><strong>正在整理今天的学习内容</strong><p>正在读取任务和最近的学习记录。</p></div>
  </section>;
}

function DashboardLoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <section className="dashboard-state dashboard-state-error sf-notice-surface sf-notice-surface--error" role="alert">
    <div className="dashboard-state-mark" aria-hidden="true">!</div>
    <div><strong>今天的学习现场暂时没有打开</strong><p>{message || "读取学习数据时遇到问题。"}</p><button type="button" className="primary-button" onClick={onRetry}>重新读取</button></div>
  </section>;
}
function AnnaArt({ variant, alt }: { variant: "main" | "face"; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <span className={`anna-art-fallback ${variant}`} aria-label={alt || "八奈见杏菜"}>杏</span>;
  const faceSources = ["/characters/anna/face-first-upscaled.png", "/characters/anna/face-2-upscaled.png"];
  return <img className={`anna-art ${variant}`} src={variant === "main" ? "/characters/anna/main-upscaled-x4.png" : faceSources[annaFaceVariant] ?? faceSources[0]} alt={alt} onError={() => setFailed(true)} />;
}

function Glyph({ name }: { name: string }) {
  const paths: Record<string, string> = { home: "M3 10.5 12 3l9 7.5M5.5 9v11h13V9M9 20v-6h6v6", spark: "m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3", sun: "M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8", moon: "M19 15.5A8 8 0 0 1 8.5 5 7.5 7.5 0 1 0 19 15.5", model: "M4 5h16v14H4zM8 9h8M8 13h5", activity: "M4 12h3l2-6 4 12 2-6h5", check: "m5 12 4 4L19 6", grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z", clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0-9-9zm0 4v5l3 2", document: "M6 3h9l3 3v15H6zM15 3v4h4M9 12h6M9 16h6", note: "M5 4h14v16H5zM8 8h8M8 12h8M8 16h5", map: "M4 6l5-2 6 2 5-2v14l-5 2-6-2-5 2zM9 4v14M15 6v14", download: "M12 4v10m0 0 4-4m-4 4-4-4M5 20h14", target: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm0 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8", upload: "M12 16V5m0 0L8 9m4-4 4 4M5 19h14", chart: "M5 19V9M12 19V5M19 19v-7", settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0 -8zM4 12h2m12 0h2M12 4v2m0 12v2", book: "M5 4h10a4 4 0 0 1 4 4v12H9a4 4 0 0 0-4-4zM9 4v12", calendar: "M6 4v3m12-3v3M4 9h16M5 6h14v14H5z", cards: "M5 5h14v10H5zM8 9h8M8 12h5M8 19h11", menu: "M4 7h16M4 12h16M4 17h16" };
      return <svg className="nav-glyph" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d={name === "arrow-right" ? "M5 12h13m-5-5 5 5-5 5" : paths[name] ?? paths.activity} /></svg>;
}
