import { chromium } from "playwright";
import { dismissOnboarding } from "./e2e-onboarding-helper.mjs";

const baseURL = process.env.BASE_URL ?? "http://127.0.0.1:5173";
const apiBaseURL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
const executablePath = process.env.PLAYWRIGHT_EXECUTABLE ?? "C:/Users/Hypix/AppData/Local/ms-playwright/chromium-1208/chrome-win64/chrome.exe";
const results = [];

function record(name, passed, detail = "") {
  results.push({ name, passed, detail });
  console.log(`${passed ? "PASS" : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
}

async function visibleText(page) {
  return (await page.locator("body").innerText()).replace(/\\s+/g, " ").trim();
}

const domainByWorkspace = {
  "今日总览": "今天", "今日记录": "今天",
  "学习计划": "规划", "周计划": "规划", "项目工作台": "规划", "岗位分析": "规划", "模拟面试": "规划",
  "练习与沙箱": "学习", "笔记库": "学习", "知识地图": "学习", "教学闭环": "学习", "学习伙伴": "学习",
  "今日复习": "回看", "复习卡片": "回看", "能力画像": "回看", "学习报告": "回看", "统计复盘": "回看",
  "初始化设置": "系统", "文件导入": "系统", "备份恢复": "系统", "模型任务": "系统", "插件系统": "系统", "运行与审计": "系统",
};

async function navigateTo(page, workspace) {
  const mobileToggle = page.getByRole("button", { name: "打开导航", exact: true });
  if (await mobileToggle.count() && await mobileToggle.isVisible()) await mobileToggle.click();
  await page.getByRole("button", { name: domainByWorkspace[workspace], exact: true }).click();
  await page.getByRole("button", { name: workspace, exact: true }).click();
  await page.waitForTimeout(250);
}

const browser = await chromium.launch({ headless: true, executablePath });
const desktop = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const consoleErrors = [];
desktop.on("console", message => {
  if (message.type() === "error" && !message.text().includes("/favicon.ico")) consoleErrors.push(message.text());
});
desktop.on("pageerror", error => consoleErrors.push(error.message));
desktop.on("requestfailed", request => {
  if (!request.url().includes("/favicon.ico")) consoleErrors.push(`${request.method()} ${request.url()} — ${request.failure()?.errorText ?? "request failed"}`);
});

try {
  await desktop.goto(baseURL, { waitUntil: "domcontentloaded" });
  await desktop.waitForTimeout(800);
  const setupResponse = await desktop.request.get(`${apiBaseURL}/api/setup/status`);
  const setupPayload = await setupResponse.json();
  record("首次启动状态接口", setupResponse.ok(), `GET /api/setup/status → ${setupResponse.status()}`);
  const runtimeResponse = await desktop.request.get(`${apiBaseURL}/api/runtime/status`);
  const runtimePayload = await runtimeResponse.json();
  record("后台调度状态接口", runtimeResponse.ok() && Boolean(runtimePayload.scheduler), `GET /api/runtime/status → ${runtimeResponse.status()}`);
  const modelHealthResponse = await desktop.request.get(`${apiBaseURL}/api/models/health`);
  const modelHealthPayload = await modelHealthResponse.json();
  record("模型健康状态接口", modelHealthResponse.ok() && Boolean(modelHealthPayload.local) && ["enabled", "configured", "available"].every(key => Object.prototype.hasOwnProperty.call(modelHealthPayload.cloud ?? {}, key)), "本地/云端三态健康字段可见");
  for (const format of ["md", "txt", "html"]) {
    const exportResponse = await desktop.request.get(`${apiBaseURL}/api/exports/${format}`);
    record(`完整${format.toUpperCase()}导出`, exportResponse.ok(), `GET /api/exports/${format} → ${exportResponse.status()}`);
  }
  const onboardingVisible = await desktop.getByLabel("初始化设置提醒").count() > 0;
  const blockingSetupDialog = await desktop.getByRole("dialog", { name: /首次启动|初始化设置/ }).count() > 0;
  record("非阻塞初始化提醒", onboardingVisible === Boolean(setupPayload.requires_onboarding) && !blockingSetupDialog, setupPayload.requires_onboarding ? "首页可用，提醒可稍后处理" : "已完成初始化，不重复提醒");
  if (await dismissOnboarding(desktop)) {
    await navigateTo(desktop, "今日总览");
  }
  record("首页加载", (await desktop.locator("h1").first().textContent())?.includes("今日总览"), await visibleText(desktop).then(text => text.includes("今天先完成什么") ? "今日任务与学习手记可见" : "缺少今日工作台"));
  await desktop.mouse.move(1200, 900);
  await desktop.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
  await desktop.waitForTimeout(260);
  const compactSidebarWidth = await desktop.locator(".sidebar").evaluate(element => element.getBoundingClientRect().width);
  await desktop.locator(".sidebar").hover();
  await desktop.waitForTimeout(260);
  const hoverSidebarWidth = await desktop.locator(".sidebar").evaluate(element => element.getBoundingClientRect().width);
  await desktop.getByRole("button", { name: "固定展开导航", exact: true }).click();
  await desktop.mouse.move(1200, 900);
  const pinnedSidebarWidth = await desktop.locator(".sidebar").evaluate(element => element.getBoundingClientRect().width);
  await desktop.getByRole("button", { name: "取消固定导航", exact: true }).click();
  await desktop.mouse.move(1200, 900);
  await desktop.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
  await desktop.waitForTimeout(260);
  const restoredSidebarWidth = await desktop.locator(".sidebar").evaluate(element => element.getBoundingClientRect().width);
  record("侧栏默认收窄、悬停展开与固定", compactSidebarWidth <= 80 && hoverSidebarWidth >= 290 && pinnedSidebarWidth >= 290 && restoredSidebarWidth <= 80, JSON.stringify({ compactSidebarWidth, hoverSidebarWidth, pinnedSidebarWidth, restoredSidebarWidth }));
  const directionContract = await desktop.evaluate(() => {
    const bodyStyle = getComputedStyle(document.body);
    const primaryStyle = getComputedStyle(document.querySelector(".home-focus-action"));
    const controls = [".global-search input", ".global-search button", ".connectivity-pill", ".model-pill", ".export-menu > summary", ".theme-toggle"].map(selector => {
      const element = document.querySelector(selector);
      const style = getComputedStyle(element);
      return { selector, tag: element.tagName, height: element.getBoundingClientRect().height, radius: style.borderRadius };
    });
    const avatar = document.querySelector(".avatar");
    return { fontSize: bodyStyle.fontSize, lineHeight: bodyStyle.lineHeight, primaryRadius: primaryStyle.borderRadius, controls, avatar: { height: avatar.getBoundingClientRect().height, radius: getComputedStyle(avatar).borderRadius }, statusTags: [document.querySelector(".connectivity-pill")?.tagName, document.querySelector(".model-pill")?.tagName] };
  });
  record("锁定设计方向合同", directionContract.fontSize === "15px" && directionContract.lineHeight === "24.75px" && directionContract.primaryRadius === "4px" && directionContract.controls.every(control => Math.abs(control.height - 38) < 1 && control.radius === "8px") && Math.abs(directionContract.avatar.height - 38) < 1 && directionContract.avatar.radius === "50%" && directionContract.statusTags.every(tag => tag === "SPAN"), JSON.stringify(directionContract));
  const homepageScene = await desktop.locator(".home-workstation").evaluate(element => {
    const workspace = element.querySelector(".home-workspace");
    const companion = element.querySelector(".home-companion");
    const rect = element.getBoundingClientRect();
    return { columns: getComputedStyle(element).gridTemplateColumns, bodyBackground: getComputedStyle(document.body).backgroundImage, companionBackground: getComputedStyle(companion).backgroundColor, characterVisible: Boolean(companion.querySelector(".home-anna-stage img")?.getBoundingClientRect().height), workspaceWidth: workspace.getBoundingClientRect().width, companionWidth: companion.getBoundingClientRect().width, bottom: rect.bottom };
  });
  record("首页桌面工作站分栏", homepageScene.bodyBackground === "none" && homepageScene.workspaceWidth > homepageScene.companionWidth && homepageScene.columns.split(" ").length >= 2, JSON.stringify(homepageScene));
  record("首页杏菜陪伴区可见", homepageScene.characterVisible && homepageScene.companionBackground !== "rgba(0, 0, 0, 0)", `Workstation bottom=${homepageScene.bottom}`);
  record("首页模型文案真实", !(await visibleText(desktop)).includes("等待 Ollama"), "未显示虚假的 Ollama 等待状态");

  const assistantTrigger = desktop.getByRole("button", { name: "打开八奈见杏菜学习伙伴" });
  await assistantTrigger.click();
  const assistantDialog = desktop.getByRole("dialog", { name: "八奈见杏菜" });
  const assistantOpenState = await assistantDialog.evaluate(element => ({ overflow: getComputedStyle(document.body).overflow, activeInside: element.contains(document.activeElement) }));
  record("助手抽屉锁定背景并聚焦", assistantOpenState.overflow === "hidden" && assistantOpenState.activeInside, JSON.stringify(assistantOpenState));
  const quickPrompt = assistantDialog.locator(".coach-quick-prompts button").first();
  if (await quickPrompt.count()) {
    await quickPrompt.click();
    record("助手快捷问题可点击", Boolean((await assistantDialog.getByLabel("发送给杏菜").inputValue()).trim()));
  } else {
    record("助手快捷问题可点击", false, "空会话未显示快捷问题");
  }
  await desktop.keyboard.press("Escape");
  record("助手 Escape 与焦点回收", await assistantDialog.count() === 0 && await desktop.evaluate(() => document.activeElement?.getAttribute("aria-label")) === "打开八奈见杏菜学习伙伴");
  await assistantTrigger.click();
  await desktop.getByRole("button", { name: "关闭学习伙伴" }).click();
  record("助手关闭后焦点回收", await desktop.evaluate(() => document.activeElement?.getAttribute("aria-label")) === "打开八奈见杏菜学习伙伴");

  const taskInput = desktop.locator("#task-input");
  if (await taskInput.count()) {
    const title = "完成一组 SQL 窗口函数练习";
    await taskInput.fill(title);
    const taskResponse = desktop.waitForResponse(response => response.url().endsWith("/api/tasks") && response.request().method() === "POST");
    await taskInput.press("Enter");
    const createdTask = await taskResponse;
    record("首页创建任务", createdTask.status() === 201, `POST /api/tasks → ${createdTask.status()}`);
  } else {
    record("首页创建任务", false, "未找到任务输入框");
  }

  const navChecks = [
    ["笔记库", "笔记库"],
    ["复习卡片", "复习卡片"],
    ["教学闭环", "教学闭环"],
    ["统计复盘", "统计复盘"],
    ["运行与审计", "运行与审计"],
  ];
  for (const [label, heading] of navChecks) {
    await navigateTo(desktop, label);
    record(`导航到${label}`, (await desktop.locator("h1").first().textContent())?.includes(heading));
  }

  await navigateTo(desktop, "文件导入");
  record("文件授权工作区", (await visibleText(desktop)).includes("文件导入") && (await visibleText(desktop)).includes("授权目录"));
  await navigateTo(desktop, "项目工作台");
  const projectSurface = await desktop.locator(".project-card, .project-metadata-workspace").evaluateAll(elements => elements.map(element => getComputedStyle(element).backgroundColor));
  record("项目工作台浅色层级", projectSurface.length > 0 && projectSurface.every(color => !["rgb(18, 26, 22)", "rgb(18, 27, 22)"].includes(color)), projectSurface.join(", "));
  await navigateTo(desktop, "今日总览");
  const dashboardTask = desktop.locator(".task-row", { hasText: "完成一组 SQL 窗口函数练习" });
  const tasksResponse = await desktop.request.get(`${apiBaseURL}/api/tasks`);
  const tasksPayload = await tasksResponse.json();
  const taskReturnedByApi = Array.isArray(tasksPayload) && tasksPayload.some(task => String(task.title) === "完成一组 SQL 窗口函数练习");
  record("首页任务列表刷新", await dashboardTask.count() > 0 || taskReturnedByApi, "后端返回的任务已确认保存；无 due_date 时驾驶舱不强制显示");

  await navigateTo(desktop, "学习计划");
  const planActionLayout = await desktop.locator(".plan-task-form > button").evaluate(element => ({ width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height, clientWidth: element.clientWidth, scrollWidth: element.scrollWidth }));
  record("计划任务操作按钮布局", planActionLayout.width >= 110 && planActionLayout.height < 60 && planActionLayout.scrollWidth <= planActionLayout.clientWidth + 2, JSON.stringify(planActionLayout));
  const planViewport = await desktop.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, width: window.innerWidth }));
  record("学习计划桌面视口", planViewport.scrollWidth <= planViewport.width + 1, JSON.stringify(planViewport));
  const planWorkbench = await desktop.locator(".plan-workspace .plan-task-form").evaluate(element => ({ borderRadius: getComputedStyle(element).borderRadius, background: getComputedStyle(element).backgroundColor, buttonHeight: element.querySelector("button")?.getBoundingClientRect().height ?? 0 }));
  record("学习计划工作台层级", planWorkbench.borderRadius !== "0px" && planWorkbench.buttonHeight >= 38, JSON.stringify(planWorkbench));
  const hierarchyGoal = "补齐数据库课程中的薄弱部分";
  await desktop.getByLabel("目标标题").fill(hierarchyGoal);
  const goalResponse = desktop.waitForResponse(response => response.url().endsWith("/api/goals") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "添加目标", exact: true }).click();
  const createdGoalResponse = await goalResponse;
  record("创建计划目标", createdGoalResponse.status() === 201, `POST /api/goals → ${createdGoalResponse.status()}`);
  const goalRow = desktop.locator(".plan-hierarchy-goal", { hasText: hierarchyGoal });
  await goalRow.getByRole("button", { name: "修改", exact: true }).click();
  await desktop.getByLabel("目标描述").fill("本周重点复习窗口函数和查询优化，并完成配套练习。");
  const goalPatch = desktop.waitForResponse(response => response.url().includes("/api/goals/") && response.request().method() === "PATCH");
  await desktop.getByRole("button", { name: "保存修改", exact: true }).click();
  const updatedGoalResponse = await goalPatch;
  const updatedGoalPayload = await updatedGoalResponse.json();
  record("编辑计划目标", updatedGoalResponse.status() === 200 && updatedGoalPayload.description === "本周重点复习窗口函数和查询优化，并完成配套练习。", `PATCH /api/goals → ${updatedGoalResponse.status()}`);
  const hierarchyStage = "窗口函数与查询优化";
  await desktop.getByLabel("阶段标题").fill(hierarchyStage);
  const stageResponse = desktop.waitForResponse(response => response.url().includes("/api/goals/") && response.url().endsWith("/stages") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "添加阶段", exact: true }).click();
  const createdStageResponse = await stageResponse;
  record("创建计划阶段", createdStageResponse.status() === 201, `POST /api/goals/:id/stages → ${createdStageResponse.status()}`);
  const stageRow = desktop.locator(".plan-hierarchy-stages .task-row", { hasText: hierarchyStage });
  await stageRow.getByRole("button", { name: "修改", exact: true }).click();
  await desktop.getByLabel("阶段标题").fill(`${hierarchyStage}（已调整）`);
  const stagePatch = desktop.waitForResponse(response => response.url().includes("/api/stages/") && response.request().method() === "PATCH");
  await desktop.getByRole("button", { name: "保存修改", exact: true }).click();
  const updatedStageResponse = await stagePatch;
  const updatedStagePayload = await updatedStageResponse.json();
  record("编辑计划阶段", updatedStageResponse.status() === 200 && updatedStagePayload.title === `${hierarchyStage}（已调整）`, `PATCH /api/stages → ${updatedStageResponse.status()}`);
  const impactTitle = "整理查询优化的练习错题";
  await desktop.getByLabel("任务标题").fill(impactTitle);
  const impactResponse = desktop.waitForResponse(response => response.url().endsWith("/api/tasks/impact-preview") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "加入前检查", exact: true }).click();
  const impactResult = await impactResponse;
  record("任务加入前检查", impactResult.status() === 200 && (await visibleText(desktop)).includes("加入前检查"), `POST /api/tasks/impact-preview → ${impactResult.status()}`);
  const confirmImpactResponse = desktop.waitForResponse(response => response.url().endsWith("/api/tasks") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "加入任务清单", exact: true }).click();
  const confirmedImpact = await confirmImpactResponse;
  const confirmedImpactPayload = await confirmedImpact.json();
  record("确认加入计划", confirmedImpact.status() === 201 && confirmedImpactPayload.title === impactTitle, `POST /api/tasks → ${confirmedImpact.status()}`);

  await navigateTo(desktop, "周计划");
  await desktop.locator(".weekly-plan-workspace").waitFor({ state: "visible" });
  const weeklyCopy = (await desktop.locator(".weekly-plan-workspace").innerText()).replace(/\s+/g, " ");
  record("周计划自然文案", weeklyCopy.includes("这一周怎么安排") && weeklyCopy.includes("这周最重要的一件事") && weeklyCopy.includes("本周要做的事") && !["周计划与周复盘", "完整的一周闭环", "可验收产出", "Agent 评价", "预计分钟", "完成率", "P3"].some(term => weeklyCopy.includes(term)), "周计划只使用学生能直接理解的安排与回看语言");
  const weeklyLayout = await desktop.locator(".weekly-plan-workspace").evaluate(element => ({
    sheetColumns: getComputedStyle(element.querySelector(".weekly-plan-sheet")).gridTemplateColumns,
    rhythmColumns: getComputedStyle(element.querySelector(".weekly-rhythm")).gridTemplateColumns,
    metricCards: element.querySelectorAll(".weekly-summary > div").length,
    taskVisible: [...element.querySelectorAll(".weekly-task-copy strong")].some(item => item.textContent?.includes("整理查询优化的练习错题")),
    overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
  }));
  record("周计划课表夹布局", weeklyLayout.sheetColumns.split(" ").length === 2 && weeklyLayout.rhythmColumns.split(" ").length === 2 && weeklyLayout.metricCards === 0 && weeklyLayout.taskVisible && !weeklyLayout.overflow, JSON.stringify(weeklyLayout));
  await desktop.getByLabel("本周目标").fill("弄懂窗口函数的边界情况");
  await desktop.getByLabel("本周产出").fill("完成两道窗口函数练习\n整理一页错题笔记");
  await desktop.getByLabel("周复盘").fill("先做例题再整理规则，理解得更快。");
  await desktop.getByLabel("本周阻塞").fill("连续学习时间不够，下周预留两个完整时段。");
  const weeklySaveResponse = desktop.waitForResponse(response => response.url().endsWith("/api/weekly-plans") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "保存这一周", exact: true }).click();
  const weeklySaveResult = await weeklySaveResponse;
  await desktop.getByText(/上次保存/).waitFor({ state: "visible" });
  record("保存这一周", weeklySaveResult.status() === 201 && (await visibleText(desktop)).includes("上次保存"), `POST /api/weekly-plans → ${weeklySaveResult.status()}`);
  const weeklyTask = desktop.locator(".weekly-task-item", { hasText: impactTitle });
  await weeklyTask.getByRole("button", { name: `记录完成情况：${impactTitle}`, exact: true }).click();
  const weeklyCompletionField = weeklyTask.getByRole("textbox", { name: `完成情况：${impactTitle}`, exact: true });
  record("周任务页面内完成表单", await weeklyCompletionField.count() === 1, "完成记录不再使用浏览器原生弹窗");
  await weeklyCompletionField.fill("完成了两道查询优化练习，并整理了窗口函数边界笔记。");
  const weeklyVerifyResponse = desktop.waitForResponse(response => /\/api\/tasks\/\d+\/verify$/.test(response.url()) && response.request().method() === "POST");
  await weeklyTask.getByRole("button", { name: "记为完成", exact: true }).click();
  const weeklyVerifyResult = await weeklyVerifyResponse;
  await desktop.locator(".weekly-task-item.completed", { hasText: impactTitle }).waitFor({ state: "visible" });
  record("记录周任务完成情况", weeklyVerifyResult.status() === 200 && await desktop.locator(".weekly-task-item.completed", { hasText: impactTitle }).count() === 1, `POST /api/tasks/:id/verify → ${weeklyVerifyResult.status()}`);

  const logText = "今天练习了窗口函数，排序范围的边界条件还需要再看一遍。";
  const logResponse = await desktop.request.post(`${apiBaseURL}/api/daily-logs`, { data: { raw_text: logText, extracted_topics: ["SQL 窗口函数"], confirm: true } });
  record("创建可编辑学习日志", logResponse.status() === 201, `POST /api/daily-logs → ${logResponse.status()}`);
  const logsRefresh = desktop.waitForResponse(response => response.url().endsWith("/api/daily-logs") && response.request().method() === "GET");
  await navigateTo(desktop, "今日记录");
  await logsRefresh;
  const logRow = desktop.locator(".log-row", { hasText: logText });
  await logRow.waitFor({ state: "visible" });
  await logRow.getByRole("button", { name: "修改", exact: true }).click();
  await desktop.getByLabel("今天的原始记录").fill(`${logText}-已修正`);
  const logPatch = desktop.waitForResponse(response => response.url().includes("/api/daily-logs/") && response.request().method() === "PATCH");
  await desktop.getByRole("button", { name: "保存修改", exact: true }).click();
  const updatedLogResponse = await logPatch;
  const updatedLogPayload = await updatedLogResponse.json();
  record("编辑已保存学习日志", updatedLogResponse.status() === 200 && updatedLogPayload.raw_text.endsWith("-已修正"), `PATCH /api/daily-logs/:id → ${updatedLogResponse.status()}`);

  await navigateTo(desktop, "笔记库");
  await desktop.getByRole("button", { name: "写新笔记", exact: true }).click();
  await desktop.getByLabel("笔记标题").fill("窗口函数易错点整理");
  await desktop.getByLabel("笔记内容").fill("第一版正文\n\n- 要点一\n- 要点二");
  await desktop.getByRole("button", { name: "保存笔记", exact: true }).click();
  await desktop.waitForTimeout(500);
  record("创建笔记", (await visibleText(desktop)).includes("笔记"));
  const notesCopy = await visibleText(desktop);
  record("笔记库自然文案", notesCopy.includes("把这篇笔记继续用起来") && !notesCopy.includes("Agent") && !notesCopy.includes("规则回退") && !notesCopy.includes("质量评分"), "写作主流程不暴露模型和内部评估词");

  const previewButton = desktop.getByRole("button", { name: "预览", exact: true });
  if (await previewButton.count()) {
    await previewButton.click();
    record("Markdown 预览", await desktop.locator(".markdown-body").count() > 0, "预览区域存在");
    const markdownColor = await desktop.locator(".markdown-body").evaluate(element => getComputedStyle(element).color);
    record("Markdown 浅色阅读层级", markdownColor !== "rgb(205, 216, 208)" && markdownColor !== "rgb(237, 243, 238)", markdownColor);
    await desktop.getByRole("button", { name: "编辑", exact: true }).click();
  } else {
    record("Markdown 预览", false, "未找到预览按钮");
  }

  const blogButton = desktop.getByRole("button", { name: "写成博客草稿", exact: true });
  if (await blogButton.count()) {
    await blogButton.click();
    await desktop.waitForTimeout(350);
    const blogPreviewVisible = (await visibleText(desktop)).includes("准备保存的博客草稿") && (await visibleText(desktop)).includes("只生成独立草稿");
    record("博客草稿预览", blogPreviewVisible, "预览阶段未写入原笔记");
    const confirmBlogButton = desktop.getByRole("button", { name: "另存为博客草稿", exact: true });
    if (await confirmBlogButton.count()) {
      await confirmBlogButton.click();
      await desktop.waitForTimeout(450);
      record("确认保存博客草稿", (await visibleText(desktop)).includes("博客草稿已另存"));
      const savedDrafts = desktop.getByText(/另存的博客草稿/).first();
      if (await savedDrafts.count()) await savedDrafts.click();
      const markdownExport = desktop.getByRole("button", { name: "Markdown", exact: true });
      if (await markdownExport.count()) {
        const download = desktop.waitForEvent("download");
        await markdownExport.first().click();
        const file = await download;
        record("博客草稿 Markdown 导出", file.suggestedFilename().endsWith(".md"));
      } else {
        record("博客草稿 Markdown 导出", false, "未找到导出按钮");
      }
    } else {
      record("确认保存博客草稿", false, "未找到确认保存按钮");
      record("博客草稿 Markdown 导出", false, "未进入已保存草稿列表");
    }
  } else {
    record("博客草稿预览", false, "未找到生成博客草稿按钮");
    record("确认保存博客草稿", false, "未找到生成入口");
    record("博客草稿 Markdown 导出", false, "未找到生成入口");
  }

  await navigateTo(desktop, "复习卡片");
  await desktop.getByRole("heading", { name: "今天复习什么", exact: true }).waitFor({ state: "visible" });
  const reviewCopy = await visibleText(desktop);
  record("复习卡片自然文案", reviewCopy.includes("今天的复习顺序") && reviewCopy.includes("整理复习卡片") && !["独立复习卡片", "平均质量", "回忆质量", "错误回忆", "确定性生成", "预览生成卡片"].some(term => reviewCopy.includes(term)), "复习流程只描述回想、答案和下次再看");
  record("复习页移除指标卡墙", await desktop.locator(".review-cards-workspace .weekly-summary, .review-cards-workspace .stat-card").count() === 0, "概况改为标题旁的一段连续说明");

  const reviewQuestion = "窗口函数为什么不会像 GROUP BY 那样合并明细行？";
  await desktop.getByLabel("卡片问题").fill(reviewQuestion);
  await desktop.getByLabel("卡片答案").fill("窗口函数在保留原始行的同时，对指定窗口进行计算；GROUP BY 会把同组记录聚合成一行。");
  await desktop.getByLabel("卡片提示").fill("先想结果集的行数是否变化");
  const createReviewResponse = desktop.waitForResponse(response => response.url().endsWith("/api/review-cards") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "留下这张卡片", exact: true }).click();
  const createReviewResult = await createReviewResponse;
  const reviewCard = desktop.locator(".review-card").filter({ hasText: reviewQuestion });
  await reviewCard.waitFor({ state: "visible" });
  record("真实创建复习卡片", createReviewResult.status() === 201 || createReviewResult.status() === 200, `POST /api/review-cards → ${createReviewResult.status()}`);

  const reviewLayout = await desktop.locator(".review-cards-workspace").evaluate(element => {
    const desk = element.querySelector(".review-desk");
    const card = element.querySelector(".review-card");
    return {
      deskColumns: getComputedStyle(desk).gridTemplateColumns,
      cardRadius: getComputedStyle(card).borderRadius,
      cardBackground: getComputedStyle(card).backgroundColor,
      queueLine: getComputedStyle(element.querySelector(".review-queue"), "::before").backgroundColor,
    };
  });
  record("连续复习桌布局", reviewLayout.deskColumns.split(" ").length === 2 && reviewLayout.cardRadius === "0px" && reviewLayout.cardBackground === "rgba(0, 0, 0, 0)" && reviewLayout.queueLine !== "rgba(0, 0, 0, 0)", JSON.stringify(reviewLayout));

  await reviewCard.getByRole("checkbox").check();
  await desktop.getByRole("button", { name: "收进卡片盒", exact: true }).click();
  const inlineArchiveConfirmation = desktop.locator(".review-selection-bar .review-inline-confirm");
  record("卡片操作页内确认", await inlineArchiveConfirmation.getByText("这些卡片以后还能从卡片盒恢复。").count() === 1 && await inlineArchiveConfirmation.getByRole("button", { name: "确认收起", exact: true }).count() === 1, "不再调用浏览器确认框");
  await inlineArchiveConfirmation.getByRole("button", { name: "取消", exact: true }).click();
  await reviewCard.getByRole("button", { name: "想好后看答案", exact: true }).click();
  record("先回想再看答案", await reviewCard.getByText("我原来写的答案", { exact: true }).count() === 1 && await reviewCard.getByText("刚才想起来多少？", { exact: true }).count() === 1);
  const answerReviewResponse = desktop.waitForResponse(response => response.url().endsWith("/answer") && response.url().includes("/api/review-cards/") && response.request().method() === "POST");
  await reviewCard.getByRole("button", { name: `${reviewQuestion}：想得很吃力`, exact: true }).click();
  const answerReviewResult = await answerReviewResponse;
  await desktop.getByText("之后再复习的卡片", { exact: false }).waitFor({ state: "visible" });
  record("真实记录回想结果", answerReviewResult.status() === 200 && await desktop.getByText("最近哪些内容容易忘", { exact: true }).count() === 1, `POST /api/review-cards/:id/answer → ${answerReviewResult.status()}`);

  await navigateTo(desktop, "笔记库");
  await desktop.waitForTimeout(350);
  const notesLayout = await desktop.locator(".notes-workspace").evaluate(element => ({ columns: getComputedStyle(element).gridTemplateColumns, listMaxHeight: getComputedStyle(element.querySelector(".note-list")).maxHeight, editorMinHeight: getComputedStyle(element.querySelector(".note-editor-panel textarea") ?? element).minHeight }));
  record("笔记库阅读工作区", notesLayout.columns.includes("px") && notesLayout.editorMinHeight !== "0px", JSON.stringify(notesLayout));

  await navigateTo(desktop, "教学闭环");
  await desktop.getByRole("heading", { name: "把一个概念讲清楚", exact: true }).waitFor({ state: "visible" });
  const teachingCopy = await visibleText(desktop);
  record("教学闭环自然文案", teachingCopy.includes("每节课只解决一个问题") && teachingCopy.includes("先读一遍") && !["自动评价", "评价来源", "置信度", "结构化模型", "本地回退", "/ 5"].some(term => teachingCopy.includes(term)), "页面只说明阅读、回答和补漏");
  record("教学页移除评分面板", await desktop.locator(".teaching-score, .teaching-workspace .stat-card").count() === 0, "主流程没有分数大字或指标卡");

  const teachingTitle = "窗口函数为什么保留明细行";
  await desktop.getByLabel("这次想弄懂什么").fill(teachingTitle);
  await desktop.getByLabel("我现在卡在哪里").fill("我知道窗口函数会计算排名，但还没弄清它和 GROUP BY 的结果有什么不同。");
  const createTeachingResponse = desktop.waitForResponse(response => response.url().endsWith("/api/teaching/sessions") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "新建这节课", exact: true }).click();
  const createTeachingResult = await createTeachingResponse;
  await desktop.getByRole("heading", { name: teachingTitle, exact: true }).waitFor({ state: "visible" });
  record("真实新建自学课", createTeachingResult.status() === 201, `POST /api/teaching/sessions → ${createTeachingResult.status()}`);

  const generateTeachingResponse = desktop.waitForResponse(response => response.url().includes("/api/teaching/sessions/") && response.url().endsWith("/generate") && response.request().method() === "POST", { timeout: 30000 });
  await desktop.getByRole("button", { name: "准备讲解和练习", exact: true }).click();
  const generateTeachingResult = await generateTeachingResponse;
  await desktop.getByText(`请用自己的话解释：${teachingTitle}`, { exact: true }).waitFor({ state: "visible" });
  record("真实准备讲解与练习", generateTeachingResult.status() === 200, `POST /api/teaching/sessions/:id/generate → ${generateTeachingResult.status()}`);

  const teachingAnswer = "窗口函数先保留原来的每一行，再在分区内计算排名或聚合值；GROUP BY 会把同一组记录合并成一行。";
  await desktop.getByLabel("用自己的话写下来").fill(teachingAnswer);
  const answerTeachingResponse = desktop.waitForResponse(response => response.url().endsWith("/answer") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "留下我的回答", exact: true }).click();
  const answerTeachingResult = await answerTeachingResponse;
  await desktop.getByText("我刚才的回答", { exact: true }).waitFor({ state: "visible" });
  record("真实留下自学回答", answerTeachingResult.status() === 200, `POST /api/teaching/sessions/:id/attempts/:id/answer → ${answerTeachingResult.status()}`);

  const evaluateTeachingResponse = desktop.waitForResponse(response => response.url().endsWith("/evaluate") && response.request().method() === "POST", { timeout: 30000 });
  await desktop.getByRole("button", { name: "看看哪里还没说清", exact: true }).click();
  const evaluateTeachingResult = await evaluateTeachingResponse;
  await desktop.getByText("下一次可以这样练", { exact: true }).waitFor({ state: "visible" });
  const evaluatedTeachingCopy = await visibleText(desktop);
  record("真实完成回答对照", evaluateTeachingResult.status() === 200 && evaluatedTeachingCopy.includes("已经说到") && evaluatedTeachingCopy.includes("还可以补上"), `POST /api/teaching/sessions/:id/attempts/:id/evaluate → ${evaluateTeachingResult.status()}`);
  record("教学反馈不暴露内部字段", !["自动评价", "评价来源", "置信度", "结构化模型", "本地回退", "/ 5"].some(term => evaluatedTeachingCopy.includes(term)), "必要来源说明收进可展开的自然语言说明");
  const teachingLayout = await desktop.locator(".teaching-workspace").evaluate(element => ({
    outerColumns: getComputedStyle(element).gridTemplateColumns,
    deskColumns: getComputedStyle(element.querySelector(".teaching-desk")).gridTemplateColumns,
    headingWidth: element.querySelector(".teaching-page-heading").getBoundingClientRect().width,
    workspaceWidth: element.getBoundingClientRect().width,
  }));
  record("自学课连续纸面层级", teachingLayout.outerColumns.split(" ").length === 1 && teachingLayout.deskColumns.split(" ").length === 2 && Math.abs(teachingLayout.headingWidth - teachingLayout.workspaceWidth) < 1, JSON.stringify(teachingLayout));

  await navigateTo(desktop, "统计复盘");
  await desktop.getByRole("heading", { level: 2, name: "统计复盘", exact: true }).waitFor({ state: "visible" });
  const analyticsCopy = await visibleText(desktop);
  record("统计复盘页面", analyticsCopy.includes("这段时间留下了什么") && analyticsCopy.includes("每天的学习节奏") && analyticsCopy.includes("哪些地方值得留意"));
  record("统计复盘使用自然语言", !["过程指标", "主题维度", "能力成长", "置信度", "任务延期率", "输入/输出", "理论/实践", "模型用量"].some(term => analyticsCopy.includes(term)), "技术用量降级到按需展开，学习事实改为完整句子");
  const analyticsLayout = await desktop.locator(".analytics-workspace").evaluate(element => ({
    sheets: element.querySelectorAll(":scope > .analytics-sheet").length,
    panels: element.querySelectorAll(".panel, .stat-card, .capability-card").length,
    topicRows: element.querySelectorAll(".analytics-topic-row").length,
    sectionBorders: [...element.querySelectorAll(".analytics-section")].map(section => getComputedStyle(section).borderBottomWidth),
  }));
  record("统计复盘连续纸面", analyticsLayout.sheets === 1 && analyticsLayout.panels === 0 && analyticsLayout.sectionBorders.every(width => width === "1px"), JSON.stringify(analyticsLayout));
  await desktop.getByLabel("统计时间范围").selectOption("14");
  await desktop.getByText("最近 14 天共记录", { exact: false }).waitFor({ state: "visible" });
  record("统计范围真实切换", (await visibleText(desktop)).includes("最近 14 天共记录"));

  const reportsDomainButton = desktop.getByRole("button", { name: "回看", exact: true });
  if (await reportsDomainButton.count()) {
    await navigateTo(desktop, "学习报告");
    await desktop.getByRole("heading", { name: "把这段时间的学习，整理成一页", exact: true }).waitFor({ state: "visible" });
    const initialReportCopy = await visibleText(desktop);
    const reportLayout = await desktop.locator(".reports-workspace").evaluate(element => ({ periodChoices: element.querySelectorAll(".report-period-choice").length, statCards: element.querySelectorAll(".stat-card, .analysis-grid").length, panels: element.querySelectorAll(":scope > .panel").length }));
    record("学习报告自然文案", initialReportCopy.includes("这次想回看哪一段") && initialReportCopy.includes("先选择一段时间") && !["强制生成新版本", "确定性统计", "降级统计", "模型生成", "反馈效果与版本对比"].some(term => initialReportCopy.includes(term)), "报告生产语言已退到用户看不见的数据层");
    record("学习回看连续纸面", reportLayout.periodChoices === 4 && reportLayout.statCards === 0 && reportLayout.panels === 0, JSON.stringify(reportLayout));
    const dailyButton = desktop.getByRole("button", { name: "整理今天", exact: true });
    if (await dailyButton.count()) {
      const reportResponse = desktop.waitForResponse(response => response.url().endsWith("/api/reports/daily/generate") && response.request().method() === "POST");
      await dailyButton.click();
      const reportResult = await reportResponse;
      await desktop.getByRole("heading", { name: "这段时间留下了什么", exact: true }).waitFor({ state: "visible" });
      const reportCopy = await visibleText(desktop);
      record("真实整理今天的学习回看", reportResult.status() === 200 && reportCopy.includes("每日学习总结") && reportCopy.includes("还卡在哪里") && reportCopy.includes("接下来可以做什么"), `POST /api/reports/daily/generate → ${reportResult.status()}`);
      record("学习回看不暴露内部评分", !["置信度", "确定性统计", "降级统计", "模型生成", "模型判断", "提案 #", "fallback"].some(term => reportCopy.includes(term)), "必要来源说明收进自然语言折叠区");
      const feedbackResponse = desktop.waitForResponse(response => /\/api\/reports\/\d+\/feedback$/.test(response.url()) && response.request().method() === "POST");
      await desktop.getByRole("button", { name: "这些建议值得安排", exact: true }).click();
      const feedbackResult = await feedbackResponse;
      await desktop.getByRole("heading", { name: "加入计划前，再看一眼", exact: true }).waitFor({ state: "visible" });
      record("回看建议先准备计划草稿", feedbackResult.status() === 201 && await desktop.getByRole("button", { name: "加入计划", exact: true }).count() > 0, `POST /api/reports/:id/feedback → ${feedbackResult.status()}`);
      const proposalResponse = desktop.waitForResponse(response => response.url().includes("/api/agent/plan-adjustment/") && response.request().method() === "POST");
      await desktop.getByRole("button", { name: "加入计划", exact: true }).click();
      const proposalResult = await proposalResponse;
      await desktop.getByText("已经加入计划", { exact: true }).waitFor({ state: "visible" });
      record("确认后加入回看建议", proposalResult.status() === 200, `POST /api/agent/plan-proposals/:id → ${proposalResult.status()}`);
    } else {
      record("真实整理今天的学习回看", false, "未找到整理今天按钮");
    }
  } else {
    record("学习报告自然文案", false, "未找到学习报告导航");
  }

  const settingsButton = desktop.getByRole("button", { name: "打开初始化设置" }).first();
  if (await settingsButton.count()) {
    await settingsButton.click();
    await desktop.waitForTimeout(350);
    await desktop.getByText("打开加密同步工具", { exact: true }).click();
    record("加密同步工具可见", (await visibleText(desktop)).includes("本地加密包") && (await desktop.getByLabel("设置页同步包口令").count()) === 1);
    await desktop.getByLabel("设置页同步包口令").fill("browser-sync-passphrase-2026");
    const syncDownload = desktop.waitForEvent("download");
    await desktop.getByRole("button", { name: "导出加密包", exact: true }).click();
    const syncFile = await syncDownload;
    record("本地加密包导出", syncFile.suggestedFilename().endsWith(".json"));
    record("初始化设置独立工作区", await desktop.getByRole("heading", { name: "初始化设置", level: 2 }).count() > 0, "复杂设置不再使用模态框");
    record("资料导入独立入口", await desktop.getByRole("button", { name: "前往文件导入", exact: true }).count() > 0, "资料授权保持可选且独立");
  } else {
    record("加密同步工具可见", false, "未找到初始化设置入口");
    record("本地加密包导出", false, "未找到初始化设置入口");
  }

  await navigateTo(desktop, "岗位分析");
  await desktop.getByRole("heading", { level: 2, name: "拿一份岗位说明，看看还差什么", exact: true }).waitFor({ state: "visible" });
  const initialJobCopy = await visibleText(desktop);
  record("岗位对照自然文案", initialJobCopy.includes("把岗位说明贴在这里") && initialJobCopy.includes("保存过的岗位") && !["分析置信度", "验证等级", "能力等级", "识别技能", "预览岗位分析", "确认保存"].some(term => initialJobCopy.includes(term)), "主流程只说明岗位要求、个人依据和待补材料");
  const jobDeskLayout = await desktop.locator(".job-analysis-workspace").evaluate(element => {
    const desk = element.querySelector(".job-readiness-desk");
    const editor = element.querySelector(".job-analysis-main");
    const archive = element.querySelector(".job-analysis-archive");
    return {
      columns: desk ? getComputedStyle(desk).gridTemplateColumns : "",
      editorLeft: editor?.getBoundingClientRect().left ?? 0,
      archiveLeft: archive?.getBoundingClientRect().left ?? 0,
      statCards: element.querySelectorAll(".stat-card, .job-analysis-summary").length,
      policyStripes: element.querySelectorAll(".job-analysis-policy").length,
    };
  });
  record("岗位准备夹桌面层级", jobDeskLayout.columns.split(" ").length === 2 && jobDeskLayout.archiveLeft < jobDeskLayout.editorLeft && jobDeskLayout.statCards === 0 && jobDeskLayout.policyStripes === 0, JSON.stringify(jobDeskLayout));
  const jobTitle = "Python 后端实习生";
  const jobDescription = "岗位职责：使用 Python 和 FastAPI 开发 REST API，编写 SQL 与自动化测试；熟悉 Docker、Linux 和 Git，能说明项目中的技术选择。";
  await desktop.getByLabel("岗位名称").fill(jobTitle);
  await desktop.getByLabel("岗位说明").fill(jobDescription);
  const previewJobResponse = desktop.waitForResponse(response => response.url().endsWith("/api/job-analyses") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "先看看这份岗位", exact: true }).click();
  const previewJobResult = await previewJobResponse;
  await desktop.getByText("还需要补什么", { exact: true }).waitFor({ state: "visible" });
  const previewJobCopy = await visibleText(desktop);
  record("真实生成岗位对照", previewJobResult.status() === 200 && previewJobCopy.includes("岗位说明里真正写了什么") && previewJobCopy.includes("我已经有哪些依据"), `POST /api/job-analyses preview → ${previewJobResult.status()}`);
  record("岗位对照不暴露内部评分", !["分析置信度", "置信度", "验证等级", "source_hash", "匹配度"].some(term => previewJobCopy.includes(term)), "不确定性放进自然语言方法说明");
  const saveJobResponse = desktop.waitForResponse(response => response.url().endsWith("/api/job-analyses") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "留下这份对照", exact: true }).click();
  const saveJobResult = await saveJobResponse;
  const savedJobRow = desktop.getByRole("button", { name: new RegExp(jobTitle) });
  await savedJobRow.waitFor({ state: "visible" });
  record("确认保存岗位对照", saveJobResult.status() === 200, `POST /api/job-analyses confirmed → ${saveJobResult.status()}`);
  await savedJobRow.click();
  await desktop.getByText("这是当时保存的对照结果，不会跟着后来的学习记录自动改变。", { exact: true }).waitFor({ state: "visible" });
  record("重新打开岗位快照", (await visibleText(desktop)).includes("对照新岗位"));

  const visualRoutes = [
    ["模拟面试", ".interview-policy"],
    ["插件系统", ".plugin-header"],
    ["知识地图", ".knowledge-workspace .panel"],
    ["练习与沙箱", ".practice-workspace .panel"],
  ];
  for (const [label, selector] of visualRoutes) {
    await navigateTo(desktop, label);
    const surface = desktop.locator(selector).first();
    await surface.waitFor({ state: "visible" });
    const surfaceStyle = await surface.evaluate(element => ({ background: getComputedStyle(element).backgroundColor, color: getComputedStyle(element).color }));
    record(`${label}主题层级`, surfaceStyle.background !== "rgb(24, 37, 27)" && surfaceStyle.background !== "rgb(18, 26, 22)" && surfaceStyle.color !== "rgb(189, 200, 194)", JSON.stringify(surfaceStyle));
    if (label === "模拟面试") {
      const policyStyle = await surface.evaluate(element => ({ borderLeftColor: getComputedStyle(element).borderLeftColor, background: getComputedStyle(element).backgroundColor }));
      record(`${label}蓝色边界提示`, policyStyle.borderLeftColor !== "rgb(156, 205, 143)" && policyStyle.background !== "rgb(238, 246, 236)", JSON.stringify(policyStyle));
    }
    if (label === "模拟面试") {
      const sessionLayout = await desktop.locator(".interview-session-list").evaluate(element => ({ columns: getComputedStyle(element).gridTemplateColumns, emptyHeight: element.parentElement?.querySelector(".interview-main")?.getBoundingClientRect().height ?? 0 }));
      record("模拟面试空状态与会话布局", sessionLayout.columns !== "none" && sessionLayout.emptyHeight <= 300, JSON.stringify(sessionLayout));
    }
    if (label === "插件系统") {
      const pluginStyle = await desktop.locator(".plugin-header").evaluate(element => ({ borderLeftColor: getComputedStyle(element).borderLeftColor, background: getComputedStyle(element).backgroundColor }));
      record("插件系统蓝色标题层", pluginStyle.borderLeftColor !== "rgb(175, 208, 168)" && pluginStyle.background !== "rgb(238, 246, 236)", JSON.stringify(pluginStyle));
    }
    if (label === "知识地图") {
      const topicGrid = desktop.locator(".topic-grid");
      const topicCard = desktop.locator(".topic-card").first();
      if (await topicCard.count()) {
        const topicStyle = await topicCard.evaluate(element => ({ display: getComputedStyle(element).display, minWidth: getComputedStyle(element).minWidth, textWrap: ["strong", "small", "p"].map(selector => getComputedStyle(element.querySelector(selector)).overflowWrap) }));
        record("知识主题长文本层级", topicStyle.display === "grid" && topicStyle.minWidth === "0px" && topicStyle.textWrap.every(value => value === "anywhere"), JSON.stringify(topicStyle));
      } else {
        record("知识主题长文本层级", await topicGrid.count() === 1, "当前数据库无主题，列表容器仍保留");
      }
    }
    if (label === "模拟面试") {
      const interviewMain = desktop.locator(".interview-main");
      const interviewHeight = await interviewMain.evaluate(element => element.getBoundingClientRect().height);
      record("模拟面试空状态密度", interviewHeight <= 280, `height=${interviewHeight}`);
    }
  }

  await navigateTo(desktop, "能力画像");
  const capabilityAssessmentResponse = desktop.waitForResponse(response => response.url().endsWith("/api/capabilities/assess") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "根据最近记录更新", exact: true }).click();
  const capabilityAssessmentResult = await capabilityAssessmentResponse;
  await desktop.locator(".capability-card").first().waitFor({ state: "visible" });
  record("更新能力回看", capabilityAssessmentResult.status() === 200 && await desktop.locator(".capability-card").count() >= 3, `POST /api/capabilities/assess → ${capabilityAssessmentResult.status()}`);
  const capabilityCopy = (await desktop.locator(".capability-workspace").innerText()).replace(/\s+/g, " ");
  record("能力回看自然文案", capabilityCopy.includes("我目前会什么") && capabilityCopy.includes("学习记录") && !["置信度", "补强计划", "确认执行计划", "得分"].some(term => capabilityCopy.includes(term)), "页面只说明学习阶段和依据，不暴露内部评分语言");
  const capabilityLayout = await desktop.locator(".capability-workspace").evaluate(element => {
    const grid = element.querySelector(".capability-grid");
    const cards = [...element.querySelectorAll(".capability-card")];
    const firstCardStyle = getComputedStyle(cards[0]);
    return {
      columns: getComputedStyle(grid).gridTemplateColumns,
      cardCount: cards.length,
      cardRadius: firstCardStyle.borderRadius,
      cardBackground: firstCardStyle.backgroundColor,
      stageVisible: Boolean(cards[0]?.querySelector(".capability-stage")?.textContent?.trim()),
      overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    };
  });
  record("能力档案连续布局", capabilityLayout.cardCount >= 3 && capabilityLayout.columns.split(" ").length === 1 && capabilityLayout.cardRadius === "0px" && capabilityLayout.cardBackground === "rgba(0, 0, 0, 0)" && capabilityLayout.stageVisible && !capabilityLayout.overflow, JSON.stringify(capabilityLayout));
  const firstCapability = desktop.locator(".capability-card").first();
  const capabilityHistoryResponse = desktop.waitForResponse(response => /\/api\/capabilities\/\d+\/history$/.test(response.url()) && response.request().method() === "GET");
  await firstCapability.getByRole("button", { name: "看看变化", exact: true }).click();
  const capabilityHistoryResult = await capabilityHistoryResponse;
  record("查看能力变化", capabilityHistoryResult.status() === 200 && await firstCapability.locator(".capability-history-panel").count() === 1, `GET /api/capabilities/:id/history → ${capabilityHistoryResult.status()}`);
  const capabilityEvidenceResponse = desktop.waitForResponse(response => /\/api\/capabilities\/\d+\/evidence$/.test(response.url()) && response.request().method() === "GET");
  await firstCapability.getByRole("button", { name: "查看练习和错题", exact: true }).click();
  const capabilityEvidenceResult = await capabilityEvidenceResponse;
  record("查看能力学习依据", capabilityEvidenceResult.status() === 200 && await firstCapability.getByText("相关练习和错题", { exact: true }).count() === 1, `GET /api/capabilities/:id/evidence → ${capabilityEvidenceResult.status()}`);
  const capabilityPlanResponse = desktop.waitForResponse(response => /\/api\/capabilities\/\d+\/plan$/.test(response.url()) && response.request().method() === "POST");
  await firstCapability.getByRole("button", { name: "安排巩固练习", exact: true }).click();
  const capabilityPlanResult = await capabilityPlanResponse;
  record("查看能力巩固安排", capabilityPlanResult.status() === 200 && await firstCapability.getByText("可以怎样巩固", { exact: true }).count() === 1, `POST /api/capabilities/:id/plan → ${capabilityPlanResult.status()}`);

  await navigateTo(desktop, "学习伙伴");
  const coachEmpty = desktop.locator(".coach-empty strong");
  const coachForm = desktop.locator(".coach-form");
  if (await coachEmpty.count() && await coachForm.count()) {
    const coachEmptyColor = await coachEmpty.evaluate(element => getComputedStyle(element).color);
    const coachFormBorder = await coachForm.evaluate(element => getComputedStyle(element).borderTopColor);
    record("学习伙伴浅色层级", coachEmptyColor !== "rgb(189, 208, 189)" && coachFormBorder !== "rgb(37, 44, 49)", `${coachEmptyColor} / ${coachFormBorder}`);
  } else {
    record("学习伙伴浅色层级", false, "未找到伙伴空状态或输入表单");
  }
  const coachText = await visibleText(desktop);
  record("学习伙伴自然文案", coachText.includes("和学习伙伴聊一聊") && coachText.includes("由你决定") && !coachText.includes("Agent") && !coachText.includes("变更预览") && !coachText.includes("确认并执行"), "对话和任务确认不暴露内部实现词");
  const coachLayout = await desktop.locator(".coach-page").evaluate(element => ({ columns: getComputedStyle(element).gridTemplateColumns, actionTop: getComputedStyle(element.querySelector(".coach-action-note")).borderTopColor, chatHeight: element.querySelector(".coach-workspace").getBoundingClientRect().height }));
  record("学习伙伴咨询桌布局", coachLayout.columns.split(" ").length >= 2 && coachLayout.chatHeight >= 650 && coachLayout.actionTop !== "rgb(40, 102, 210)", JSON.stringify(coachLayout));
  await desktop.getByLabel("准备加入计划的任务").fill("复习两道窗口函数边界题");
  const coachPreviewResponse = desktop.waitForResponse(response => response.url().endsWith("/api/agent/change") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "先检查一下", exact: true }).click();
  const coachPreviewResult = await coachPreviewResponse;
  record("伙伴建议加入前检查", coachPreviewResult.status() === 200 && await desktop.getByText("准备加入", { exact: true }).count() === 1, `POST /api/agent/change → ${coachPreviewResult.status()}`);
  const coachConfirmResponse = desktop.waitForResponse(response => response.url().endsWith("/api/agent/change") && response.request().method() === "POST");
  await desktop.getByRole("button", { name: "加入任务清单", exact: true }).click();
  const coachConfirmResult = await coachConfirmResponse;
  await desktop.waitForTimeout(250);
  record("确认加入伙伴建议", coachConfirmResult.status() === 200 && (await visibleText(desktop)).includes("任务已经加入学习计划"), `POST /api/agent/change confirmed → ${coachConfirmResult.status()}`);

  await navigateTo(desktop, "学习报告");
  const reportPaper = desktop.locator(".report-reading-paper");
  if (await reportPaper.count()) {
    const reportSurface = await reportPaper.evaluate(element => ({ paper: getComputedStyle(element).backgroundColor, heading: getComputedStyle(element.querySelector(".report-paper-header")).backgroundColor, sectionColumns: getComputedStyle(element.querySelector(".report-paper-section")).gridTemplateColumns }));
    record("学习报告浅色层级", reportSurface.paper !== reportSurface.heading && reportSurface.sectionColumns.split(" ").length >= 2, JSON.stringify(reportSurface));
  } else {
    record("学习报告浅色层级", false, "未找到学习回看纸面");
  }

  await desktop.getByRole("button", { name: "打开初始化设置" }).first().click();
  await desktop.waitForTimeout(300);
  const settingsSurface = await desktop.locator(".model-settings-section").evaluate(element => ({ background: getComputedStyle(element).backgroundColor, color: getComputedStyle(element).color, border: getComputedStyle(element).borderColor }));
  record("设置工作区主题层级", settingsSurface.background !== "rgb(23, 30, 29)" && settingsSurface.color !== "rgb(189, 200, 194)", JSON.stringify(settingsSurface));
  const settingsHealth = await desktop.locator(".model-status-summary").evaluate(element => ({ cards: element.querySelectorAll(".stat-card").length, columns: getComputedStyle(element).gridTemplateColumns }));
  record("设置状态摘要非 KPI 化", settingsHealth.cards === 0 && settingsHealth.columns.split(" ").length >= 3, JSON.stringify(settingsHealth));

  await navigateTo(desktop, "运行与审计");
  const operationsSurface = await desktop.locator(".runtime-status-grid span, .operation-call-details").evaluateAll(elements => elements.map(element => getComputedStyle(element).backgroundColor));
  const auditList = desktop.locator(".audit-list");
  const auditLayout = await auditList.count() ? await auditList.evaluate(element => ({ height: element.getBoundingClientRect().height, scrollHeight: element.scrollHeight, clientHeight: element.clientHeight })) : null;
  record("运行审计浅色层级", operationsSurface.length > 0 && operationsSurface.every(color => color !== "rgb(18, 25, 24)" && color !== "rgb(18, 26, 22)"), operationsSurface.join(", "));
  record("审计记录内部滚动", Boolean(auditLayout && auditLayout.scrollHeight > auditLayout.clientHeight && auditLayout.height <= 600), JSON.stringify(auditLayout));

  const namedInputs = await desktop.locator("input, textarea, select").evaluateAll(elements => elements.map(element => ({ tag: element.tagName, aria: element.getAttribute("aria-label"), id: element.id, placeholder: element.getAttribute("placeholder") })));
  record("表单可识别性", namedInputs.filter(item => item.aria || item.id || item.placeholder).length === namedInputs.length, `${namedInputs.length} 个表单控件均有标识`);

  await desktop.keyboard.press("Tab");
  const focused = await desktop.evaluate(() => ({ tag: document.activeElement?.tagName, label: document.activeElement?.getAttribute("aria-label"), text: document.activeElement?.textContent?.trim().slice(0, 40) }));
  record("键盘焦点可用", Boolean(focused.tag), `${focused.tag}${focused.label ? `/${focused.label}` : ""}`);

  const reducedContext = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1024, height: 800 } });
  const reducedPage = await reducedContext.newPage();
  await reducedPage.goto(baseURL, { waitUntil: "domcontentloaded" });
  await dismissOnboarding(reducedPage);
  const reducedMotion = await reducedPage.locator(".nav-item").first().evaluate(element => ({ animation: getComputedStyle(element).animationDuration, transition: getComputedStyle(element).transitionDuration }));
  const reducedDuration = value => value === "0.01ms" || value === "1e-05s";
  record("减少动态偏好", reducedDuration(reducedMotion.animation) && reducedDuration(reducedMotion.transition), JSON.stringify(reducedMotion));
  await reducedContext.close();

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await mobile.goto(baseURL, { waitUntil: "domcontentloaded" });
  await mobile.waitForTimeout(500);
  await dismissOnboarding(mobile);
  const mobileNavToggle = mobile.getByRole("button", { name: "打开导航" });
  if (await mobileNavToggle.count()) {
    await mobileNavToggle.click();
    record("移动导航语义状态", await mobile.getByRole("button", { name: "关闭导航" }).count() === 1, "打开后按钮名称与 aria 状态同步");
    await mobile.keyboard.press("Escape");
    record("移动导航 Escape 关闭", await mobile.getByRole("button", { name: "打开导航" }).count() === 1 && !(await mobile.locator(".sidebar").getAttribute("class"))?.includes("mobile-open"));
    await navigateTo(mobile, "今日总览");
    await mobile.locator(".home-workstation").waitFor({ state: "visible", timeout: 3000 });
  }
  const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  record("移动端视口", !overflow, `scrollWidth=${await mobile.evaluate(() => document.documentElement.scrollWidth)}, width=${await mobile.evaluate(() => window.innerWidth)}`);
  const mobileText = await visibleText(mobile);
  record("移动端核心内容", mobileText.includes("今日总览") && mobileText.includes("今天先完成什么"));
  const mobilePrimaryControls = await mobile.locator(".mobile-nav-toggle, .theme-toggle, .avatar").evaluateAll(elements => elements.filter(element => getComputedStyle(element).display !== "none").map(element => ({ className: element.className, width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height })));
  record("移动端高频入口", mobilePrimaryControls.length === 3 && mobilePrimaryControls.every(control => control.width >= 44 && control.height >= 44), JSON.stringify(mobilePrimaryControls));
  if (await mobileNavToggle.count()) {
    await navigateTo(mobile, "文件导入");
    const mobileImportLayout = await mobile.evaluate(() => {
      const checkbox = document.querySelector('.stack-form input[type="checkbox"]');
      const importButton = document.querySelector('.web-import-form button');
      const searchButton = document.querySelector('.import-search-form button');
      const rect = element => element?.getBoundingClientRect();
      const checkboxRect = rect(checkbox);
      const importRect = rect(importButton);
      const searchRect = rect(searchButton);
      return {
        checkbox: checkboxRect ? { width: checkboxRect.width, height: checkboxRect.height } : null,
        importButton: importRect ? { width: importRect.width, height: importRect.height, bottom: importRect.bottom } : null,
        searchButton: searchRect ? { width: searchRect.width, height: searchRect.height, bottom: searchRect.bottom } : null,
      };
    });
    const controlsFit = Boolean(mobileImportLayout.checkbox && mobileImportLayout.checkbox.width <= 20 && mobileImportLayout.checkbox.height <= 20 && mobileImportLayout.importButton && mobileImportLayout.importButton.width >= 70 && mobileImportLayout.importButton.height < 60 && mobileImportLayout.searchButton && mobileImportLayout.searchButton.width >= 70 && mobileImportLayout.searchButton.height < 60);
    record("移动端导入控件布局", controlsFit, JSON.stringify(mobileImportLayout));
    await navigateTo(mobile, "项目工作台");
    record("移动端项目空状态", !(await mobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)), `scrollWidth=${await mobile.evaluate(() => document.documentElement.scrollWidth)}`);
    await navigateTo(mobile, "学习计划");
    const planMobileLayout = await mobile.evaluate(() => {
      const rows = [...document.querySelectorAll(".plan-task-list-panel .task-row")];
      const overlaps = rows.map(row => {
        const children = [...row.children].map(child => child.getBoundingClientRect());
        return children.some((first, index) => children.some((second, otherIndex) => otherIndex > index && first.bottom > second.top + 1 && first.top < second.bottom - 1 && first.right > second.left + 1 && first.left < second.right - 1));
      });
      return { overlaps, scrollWidth: document.documentElement.scrollWidth, viewport: window.innerWidth };
    });
    record("移动端学习计划任务布局", planMobileLayout.overlaps.every(value => !value) && planMobileLayout.scrollWidth <= planMobileLayout.viewport + 1, JSON.stringify(planMobileLayout));
    await navigateTo(mobile, "周计划");
    const weeklyMobileLayout = await mobile.locator(".weekly-plan-workspace").evaluate(element => {
      const taskRows = [...element.querySelectorAll(".weekly-task-row")];
      const overlaps = taskRows.map(row => {
        const children = [...row.children].map(child => child.getBoundingClientRect());
        return children.some((first, index) => children.some((second, otherIndex) => otherIndex > index && first.bottom > second.top + 1 && first.top < second.bottom - 1 && first.right > second.left + 1 && first.left < second.right - 1));
      });
      return { sheetColumns: getComputedStyle(element.querySelector(".weekly-plan-sheet")).gridTemplateColumns, overlaps, overflow: document.documentElement.scrollWidth > window.innerWidth + 1 };
    });
    record("移动端周计划布局", weeklyMobileLayout.sheetColumns.split(" ").length === 1 && weeklyMobileLayout.overlaps.every(value => !value) && !weeklyMobileLayout.overflow, JSON.stringify(weeklyMobileLayout));
    await navigateTo(mobile, "复习卡片");
    const reviewMobileLayout = await mobile.locator(".review-cards-workspace").evaluate(element => {
      const desk = element.querySelector(".review-desk");
      const session = element.querySelector(".review-session")?.getBoundingClientRect();
      const editor = element.querySelector(".review-card-editor")?.getBoundingClientRect();
      const controls = [...element.querySelectorAll("button, summary")].filter(control => {
        const rect = control.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && getComputedStyle(control).visibility !== "hidden";
      });
      return {
        columns: getComputedStyle(desk).gridTemplateColumns,
        stacked: Boolean(session && editor && session.bottom <= editor.top + 1),
        clippedControls: controls.filter(control => control.scrollWidth > control.clientWidth + 2).map(control => control.textContent?.trim().slice(0, 28)),
        overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      };
    });
    record("移动端复习桌布局", reviewMobileLayout.columns.split(" ").length === 1 && reviewMobileLayout.stacked && reviewMobileLayout.clippedControls.length === 0 && !reviewMobileLayout.overflow, JSON.stringify(reviewMobileLayout));
    await navigateTo(mobile, "今日记录");
    const logMobileLayout = await mobile.evaluate(() => {
      const rows = [...document.querySelectorAll(".log-row")];
      const overlaps = rows.map(row => {
        const children = [...row.children].map(child => child.getBoundingClientRect());
        return children.some((first, index) => children.some((second, otherIndex) => otherIndex > index && first.bottom > second.top + 1 && first.top < second.bottom - 1 && first.right > second.left + 1 && first.left < second.right - 1));
      });
      const status = document.querySelector(".review-state");
      return { overlaps, statusVisible: status ? getComputedStyle(status).display !== "none" : false, scrollWidth: document.documentElement.scrollWidth, viewport: window.innerWidth };
    });
    record("移动端学习记录布局", logMobileLayout.overlaps.every(value => !value) && logMobileLayout.statusVisible && logMobileLayout.scrollWidth <= logMobileLayout.viewport + 1, JSON.stringify(logMobileLayout));
    await navigateTo(mobile, "笔记库");
    const mobileFirstNote = mobile.locator(".note-list-item").first();
    await mobileFirstNote.waitFor({ state: "visible" });
    await mobileFirstNote.click();
    const notesMobileLayout = await mobile.locator(".notes-workspace").evaluate(element => {
      const panels = [...element.querySelectorAll(":scope > .panel")].map(panel => panel.getBoundingClientRect());
      const utilityButtons = [...element.querySelectorAll(".note-utility-bar button")].map(button => button.getBoundingClientRect());
      const panelOverlap = panels.some((first, index) => panels.some((second, otherIndex) => otherIndex > index && first.bottom > second.top + 1));
      return { columns: getComputedStyle(element).gridTemplateColumns, panelOverlap, buttonWidths: utilityButtons.map(rect => rect.width), overflow: document.documentElement.scrollWidth > window.innerWidth + 1 };
    });
    record("移动端笔记写作布局", !notesMobileLayout.panelOverlap && !notesMobileLayout.overflow && notesMobileLayout.buttonWidths.length === 4 && notesMobileLayout.buttonWidths.every(width => width >= 120), JSON.stringify(notesMobileLayout));
    await navigateTo(mobile, "教学闭环");
    await mobile.getByRole("heading", { name: "把一个概念讲清楚", exact: true }).waitFor({ state: "visible" });
    const teachingMobileLayout = await mobile.locator(".teaching-workspace").evaluate(element => {
      const desk = element.querySelector(".teaching-desk");
      const sidebar = element.querySelector(".teaching-sidebar");
      const main = element.querySelector(".teaching-main");
      const controls = [...element.querySelectorAll("button, input, select, textarea")].filter(control => {
        const rect = control.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }).map(control => control.getBoundingClientRect());
      return {
        columns: desk ? getComputedStyle(desk).gridTemplateColumns : "",
        stacked: Boolean(sidebar && main && sidebar.getBoundingClientRect().bottom <= main.getBoundingClientRect().top + 1),
        shortControls: controls.filter(rect => rect.height < 44).length,
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      };
    });
    record("移动端自学课连续阅读", teachingMobileLayout.columns.split(" ").length === 1 && teachingMobileLayout.stacked && teachingMobileLayout.shortControls === 0 && !teachingMobileLayout.overflow, JSON.stringify(teachingMobileLayout));
    await navigateTo(mobile, "岗位分析");
    await mobile.getByRole("heading", { level: 2, name: "拿一份岗位说明，看看还差什么", exact: true }).waitFor({ state: "visible" });
    const jobMobileLayout = await mobile.locator(".job-analysis-workspace").evaluate(element => {
      const desk = element.querySelector(".job-readiness-desk");
      const main = element.querySelector(".job-analysis-main")?.getBoundingClientRect();
      const archive = element.querySelector(".job-analysis-archive")?.getBoundingClientRect();
      const controls = [...element.querySelectorAll("button, input, textarea, summary")].filter(control => control.getBoundingClientRect().width > 0);
      return {
        columns: desk ? getComputedStyle(desk).gridTemplateColumns : "",
        mainBeforeArchive: Boolean(main && archive && main.bottom <= archive.top + 1),
        shortControls: controls.filter(control => control.getBoundingClientRect().height < 44).length,
        clippedControls: controls.filter(control => control.scrollWidth > control.clientWidth + 2).map(control => control.textContent?.trim().slice(0, 28)),
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      };
    });
    record("移动端岗位准备夹", jobMobileLayout.columns.split(" ").length === 1 && jobMobileLayout.mainBeforeArchive && jobMobileLayout.shortControls === 0 && jobMobileLayout.clippedControls.length === 0 && !jobMobileLayout.overflow, JSON.stringify(jobMobileLayout));
    await navigateTo(mobile, "统计复盘");
    await mobile.getByRole("heading", { level: 2, name: "统计复盘", exact: true }).waitFor({ state: "visible" });
    const analyticsMobileLayout = await mobile.locator(".analytics-workspace").evaluate(element => {
      const actions = element.querySelector(".analytics-page-actions");
      const ledger = element.querySelector(".analytics-ledger");
      const rhythm = element.querySelector(".analytics-rhythm-scroll");
      const topicRows = [...element.querySelectorAll(".analytics-topic-row")];
      const controls = [...element.querySelectorAll("button, select")].filter(control => control.getBoundingClientRect().width > 0);
      return {
        actionDirection: actions ? getComputedStyle(actions).flexDirection : "",
        ledgerColumns: ledger ? getComputedStyle(ledger).gridTemplateColumns : "",
        topicColumns: topicRows.map(row => getComputedStyle(row).gridTemplateColumns),
        rhythmAtLatest: Boolean(rhythm && rhythm.scrollLeft + rhythm.clientWidth >= rhythm.scrollWidth - 2),
        clippedControls: controls.filter(control => control.scrollWidth > control.clientWidth + 2).map(control => control.textContent?.trim().slice(0, 28)),
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      };
    });
    record("移动端统计复盘阅读", analyticsMobileLayout.actionDirection === "column" && analyticsMobileLayout.ledgerColumns.split(" ").length === 1 && analyticsMobileLayout.topicColumns.every(columns => columns.split(" ").length === 1) && analyticsMobileLayout.rhythmAtLatest && analyticsMobileLayout.clippedControls.length === 0 && !analyticsMobileLayout.overflow, JSON.stringify(analyticsMobileLayout));
    await navigateTo(mobile, "学习报告");
    await mobile.getByRole("heading", { name: "把这段时间的学习，整理成一页", exact: true }).waitFor({ state: "visible" });
    const mobileReportHistory = mobile.locator(".report-history-row").first();
    await mobileReportHistory.waitFor({ state: "visible" });
    await mobileReportHistory.click();
    await mobile.getByRole("heading", { name: "这段时间留下了什么", exact: true }).waitFor({ state: "visible" });
    const reportMobileLayout = await mobile.locator(".reports-workspace").evaluate(element => {
      const periodList = element.querySelector(".report-period-list");
      const paper = element.querySelector(".report-reading-paper")?.getBoundingClientRect();
      const archive = element.querySelector(".report-archive")?.getBoundingClientRect();
      const section = element.querySelector(".report-paper-section");
      const controls = [...element.querySelectorAll("button, input, select, summary")].filter(control => control.getBoundingClientRect().width > 0);
      return {
        periodColumns: periodList ? getComputedStyle(periodList).gridTemplateColumns : "",
        sectionColumns: section ? getComputedStyle(section).gridTemplateColumns : "",
        paperBeforeArchive: Boolean(paper && archive && paper.bottom <= archive.top + 1),
        shortControls: controls.filter(control => control.getBoundingClientRect().height < 44).length,
        clippedControls: controls.filter(control => control.scrollWidth > control.clientWidth + 2).map(control => control.textContent?.trim().slice(0, 28)),
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      };
    });
    record("移动端学习回看阅读", reportMobileLayout.periodColumns.split(" ").length === 1 && reportMobileLayout.sectionColumns.split(" ").length === 1 && reportMobileLayout.paperBeforeArchive && reportMobileLayout.shortControls === 0 && reportMobileLayout.clippedControls.length === 0 && !reportMobileLayout.overflow, JSON.stringify(reportMobileLayout));
    await navigateTo(mobile, "学习伙伴");
    const coachMobileLayout = await mobile.locator(".coach-page").evaluate(element => {
      const panels = [...element.querySelectorAll(":scope > .panel")].map(panel => panel.getBoundingClientRect());
      const prompts = [...element.querySelectorAll(".coach-quick-prompts button")].map(button => button.getBoundingClientRect());
      return { columns: getComputedStyle(element).gridTemplateColumns, stacked: panels.length === 2 && panels[0].bottom <= panels[1].top + 1, promptWidths: prompts.map(rect => rect.width), overflow: document.documentElement.scrollWidth > window.innerWidth + 1 };
    });
    record("移动端学习伙伴布局", coachMobileLayout.stacked && !coachMobileLayout.overflow && coachMobileLayout.promptWidths.length === 3 && coachMobileLayout.promptWidths.every(width => width >= 300), JSON.stringify(coachMobileLayout));
    await navigateTo(mobile, "能力画像");
    await mobile.locator(".capability-card").first().waitFor({ state: "visible" });
    const capabilityMobileLayout = await mobile.locator(".capability-workspace").evaluate(element => {
      const cards = [...element.querySelectorAll(".capability-card")];
      const actionRows = cards.map(card => {
        const actions = [...card.querySelectorAll(".capability-actions button")].map(button => button.getBoundingClientRect());
        return actions.some((first, index) => actions.some((second, otherIndex) => otherIndex > index && first.bottom > second.top + 1 && first.top < second.bottom - 1 && first.right > second.left + 1 && first.left < second.right - 1));
      });
      const firstHeader = cards[0]?.querySelector(".capability-card-header");
      return {
        cards: cards.length,
        columns: firstHeader ? getComputedStyle(firstHeader).gridTemplateColumns : "",
        actionOverlaps: actionRows,
        overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      };
    });
    record("移动端能力档案布局", capabilityMobileLayout.cards >= 3 && capabilityMobileLayout.columns.split(" ").length === 1 && capabilityMobileLayout.actionOverlaps.every(value => !value) && !capabilityMobileLayout.overflow, JSON.stringify(capabilityMobileLayout));
    await navigateTo(mobile, "知识地图");
    const knowledgeViewport = await mobile.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, graphWidth: document.querySelector('.graph-canvas-wrap')?.clientWidth ?? 0, graphScrollWidth: document.querySelector('.graph-canvas-wrap')?.scrollWidth ?? 0 }));
    record("移动端知识地图容器", knowledgeViewport.scrollWidth <= knowledgeViewport.clientWidth + 1 && knowledgeViewport.graphWidth <= knowledgeViewport.clientWidth, JSON.stringify(knowledgeViewport));
  } else {
    record("移动端导入控件布局", false, "未找到移动端导航按钮");
  }
  await mobile.close();

  const responsivePage = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await responsivePage.goto(baseURL, { waitUntil: "domcontentloaded" });
  await responsivePage.waitForTimeout(500);
  await dismissOnboarding(responsivePage);
  await navigateTo(responsivePage, "今日总览");
  await responsivePage.locator(".scene-hero").waitFor({ state: "visible", timeout: 5000 });
  const responsiveResults = [];
  for (const width of [320, 375, 390, 414, 768, 1280, 1440, 1920]) {
    await responsivePage.setViewportSize({ width, height: width <= 414 ? 844 : 1000 });
    await responsivePage.waitForTimeout(100);
    responsiveResults.push(await responsivePage.evaluate(currentWidth => {
      const workspace = document.querySelector(".home-workspace")?.getBoundingClientRect();
      const companion = document.querySelector(".home-companion")?.getBoundingClientRect();
      const visibleButtons = [...document.querySelectorAll("button")].filter(button => {
        const style = getComputedStyle(button);
        const rect = button.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      });
      return {
        width: currentWidth,
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        workstationClear: !workspace || !companion || workspace.right <= companion.left + 1 || workspace.bottom <= companion.top + 1 || companion.bottom <= workspace.top + 1,
        clippedButtons: visibleButtons.filter(button => Boolean(button.textContent?.trim()) && button.scrollWidth > button.clientWidth + 2).map(button => button.textContent?.trim().slice(0, 24)),
      };
    }, width));
  }
  record("八档响应式合同", responsiveResults.every(result => !result.overflow && result.workstationClear && result.clippedButtons.length === 0), JSON.stringify(responsiveResults));
  await navigateTo(responsivePage, "复习卡片");
  const responsiveReviewResults = [];
  for (const width of [320, 375, 390, 414, 768, 1280, 1440, 1920]) {
    await responsivePage.setViewportSize({ width, height: width <= 414 ? 844 : 1000 });
    await responsivePage.waitForTimeout(80);
    responsiveReviewResults.push(await responsivePage.evaluate(currentWidth => {
      const visibleControls = [...document.querySelectorAll(".review-cards-workspace button, .review-cards-workspace summary")].filter(control => {
        const rect = control.getBoundingClientRect();
        const style = getComputedStyle(control);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      });
      return {
        width: currentWidth,
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        clippedControls: visibleControls.filter(control => control.scrollWidth > control.clientWidth + 2).map(control => control.textContent?.trim().slice(0, 28)),
      };
    }, width));
  }
  record("复习桌八档响应式", responsiveReviewResults.every(result => !result.overflow && result.clippedControls.length === 0), JSON.stringify(responsiveReviewResults));
  await navigateTo(responsivePage, "教学闭环");
  const responsiveTeachingResults = [];
  for (const width of [320, 375, 390, 414, 768, 1280, 1440, 1920]) {
    await responsivePage.setViewportSize({ width, height: width <= 414 ? 844 : 1000 });
    await responsivePage.waitForTimeout(80);
    responsiveTeachingResults.push(await responsivePage.evaluate(currentWidth => {
      const visibleControls = [...document.querySelectorAll(".teaching-workspace button, .teaching-workspace input, .teaching-workspace select, .teaching-workspace textarea, .teaching-workspace summary")].filter(control => {
        const rect = control.getBoundingClientRect();
        const style = getComputedStyle(control);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      });
      return {
        width: currentWidth,
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        clippedControls: visibleControls.filter(control => control.scrollWidth > control.clientWidth + 2).map(control => control.textContent?.trim().slice(0, 28)),
      };
    }, width));
  }
  record("自学课八档响应式", responsiveTeachingResults.every(result => !result.overflow && result.clippedControls.length === 0), JSON.stringify(responsiveTeachingResults));
  await navigateTo(responsivePage, "统计复盘");
  const responsiveAnalyticsResults = [];
  for (const width of [320, 375, 390, 414, 768, 1280, 1440, 1920]) {
    await responsivePage.setViewportSize({ width, height: width <= 414 ? 844 : 1000 });
    await responsivePage.waitForTimeout(80);
    responsiveAnalyticsResults.push(await responsivePage.evaluate(currentWidth => {
      const visibleControls = [...document.querySelectorAll(".analytics-workspace button, .analytics-workspace select, .analytics-workspace summary")].filter(control => {
        const rect = control.getBoundingClientRect();
        const style = getComputedStyle(control);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      });
      return {
        width: currentWidth,
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        clippedControls: visibleControls.filter(control => control.scrollWidth > control.clientWidth + 2).map(control => control.textContent?.trim().slice(0, 28)),
      };
    }, width));
  }
  record("统计复盘八档响应式", responsiveAnalyticsResults.every(result => !result.overflow && result.clippedControls.length === 0), JSON.stringify(responsiveAnalyticsResults));
  await navigateTo(responsivePage, "岗位分析");
  const responsiveJobResults = [];
  for (const width of [320, 375, 390, 414, 768, 1280, 1440, 1920]) {
    await responsivePage.setViewportSize({ width, height: width <= 414 ? 844 : 1000 });
    await responsivePage.waitForTimeout(80);
    responsiveJobResults.push(await responsivePage.evaluate(currentWidth => {
      const controls = [...document.querySelectorAll(".job-analysis-workspace button, .job-analysis-workspace input, .job-analysis-workspace textarea, .job-analysis-workspace summary")].filter(control => {
        const rect = control.getBoundingClientRect();
        const style = getComputedStyle(control);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      });
      return {
        width: currentWidth,
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        clippedControls: controls.filter(control => control.scrollWidth > control.clientWidth + 2).map(control => control.textContent?.trim().slice(0, 28)),
      };
    }, width));
  }
  record("岗位准备夹八档响应式", responsiveJobResults.every(result => !result.overflow && result.clippedControls.length === 0), JSON.stringify(responsiveJobResults));
  await navigateTo(responsivePage, "学习报告");
  await responsivePage.locator(".report-history-row").first().click();
  await responsivePage.getByRole("heading", { name: "这段时间留下了什么", exact: true }).waitFor({ state: "visible" });
  const responsiveReportResults = [];
  for (const width of [320, 375, 390, 414, 768, 1280, 1440, 1920]) {
    await responsivePage.setViewportSize({ width, height: width <= 414 ? 844 : 1000 });
    await responsivePage.waitForTimeout(80);
    responsiveReportResults.push(await responsivePage.evaluate(currentWidth => {
      const controls = [...document.querySelectorAll(".reports-workspace button, .reports-workspace input, .reports-workspace select, .reports-workspace summary")].filter(control => {
        const rect = control.getBoundingClientRect();
        const style = getComputedStyle(control);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      });
      return {
        width: currentWidth,
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        clippedControls: controls.filter(control => control.scrollWidth > control.clientWidth + 2).map(control => control.textContent?.trim().slice(0, 28)),
      };
    }, width));
  }
  record("学习回看八档响应式", responsiveReportResults.every(result => !result.overflow && result.clippedControls.length === 0), JSON.stringify(responsiveReportResults));
  await responsivePage.setViewportSize({ width: 1440, height: 1000 });
  await navigateTo(responsivePage, "今日总览");
  await responsivePage.getByRole("button", { name: "切换到深色主题", exact: true }).click();
  const darkTheme = await responsivePage.evaluate(() => ({ theme: document.documentElement.dataset.theme, bodyBackground: getComputedStyle(document.body).backgroundColor, bodyColor: getComputedStyle(document.body).color, companionBackground: getComputedStyle(document.querySelector(".home-companion")).backgroundColor, workspaceBackground: getComputedStyle(document.querySelector(".home-workspace")).backgroundColor }));
  record("深色主题工作站边界", darkTheme.theme === "dark" && darkTheme.bodyBackground !== darkTheme.bodyColor && darkTheme.companionBackground !== darkTheme.workspaceBackground, JSON.stringify(darkTheme));
  await navigateTo(responsivePage, "学习计划");
  const darkPlan = await responsivePage.locator(".plan-workspace").evaluate(element => ({
    button: getComputedStyle(element.querySelector(".primary-button")).backgroundColor,
    buttonShadow: getComputedStyle(element.querySelector(".primary-button")).boxShadow,
    timer: getComputedStyle(element.querySelector(".task-timer")).backgroundColor,
    timerText: getComputedStyle(element.querySelector(".task-timer")).color,
  }));
  record("深色学习计划控件层级", darkPlan.button.includes("0.64 0.1 250") && darkPlan.buttonShadow === "none" && darkPlan.timer !== "rgb(239, 246, 241)" && darkPlan.timerText !== darkPlan.timer, JSON.stringify(darkPlan));
  await navigateTo(responsivePage, "周计划");
  const darkWeeklyPlan = await responsivePage.locator(".weekly-plan-workspace").evaluate(element => ({
    surface: getComputedStyle(element).backgroundColor,
    rhythm: getComputedStyle(element.querySelector(".weekly-rhythm")).backgroundColor,
    field: getComputedStyle(element.querySelector("textarea")).backgroundColor,
    fieldText: getComputedStyle(element.querySelector("textarea")).color,
    progress: getComputedStyle(element.querySelector(".weekly-progress-track span")).backgroundColor,
    button: getComputedStyle(element.querySelector(".weekly-plan-sheet .primary-button")).backgroundColor,
  }));
  record("深色周计划阅读层级", darkWeeklyPlan.surface !== "rgb(255, 255, 255)" && darkWeeklyPlan.rhythm !== "rgb(255, 255, 255)" && darkWeeklyPlan.fieldText !== darkWeeklyPlan.field && darkWeeklyPlan.progress.includes("0.64 0.1 250") && darkWeeklyPlan.button.includes("0.64 0.1 250"), JSON.stringify(darkWeeklyPlan));
  await navigateTo(responsivePage, "复习卡片");
  const darkReviewCards = await responsivePage.locator(".review-cards-workspace").evaluate(element => ({
    desk: getComputedStyle(element.querySelector(".review-desk")).backgroundColor,
    editor: getComputedStyle(element.querySelector(".review-card-editor")).backgroundColor,
    field: getComputedStyle(element.querySelector(".review-manual-form input")).backgroundColor,
    fieldText: getComputedStyle(element.querySelector(".review-manual-form input")).color,
    button: getComputedStyle(element.querySelector(".review-manual-form .primary-button")).backgroundColor,
    buttonShadow: getComputedStyle(element.querySelector(".review-manual-form .primary-button")).boxShadow,
  }));
  record("深色复习桌阅读层级", darkReviewCards.desk !== "rgb(255, 255, 255)" && darkReviewCards.editor !== darkReviewCards.desk && darkReviewCards.fieldText !== darkReviewCards.field && darkReviewCards.button.includes("0.64 0.1 250") && darkReviewCards.buttonShadow === "none", JSON.stringify(darkReviewCards));
  await navigateTo(responsivePage, "教学闭环");
  const darkTeaching = await responsivePage.locator(".teaching-workspace").evaluate(element => ({
    desk: getComputedStyle(element.querySelector(".teaching-desk")).backgroundColor,
    sidebar: getComputedStyle(element.querySelector(".teaching-sidebar")).backgroundColor,
    main: getComputedStyle(element.querySelector(".teaching-main")).backgroundColor,
    field: getComputedStyle(element.querySelector(".teaching-new-lesson input")).backgroundColor,
    fieldText: getComputedStyle(element.querySelector(".teaching-new-lesson input")).color,
    button: getComputedStyle(element.querySelector(".teaching-new-lesson .primary-button")).backgroundColor,
    buttonShadow: getComputedStyle(element.querySelector(".teaching-new-lesson .primary-button")).boxShadow,
  }));
  record("深色自学课阅读层级", darkTeaching.desk !== "rgb(255, 255, 255)" && darkTeaching.sidebar !== darkTeaching.main && darkTeaching.fieldText !== darkTeaching.field && darkTeaching.button.includes("0.64 0.1 250") && darkTeaching.buttonShadow === "none", JSON.stringify(darkTeaching));
  await navigateTo(responsivePage, "岗位分析");
  const darkJob = await responsivePage.locator(".job-analysis-workspace").evaluate(element => ({
    heading: getComputedStyle(element.querySelector(".job-analysis-heading")).backgroundColor,
    main: getComputedStyle(element.querySelector(".job-analysis-main")).backgroundColor,
    archive: getComputedStyle(element.querySelector(".job-analysis-archive")).backgroundColor,
    field: getComputedStyle(element.querySelector("textarea")).backgroundColor,
    fieldText: getComputedStyle(element.querySelector("textarea")).color,
    button: getComputedStyle(element.querySelector(".job-analysis-form .primary-button")).backgroundColor,
    buttonShadow: getComputedStyle(element.querySelector(".job-analysis-form .primary-button")).boxShadow,
  }));
  record("深色岗位准备夹阅读层级", darkJob.heading !== "rgb(255, 255, 255)" && darkJob.main !== "rgb(255, 255, 255)" && darkJob.archive !== darkJob.main && darkJob.fieldText !== darkJob.field && darkJob.button.includes("0.64 0.1 250") && darkJob.buttonShadow === "none", JSON.stringify(darkJob));
  await navigateTo(responsivePage, "统计复盘");
  const darkAnalytics = await responsivePage.locator(".analytics-workspace").evaluate(element => {
    const activeBar = element.querySelector(".analytics-day.has-record .analytics-day-track span");
    const quietBar = element.querySelector(".analytics-day:not(.has-record) .analytics-day-track span");
    return {
      sheet: getComputedStyle(element.querySelector(".analytics-sheet")).backgroundColor,
      heading: getComputedStyle(element.querySelector(".analytics-page-heading")).backgroundColor,
      text: getComputedStyle(element.querySelector(".analytics-page-heading h2")).color,
      activeBar: activeBar ? getComputedStyle(activeBar).backgroundColor : null,
      quietBar: quietBar ? getComputedStyle(quietBar).backgroundColor : null,
    };
  });
  record("深色统计复盘阅读层级", darkAnalytics.sheet !== "rgb(255, 255, 255)" && darkAnalytics.heading !== "rgb(255, 255, 255)" && darkAnalytics.text !== darkAnalytics.sheet && (!darkAnalytics.activeBar || !darkAnalytics.quietBar || darkAnalytics.activeBar !== darkAnalytics.quietBar), JSON.stringify(darkAnalytics));
  await navigateTo(responsivePage, "学习报告");
  await responsivePage.locator(".report-history-row").first().click();
  await responsivePage.getByRole("heading", { name: "这段时间留下了什么", exact: true }).waitFor({ state: "visible" });
  const darkReport = await responsivePage.locator(".reports-workspace").evaluate(element => ({
    intro: getComputedStyle(element.querySelector(".report-reader-intro")).backgroundColor,
    paper: getComputedStyle(element.querySelector(".report-reading-paper")).backgroundColor,
    heading: getComputedStyle(element.querySelector(".report-paper-header")).backgroundColor,
    text: getComputedStyle(element.querySelector(".report-paper-header h2")).color,
    choice: getComputedStyle(element.querySelector(".report-period-choice")).backgroundColor,
    download: getComputedStyle(element.querySelector(".report-download > summary")).color,
  }));
  record("深色学习回看阅读层级", darkReport.intro !== "rgb(255, 255, 255)" && darkReport.paper !== "rgb(255, 255, 255)" && darkReport.paper !== darkReport.heading && darkReport.text !== darkReport.paper && darkReport.download !== darkReport.paper, JSON.stringify(darkReport));
  await navigateTo(responsivePage, "今日记录");
  const darkLog = await responsivePage.locator(".logs-workspace").evaluate(element => ({
    panel: getComputedStyle(element.querySelector(".log-entry-panel")).backgroundColor,
    field: getComputedStyle(element.querySelector("textarea")).backgroundColor,
    fieldText: getComputedStyle(element.querySelector("textarea")).color,
    button: getComputedStyle(element.querySelector(".primary-button")).backgroundColor,
    buttonShadow: getComputedStyle(element.querySelector(".primary-button")).boxShadow,
  }));
  record("深色学习记录阅读层级", darkLog.panel !== "rgb(255, 255, 255)" && darkLog.field !== "rgb(255, 255, 255)" && darkLog.fieldText !== darkLog.field && darkLog.button.includes("0.64 0.1 250") && darkLog.buttonShadow === "none", JSON.stringify(darkLog));
  await navigateTo(responsivePage, "笔记库");
  const darkNotes = await responsivePage.locator(".notes-workspace").evaluate(element => ({
    list: getComputedStyle(element.querySelector(".notes-list-panel")).backgroundColor,
    editor: getComputedStyle(element.querySelector(".note-editor-panel")).backgroundColor,
    field: getComputedStyle(element.querySelector(".note-body-field textarea")).backgroundColor,
    fieldText: getComputedStyle(element.querySelector(".note-body-field textarea")).color,
    primary: getComputedStyle(element.querySelector(".primary-button")).backgroundColor,
  }));
  record("深色笔记阅读层级", darkNotes.list !== darkNotes.editor && darkNotes.field !== "rgb(255, 255, 255)" && darkNotes.fieldText !== darkNotes.field && darkNotes.primary.includes("0.64 0.1 250"), JSON.stringify(darkNotes));
  await navigateTo(responsivePage, "学习伙伴");
  const darkCoach = await responsivePage.locator(".coach-page").evaluate(element => ({
    chat: getComputedStyle(element.querySelector(".coach-workspace")).backgroundColor,
    action: getComputedStyle(element.querySelector(".coach-action-note")).backgroundColor,
    accent: getComputedStyle(element.querySelector(".coach-action-note")).borderTopColor,
    field: getComputedStyle(element.querySelector(".coach-form textarea")).backgroundColor,
    fieldText: getComputedStyle(element.querySelector(".coach-form textarea")).color,
    primary: getComputedStyle(element.querySelector(".coach-form .primary-button")).backgroundColor,
  }));
  record("深色学习伙伴阅读层级", darkCoach.chat !== "rgb(255, 255, 255)" && darkCoach.action !== "rgb(255, 255, 255)" && darkCoach.fieldText !== darkCoach.field && darkCoach.primary.includes("0.64 0.1 250") && darkCoach.accent !== darkCoach.primary, JSON.stringify(darkCoach));
  await navigateTo(responsivePage, "能力画像");
  const darkCapability = await responsivePage.locator(".capability-workspace").evaluate(element => {
    const card = element.querySelector(".capability-card");
    const meter = element.querySelector(".capability-meter span");
    const action = element.querySelector(".capability-actions button");
    return {
      workspace: getComputedStyle(element).backgroundColor,
      card: getComputedStyle(card).backgroundColor,
      cardText: getComputedStyle(card).color,
      meter: getComputedStyle(meter).backgroundColor,
      action: getComputedStyle(action).color,
    };
  });
  record("深色能力档案阅读层级", darkCapability.workspace !== "rgb(255, 255, 255)" && darkCapability.card === "rgba(0, 0, 0, 0)" && darkCapability.cardText !== darkCapability.workspace && darkCapability.meter.includes("0.64 0.1 250") && darkCapability.action !== darkCapability.workspace, JSON.stringify(darkCapability));
  await responsivePage.close();
} catch (error) {
  record("端到端回归执行", false, error instanceof Error ? error.message : String(error));
}

record("页面控制台无错误", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));
await browser.close();
const failed = results.filter(result => !result.passed);
console.log(`SUMMARY ${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exitCode = 1;
