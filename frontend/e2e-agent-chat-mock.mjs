import http from "node:http";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const host = "127.0.0.1";
const apiPort = Number(process.env.MOCK_API_PORT ?? 18180);
const appPort = Number(process.env.MOCK_APP_PORT ?? 15178);
const appURL = `http://${host}:${appPort}`;
const apiURL = `http://${host}:${apiPort}`;
const executablePath = process.env.PLAYWRIGHT_EXECUTABLE ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const nodeExecutable = process.execPath;
const viteEntry = fileURLToPath(new URL("./node_modules/vite/bin/vite.js", import.meta.url));
const calls = [];
const histories = new Map();
let historyId = 1;

const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type, X-Request-ID",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
};
const dashboard = { today_tasks: [], recent_logs: [], current_goal: null, current_stage: null, weekly_minutes: 0, output_count: 0, pending_review_count: 0, due_reviews: [], weak_capabilities: [], active_projects: [], recent_notes: [], agent_suggestions: [], progress_signal: { status: "no_recent_activity", summary: "暂无证据", window_days: 7, recent_minutes: 0, previous_minutes: 0, recent_evidence_count: 0, previous_evidence_count: 0, recent_completed_tasks: 0, recent_notes: 0, basis: ["日志"] } };
const setup = { completed: true, requires_onboarding: false, profile_confirmed: true, first_plan_generated: true, authorized_directory_count: 0, privacy: { local_data_default: true, cloud_transfer_requires_permission: true, directory_access_requires_explicit_authorization: true } };

