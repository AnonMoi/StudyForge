import { chromium } from "playwright";
import { runMockOnboarding } from "./e2e-onboarding-helper.mjs";

const baseURL = process.env.BASE_URL ?? "http://127.0.0.1:4174";
const apiBaseURL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
const executablePath = process.env.PLAYWRIGHT_EXECUTABLE ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const calls = [];
const profile = {
  id: 1,
  major: "数据科学与大数据技术",
  grade: "大一",
  long_term_goal: "建立可迁移的计算机基础",
  target_job_directions: [],
  confirmed_skills: [],
  unverified_skills: [],
  weak_capabilities: ["Python 工程化"],
  learning_preferences: [],
  proactive_level: "中主动",
  profile_confirmed: false,
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
};
const setup = { completed: false, requires_onboarding: true, profile_confirmed: false, first_plan_generated: false, authorized_directory_count: 0, privacy: { local_data_default: true, cloud_transfer_requires_permission: true, directory_access_requires_explicit_authorization: true } };

function json(body, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

const browser = await chromium.launch({ headless: true, executablePath });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await page.route(`${apiBaseURL}/**`, async route => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  calls.push(`${request.method()} ${path}`);
  if (path === "/api/dashboard") return route.fulfill(json({ today_tasks: [], recent_logs: [], current_goal: null, current_stage: null, weekly_minutes: 0, output_count: 0, pending_review_count: 0, agent_suggestions: [], due_reviews: [], weak_capabilities: [], active_projects: [], recent_notes: [] }));
  if (path === "/api/models/health") return route.fulfill(json({ local: { provider: "ollama", model: "test-local", available: false }, cloud: { provider: "zhiapi", model: "test-cloud", enabled: false, configured: false, available: false } }));
  if (path === "/api/models/budget") return route.fulfill(json({ calls_used: 0, daily_call_limit: 20, remaining_calls: 20, cost_used: 0, cost_limit: 2 }));
  if (path === "/api/settings") return route.fulfill(json({ local_model: "test-local", cloud_model: "test-cloud", cloud_enabled: false, cloud_key_configured: false, model_routing_mode: "local_first", daily_cloud_call_limit: 20, daily_cost_limit: 2, max_tokens_per_request: 12000, local_confidence_threshold: 0.65, cloud_input_price_per_1k: 0.02, cloud_output_price_per_1k: 0.06, report_model_enhancement_enabled: false, native_notifications_enabled: false, native_notifications_available: false }));
  if (path === "/api/sync/cloud/status") return route.fulfill(json({ configured: false, provider: "webdav", path: "", warning: "WebDAV 未配置。" }));
  if (path === "/api/reminders") return route.fulfill(json({ reminders: [], pending_count: 0 }));
  if (path === "/api/setup/status") return route.fulfill(json(setup));
  if (path === "/api/user-profile") return route.fulfill(json(profile));
  if (path === "/api/setup/initialize") {
    const body = JSON.parse(request.postData() ?? "{}");
    if (!body.confirmed) return route.fulfill(json({ executed: false, requires_confirmation: true, profile_preview: { ...profile, ...body.profile, profile_confirmed: true }, plan_preview: { goal_title: body.profile.long_term_goal, stage_title: "基础能力诊断", task_title: "完成首次学习基线诊断", capability_targets: ["Python 工程化"] } }));
    Object.assign(setup, { completed: true, requires_onboarding: false, profile_confirmed: true, first_plan_generated: true });
    return route.fulfill(json({ executed: true, requires_confirmation: false, profile: { ...profile, ...body.profile, profile_confirmed: true }, first_plan_generated: true, setup }));
  }
  if (path === "/api/authorized-directories" && request.method() === "GET") return route.fulfill(json([]));
  if (path === "/api/authorized-directories" && request.method() === "POST") {
    Object.assign(setup, { authorized_directory_count: 1 });
    return route.fulfill(json({ id: 1, path: "C:\\LearningMaterials", label: "课程资料", active: true, local_analysis: true, cloud_transfer: false, write_access: false, excluded_extensions: [], authorized_at: "2026-08-20T00:00:00Z", revoked_at: null, last_scanned_at: null, scan_enabled: true }, 201));
  }
  if (path === "/api/authorized-directories/1/scan") return route.fulfill(json({ import_id: 1, files_scanned: 1, files: [{ relative_path: "python.md" }] }));
  if (path === "/api/imports/1/confirm") {
    const body = JSON.parse(request.postData() ?? "{}");
    if (!body.confirmed) return route.fulfill(json({ executed: false, requires_confirmation: true, files: 1, preview: [{ imported_file_id: 1, relative_path: "python.md", source_path: "python.md", suggested_topics: ["Python"], will_create_note: true, already_confirmed: false }] }));
    return route.fulfill(json({ executed: true, confirmed_files: 1, created_topics: 1, created_notes: 1, created_tasks: 0, created_reviews: 1 }));
  }
  if (path === "/api/setup/complete") {
    Object.assign(setup, { completed: true, requires_onboarding: false });
    return route.fulfill(json(setup));
  }
  return route.fulfill(json({}));
});

try {
  await page.goto(baseURL, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "今天，继续往前一点。", level: 2 }).waitFor();
  await page.getByRole("button", { name: "以后再说", exact: true }).click();
  await page.reload({ waitUntil: "domcontentloaded" });
  if (await page.getByLabel("初始化设置提醒").count()) throw new Error("当前会话选择稍后处理后不应重复提醒");
  await page.evaluate(() => sessionStorage.removeItem("learning-workstation.setup-reminder"));
  await page.reload({ waitUntil: "domcontentloaded" });
  await runMockOnboarding(page);
  const completed = calls.includes("POST /api/setup/complete") && calls.includes("POST /api/imports/1/confirm");
  await page.reload({ waitUntil: "domcontentloaded" });
  const reminderAfterCompletion = await page.getByLabel("初始化设置提醒").count();
  const setupEntryAvailable = await page.getByRole("button", { name: "打开初始化设置" }).count();
  const passed = completed && reminderAfterCompletion === 0 && setupEntryAvailable === 1;
  console.log(JSON.stringify({ passed, reminderAfterCompletion, setupEntryAvailable, calls }));
  if (!passed) process.exitCode = 1;
} finally {
  await browser.close();
}