function json(res, body, status = 200) {
  res.writeHead(status, { ...cors, "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

async function requestBody(req) {
  let value = "";
  for await (const chunk of req) value += chunk;
  return value ? JSON.parse(value) : {};
}

function rows(sessionId) {
  if (!histories.has(sessionId)) histories.set(sessionId, []);
  return histories.get(sessionId);
}

function addUser(payload) {
  const row = { id: historyId++, session_id: payload.session_id, turn_id: payload.request_id, request_id: payload.request_id, persona: payload.persona, role: "user", turn_status: "pending", provider: null, model_name: null, route_reason: null, failure_kind: null, content: payload.message };
  rows(payload.session_id).push(row);
  return row;
}

function terminal(payload, userRow, status, metadata = {}, answer) {
  Object.assign(userRow, { turn_status: status, ...metadata });
  if (status === "completed") rows(payload.session_id).push({ ...userRow, id: historyId++, role: "assistant", content: answer });
}

async function streamTurn(req, res, payload) {
  calls.push(payload);
  const userRow = addUser(payload);
  let terminalState = false;
  let responseClosed = false;
  res.on("close", () => {
    responseClosed = true;
    if (!terminalState) terminal(payload, userRow, "cancelled", { route_reason: "client_cancelled", failure_kind: "cancelled" });
  });
  res.writeHead(200, { ...cors, "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
  const emit = async (event, data, delay = 45) => {
    await wait(delay);
    if (!responseClosed) res.write(`event: ${event}\ndata: ${JSON.stringify({ request_id: payload.request_id, turn_id: payload.request_id, ...data })}\n\n`);
  };
  const localAttempt = `${payload.request_id}-local`;
  const cloudAttempt = `${payload.request_id}-cloud`;
  const finishFailure = async (failureKind, routeReason, provider = "ollama") => {
    await emit("failed", { status: "failed", provider, model_name: provider === "ollama" ? "mock-local" : "mock-cloud", failure_kind: failureKind, route_reason: routeReason });
    await emit("error", { code: "TURN_FAILED", message: "internal provider text must not render" });
    await emit("done", { status: "failed" });
    terminalState = true;
    terminal(payload, userRow, "failed", { provider, model_name: provider === "ollama" ? "mock-local" : "mock-cloud", route_reason: routeReason, failure_kind: failureKind });
    if (!responseClosed) res.end();
  };
  const finishSuccess = async (provider = "ollama", routeReason = "local_stream_success", replayed = false) => {
    const answer = `可验证回答：${payload.message}`;
    await emit("meta", { provider, model_name: provider === "ollama" ? "mock-local" : "mock-cloud", route_reason: routeReason, output_type: "suggestion", basis: ["当前问题"], uncertainty: "请结合实际结果验证", actions: [] });
    await emit("token", { chunk: answer, ...(replayed ? {} : { attempt_id: provider === "ollama" ? localAttempt : cloudAttempt }) });
    await emit("completed", { status: "completed", provider, model_name: provider === "ollama" ? "mock-local" : "mock-cloud", route_reason: routeReason, replayed });
    await emit("done", { status: "completed", replayed });
    terminalState = true;
    terminal(payload, userRow, "completed", { provider, model_name: provider === "ollama" ? "mock-local" : "mock-cloud", route_reason: routeReason, failure_kind: null }, answer);
    if (!responseClosed) res.end();
  };

  if (payload.message === "illegal-order") {
    await emit("token", { chunk: "must-not-render" });
    await wait(80);
    if (!responseClosed) res.end();
    return;
  }
  await emit("accepted", { status: "pending", replayed: payload.message === "completed-replay" });
  if (payload.message === "illegal-mismatched-turn") {
    await emit("local_started", { request_id: "other-request", turn_id: "other-turn", attempt_id: localAttempt, provider: "ollama" });
    if (!responseClosed) res.end();
    return;
  }
  if (payload.message === "completed-replay") return finishSuccess("ollama", "idempotent_replay", true);
  await emit("local_started", { attempt_id: localAttempt, provider: "ollama", model_name: "mock-local", stage: "local", attempt_status: "running", route_reason: "local_started" });
  if (payload.message === "illegal-cloud-before-local-failure") {
    await emit("cloud_started", { attempt_id: cloudAttempt, provider: "zhiapi" });
    if (!responseClosed) res.end();
    return;
  }
  if (payload.message === "illegal-completed-after-cancelled") {
    await emit("cancelled", { status: "cancelled", failure_kind: "cancelled" });
    await emit("completed", { status: "completed", provider: "ollama" });
    if (!responseClosed) res.end();
    return;
  }
  if (payload.message === "illegal-failed-after-complete") {
    await emit("token", { chunk: "terminal content", attempt_id: localAttempt });
    await emit("completed", { status: "completed", provider: "ollama" });
    await emit("failed", { status: "failed", failure_kind: "provider_error" });
    if (!responseClosed) res.end();
    return;
  }
  if (payload.message === "illegal-superseded-token") {
    await emit("local_failed", { attempt_id: localAttempt, provider: "ollama", failure_kind: "timeout" });
    await emit("cloud_started", { attempt_id: cloudAttempt, provider: "zhiapi" });
    await emit("token", { chunk: "stale content", attempt_id: localAttempt });
    if (!responseClosed) res.end();
    return;
  }
  if (payload.message === "mismatched-attempt") {
    await emit("local_failed", { attempt_id: "wrong-attempt", provider: "ollama", failure_kind: "timeout", route_reason: "local_timeout" });
    await wait(80);
    if (!responseClosed) res.end();
    return;
  }
  if (payload.message.startsWith("slow-")) {
    await wait(1000);
    if (!responseClosed) await finishSuccess();
    return;
  }
  if (payload.message === "provider-failed") {
    if (calls.filter(call => call.message === payload.message).length === 1) return finishFailure("provider_error", "local_provider_error");
    return finishSuccess();
  }
  if (payload.message === "reload-failed") return finishFailure("provider_error", "local_provider_error");

  const localFailure = {
    "timeout-cloud": ["timeout", "local_timeout"],
    "unavailable-cloud": ["unavailable", "local_unavailable"],
    "cloud-disabled": ["unavailable", "cloud_disabled"],
    "budget-blocked": ["unavailable", "local_first_budget_blocked_local_unavailable"],
    "privacy-blocked": ["unavailable", "local_first_privacy_blocked"],
    "both-fail": ["unavailable", "local_unavailable"],
  }[payload.message];
  if (!localFailure) return finishSuccess();
  await emit("local_failed", { attempt_id: localAttempt, provider: "ollama", model_name: "mock-local", stage: "local", attempt_status: localFailure[0] === "timeout" ? "timed_out" : "failed", failure_kind: localFailure[0], route_reason: localFailure[1] });
  if (["cloud-disabled", "budget-blocked", "privacy-blocked"].includes(payload.message)) return finishFailure(localFailure[0], localFailure[1]);
  await emit("cloud_started", { attempt_id: cloudAttempt, provider: "zhiapi", model_name: "mock-cloud", stage: "cloud", attempt_status: "running", route_reason: "cloud_started" }, 120);
  if (payload.message === "both-fail") return finishFailure("provider_error", "cloud_provider_error", "zhiapi");
  return finishSuccess("zhiapi", "local_first_local_unavailable_cloud_fallback");
}

const apiServer = http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") { res.writeHead(204, cors); return res.end(); }
  const path = new URL(req.url, apiURL).pathname;
  if (path === "/api/agent/chat/stream" && req.method === "POST") return streamTurn(req, res, await requestBody(req));
  if (path.startsWith("/api/agent/history/")) return json(res, rows(decodeURIComponent(path.slice("/api/agent/history/".length))));
  if (path === "/api/dashboard") return json(res, dashboard);
  if (path === "/api/setup/status") return json(res, setup);
  if (path === "/api/models/health") return json(res, { local: { provider: "ollama", model: "mock-local", available: true }, cloud: { provider: "zhiapi", model: "mock-cloud", enabled: true, configured: true, available: true } });
  if (path === "/api/user-profile") return json(res, { id: 1, major: "", grade: "", long_term_goal: "", target_job_directions: [], confirmed_skills: [], unverified_skills: [], weak_capabilities: [], learning_preferences: [], proactive_level: "中主动", profile_confirmed: true });
  if (path === "/api/reminders") return json(res, { reminders: [], pending_count: 0 });
  return json(res, {});
});

await new Promise((resolve, reject) => apiServer.listen(apiPort, host, resolve).once("error", reject));
const vite = spawn(nodeExecutable, [viteEntry, "--host", host, "--port", String(appPort), "--strictPort"], {
  cwd: fileURLToPath(new URL(".", import.meta.url)),
  env: { ...process.env, VITE_API_BASE_URL: apiURL },
  stdio: ["ignore", "pipe", "pipe"],
});
let viteLog = "";
vite.stdout.on("data", chunk => { viteLog += chunk; });
vite.stderr.on("data", chunk => { viteLog += chunk; });
for (let attempt = 0; attempt < 80; attempt += 1) {
  try { if ((await fetch(appURL)).ok) break; } catch {}
  if (attempt === 79) throw new Error(`Vite did not start: ${viteLog}`);
  await wait(100);
}

const browser = await chromium.launch({ headless: true, executablePath });
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
await context.addInitScript(() => localStorage.setItem("learning-workstation-session-id", "phase4d-e2e"));
const page = await context.newPage();
const unexpectedErrors = [];
page.on("pageerror", error => unexpectedErrors.push(error.message));
page.on("console", message => {
  if (message.type() === "error" && !message.text().includes("agent_stream_protocol_violation")) unexpectedErrors.push(message.text());
});

const assistant = turnId => page.locator(`[data-turn-role="assistant"][data-turn-id="${turnId}"]`);
const latestCall = text => [...calls].reverse().find(call => call.message === text);
async function openAnna() {
  if (!await page.getByRole("dialog", { name: "八奈见杏菜" }).count()) await page.getByRole("button", { name: "打开八奈见杏菜学习伙伴" }).click();
  await page.getByRole("dialog", { name: "八奈见杏菜" }).waitFor();
  return page.getByLabel("发送给杏菜");
}
async function submit(input, text) {
  await input.fill(text);
  for (let index = 0; index < 100; index += 1) {
    if (await input.evaluate(element => !element.closest("form")?.querySelector('button[type="submit"]')?.disabled)) break;
    await wait(10);
  }
  for (let index = 0; index < 100 && !latestCall(text); index += 1) {
    await input.press("Enter");
    await wait(20);
  }
  const call = latestCall(text);
  assert(call?.request_id, `request not received: ${text}`);
  return call.request_id;
}
async function expectState(turnId, state) {
  await assistant(turnId).filter({ has: page.locator(`[data-lifecycle-state="${state}"]`) }).waitFor().catch(async () => {
    await page.locator(`[data-turn-id="${turnId}"][data-lifecycle-state="${state}"]`).waitFor();
  });
}

const checks = {};
try {
  await page.goto(appURL, { waitUntil: "domcontentloaded" });
  await page.locator(".studyforge-shell").waitFor();
  let annaInput = await openAnna();

  await annaInput.fill("第一行");
  await annaInput.press("Shift+Enter");
  checks.shiftEnter = await annaInput.inputValue() === "第一行\n";
  await annaInput.fill("中文输入");
  await annaInput.dispatchEvent("compositionstart", { data: "中" });
  await annaInput.dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true, keyCode: 229 });
  checks.ime = !latestCall("中文输入");
  await annaInput.dispatchEvent("compositionend", { data: "中文输入" });

  const beforeDouble = calls.length;
  const localId = await submit(annaInput, "local-success");
  await annaInput.press("Enter");
  await page.locator(`[data-turn-id="${localId}"][data-lifecycle-state="completed"]`).waitFor();
  checks.B1 = await assistant(localId).count() === 1 && await assistant(localId).getByText("本机处理", { exact: true }).count() === 1;
  checks.doubleSubmit = calls.length === beforeDouble + 1;

  const timeoutId = await submit(annaInput, "timeout-cloud");
  await page.locator(`[data-turn-id="${timeoutId}"][data-lifecycle-state="fallback_evaluating"]`).waitFor();
  checks.fallbackNotGuessed = await assistant(timeoutId).getByText("已切换到云端继续处理", { exact: true }).count() === 0;
  await page.locator(`[data-turn-id="${timeoutId}"][data-lifecycle-state="pending_cloud"]`).waitFor();
  checks.B2 = await assistant(timeoutId).count() === 1;
  await page.locator(`[data-turn-id="${timeoutId}"][data-lifecycle-state="completed"]`).waitFor();
  checks.B2 = checks.B2 && await assistant(timeoutId).getByText("云端补充", { exact: true }).count() === 1;

  const unavailableId = await submit(annaInput, "unavailable-cloud");
  await page.locator(`[data-turn-id="${unavailableId}"][data-lifecycle-state="completed"][data-provider="zhiapi"]`).waitFor();
  checks.B3 = await assistant(unavailableId).count() === 1;

  for (const [message, copy, key] of [
    ["cloud-disabled", "本地服务暂时不可用，且未启用云端补充。", "B4"],
    ["budget-blocked", "本地处理未完成，云端预算限制阻止了继续尝试。", "B5"],
    ["privacy-blocked", "本地处理未完成，隐私设置阻止了云端处理。", "B6"],
    ["both-fail", "处理服务暂时异常，请稍后重试。", "B7"],
  ]) {
    const id = await submit(annaInput, message);
    await page.locator(`[data-turn-id="${id}"][data-lifecycle-state="failed"]`).waitFor();
    checks[key] = await assistant(id).getByText(copy, { exact: true }).count() === 1 && await assistant(id).getByText("已切换到云端继续处理", { exact: true }).count() === 0;
  }

  const cancelId = await submit(annaInput, "slow-explicit-cancel");
  await page.locator(`[data-turn-id="${cancelId}"][data-lifecycle-state="pending_local"]`).waitFor();
  await assistant(cancelId).getByRole("button", { name: "取消这次请求" }).click();
  await page.locator(`[data-turn-id="${cancelId}"][data-lifecycle-state="cancelled"]`).waitFor();
  await wait(1100);
  checks.B8 = await assistant(cancelId).getByText("已取消这次请求。", { exact: true }).count() === 1 && await assistant(cancelId).getByText("可验证回答", { exact: false }).count() === 0;

  const closeId = await submit(annaInput, "slow-close-drawer");
  await page.locator(`[data-turn-id="${closeId}"][data-lifecycle-state="pending_local"]`).waitFor();
  await page.getByRole("button", { name: "关闭学习伙伴" }).click();
  await wait(160);
  annaInput = await openAnna();
  await page.locator(`[data-turn-id="${closeId}"][data-lifecycle-state="cancelled"]`).waitFor();
  checks.B9 = await page.locator(`[data-turn-id="${closeId}"][data-lifecycle-state="pending_local"]`).count() === 0;

  const retryId1 = await submit(annaInput, "provider-failed");
  await page.locator(`[data-turn-id="${retryId1}"][data-lifecycle-state="failed"]`).waitFor();
  const pairsBeforeRetry = { users: await page.locator('[data-turn-role="user"]').count(), assistants: await page.locator('[data-turn-role="assistant"]').count() };
  await assistant(retryId1).getByRole("button", { name: "重新发送这条消息" }).click();
  for (let index = 0; index < 100 && calls.filter(call => call.message === "provider-failed").length < 2; index += 1) await wait(10);
  const retryCalls = calls.filter(call => call.message === "provider-failed");
  const retryId2 = retryCalls.at(-1).request_id;
  await page.locator(`[data-turn-id="${retryId2}"][data-lifecycle-state="completed"]`).waitFor();
  checks.B11 = retryId1 !== retryId2
    && pairsBeforeRetry.users === await page.locator('[data-turn-role="user"]').count()
    && pairsBeforeRetry.assistants === await page.locator('[data-turn-role="assistant"]').count()
    && await assistant(retryId2).getByText("可验证回答：provider-failed", { exact: true }).count() === 1;

  const replayId = await submit(annaInput, "completed-replay");
  await page.locator(`[data-turn-id="${replayId}"][data-lifecycle-state="completed"]`).waitFor();
  checks.B12 = await assistant(replayId).count() === 1 && await assistant(replayId).getByText("可验证回答：completed-replay", { exact: true }).count() === 1;

  const reloadFailedId = await submit(annaInput, "reload-failed");
  await page.locator(`[data-turn-id="${reloadFailedId}"][data-lifecycle-state="failed"]`).waitFor();
  const reloadCloudId = await submit(annaInput, "unavailable-cloud");
  await page.locator(`[data-turn-id="${reloadCloudId}"][data-lifecycle-state="completed"]`).waitFor();
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator(".studyforge-shell").waitFor();
  annaInput = await openAnna();
  await page.locator(`[data-turn-id="${reloadFailedId}"][data-lifecycle-state="failed"]`).waitFor();
  await page.locator(`[data-turn-id="${reloadCloudId}"][data-lifecycle-state="completed"]`).waitFor();
  checks.B13 = await assistant(reloadFailedId).getByRole("button", { name: "重新发送这条消息" }).count() === 1;
  checks.B14 = await assistant(reloadCloudId).getByText("云端补充", { exact: true }).count() === 1;

  const illegalId = await submit(annaInput, "illegal-order");
  await page.locator(`[data-turn-id="${illegalId}"][data-lifecycle-state="protocol_error"]`).waitFor();
  checks.B16 = await assistant(illegalId).getByText("本次请求状态异常，请重试。", { exact: true }).count() === 1 && await assistant(illegalId).getByText("must-not-render", { exact: true }).count() === 0;
  for (const message of ["illegal-cloud-before-local-failure", "illegal-completed-after-cancelled", "illegal-failed-after-complete", "illegal-superseded-token", "illegal-mismatched-turn"]) {
    const id = await submit(annaInput, message);
    await page.locator(`[data-turn-id="${id}"][data-lifecycle-state="protocol_error"]`).waitFor();
    checks.B16 = checks.B16 && await assistant(id).getByText("本次请求状态异常，请重试。", { exact: true }).count() === 1;
  }
  const mismatchId = await submit(annaInput, "mismatched-attempt");
  await page.locator(`[data-turn-id="${mismatchId}"][data-lifecycle-state="protocol_error"]`).waitFor();
  checks.B17 = await assistant(mismatchId).getByText("本次请求状态异常，请重试。", { exact: true }).count() === 1;

  await page.getByRole("button", { name: "关闭学习伙伴" }).click();
  await page.getByRole("button", { name: "学习", exact: true }).click();
  await page.getByRole("button", { name: "学习伙伴", exact: true }).click();
  const coachInput = page.getByLabel("发送给学习伙伴");
  const coachCancelId = await submit(coachInput, "slow-coach-navigation");
  await page.locator(`[data-turn-id="${coachCancelId}"][data-lifecycle-state="pending_local"]`).waitFor();
  await page.getByRole("button", { name: "今天", exact: true }).click();
  await page.getByRole("button", { name: "今日总览", exact: true }).click();
  for (let index = 0; index < 100 && rows("phase4d-e2e").find(row => row.turn_id === coachCancelId)?.turn_status === "pending"; index += 1) await wait(20);
  await page.getByRole("button", { name: "学习", exact: true }).click();
  await page.getByRole("button", { name: "学习伙伴", exact: true }).click();
  await page.locator(`[data-turn-id="${coachCancelId}"][data-lifecycle-state="cancelled"]`).waitFor();
  checks.B10 = await page.locator(`[data-turn-id="${coachCancelId}"][data-lifecycle-state="pending_local"]`).count() === 0;

  const activeCoach = await submit(page.getByLabel("发送给学习伙伴"), "slow-coach-concurrent");
  annaInput = await openAnna();
  const activeAnna = await submit(annaInput, "slow-anna-concurrent");
  await page.locator(`[data-turn-id="${activeCoach}"][data-lifecycle-state="pending_local"][data-provider="ollama"]`).waitFor();
  await page.locator(`[data-turn-id="${activeAnna}"][data-lifecycle-state="pending_local"][data-provider="ollama"]`).waitFor();
  checks.B15 = activeCoach !== activeAnna && latestCall("slow-coach-concurrent").persona === "study-coach" && latestCall("slow-anna-concurrent").persona === "anna";
  await assistant(activeAnna).getByRole("button", { name: "取消这次请求" }).click();
  await page.getByRole("button", { name: "关闭学习伙伴" }).click();
  await page.locator(`[data-turn-id="${activeCoach}"]`).getByRole("button", { name: "取消这次请求" }).click();

  const responsive = {};
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: width < 600 ? 844 : 960 });
    responsive[width] = await page.evaluate(() => ({
      noOverflow: document.documentElement.scrollWidth <= window.innerWidth + 1,
      touchTargets: [...document.querySelectorAll('[aria-label="取消这次请求"], [aria-label="重新发送这条消息"]')].every(element => element.getBoundingClientRect().height >= (window.innerWidth <= 640 ? 44 : 36)),
    }));
  }
  checks.mobile = Object.values(responsive).every(result => result.noOverflow && result.touchTargets);
  await page.evaluate(() => document.querySelector(".theme-toggle")?.click());
  checks.dark = await page.evaluate(() => getComputedStyle(document.querySelector(".coach-composer")).backgroundColor !== "rgba(0, 0, 0, 0)");
  checks.B18 = checks.shiftEnter && checks.ime && checks.doubleSubmit;
  checks.noUnexpectedConsoleErrors = unexpectedErrors.length === 0;

  const required = Array.from({ length: 18 }, (_, index) => `B${index + 1}`).filter(key => key !== "B10" || checks.B10 !== undefined);
  const missing = required.filter(key => checks[key] === undefined);
  assert(!missing.length, `missing scenarios: ${missing.join(", ")}`);
  const failed = Object.entries(checks).filter(([, value]) => !value).map(([key]) => key);
  console.log(JSON.stringify({ passed: !failed.length, checks, failed, calls: calls.map(({ message, persona, request_id }) => ({ message, persona, request_id })), unexpectedErrors }));
  if (failed.length) process.exitCode = 1;
} finally {
  await context.close();
  await browser.close();
  vite.kill();
  await new Promise(resolve => apiServer.close(resolve));
}
