// Shared non-blocking setup reminder helpers for browser smoke tests and screenshot scripts.
//
// Every function is idempotent and safe to call on an already-initialized app:
// they no-op (or return false) when the wizard is not present, and never mutate
// real user data beyond the API calls the wizard itself would make.
//
// Usage:
//   import { dismissOnboarding, hasOnboarding, runMockOnboarding } from "./e2e-onboarding-helper.mjs";

/** Return true when the incomplete-setup reminder is currently rendered. */
export async function hasOnboarding(page) {
  return (await page.getByLabel("初始化设置提醒").count()) > 0;
}

/**
 * Defer the non-blocking reminder for the current browser session.
 */
export async function dismissOnboarding(page) {
  const defer = page.getByRole("button", { name: "以后再说", exact: true });
  if (await defer.isVisible().catch(() => false)) {
    await defer.click();
    await page.waitForTimeout(180);
    return true;
  }
  return false;
}

/**
 * Drive the complete setup-center flow against the mock API contract defined in
 * e2e-onboarding-mock.mjs: profile preview -> confirm main line -> authorize and
 * scan a directory -> confirm import -> finish setup. Requires the same mock
 * route table to be registered before navigation.
 */
export async function runMockOnboarding(page) {
  await page.getByLabel("初始化设置提醒").waitFor();
  if (await page.getByRole("dialog").count()) throw new Error("首次打开不应出现阻塞式设置对话框");
  await page.getByRole("button", { name: "开始设置", exact: true }).click();
  await page.getByRole("heading", { name: "初始化设置", level: 2 }).waitFor();
  if (!(await page.getByPlaceholder("你希望长期建立什么能力？").count())) {
    throw new Error(`初始化设置缺少画像编辑器：${(await page.locator("body").innerText()).slice(0, 2000)}`);
  }
  await page.getByPlaceholder("你希望长期建立什么能力？").fill("建立可迁移的计算机基础");
  await page.getByRole("button", { name: "预览首版学习主线", exact: true }).click();
  await page.getByRole("button", { name: "确认并建立学习主线", exact: true }).click();
  await page.getByLabel("首次启动资料目录").fill("C:\\LearningMaterials");
  await page.getByLabel("首次启动目录名称").fill("课程资料");
  await page.getByRole("button", { name: "授权并扫描目录", exact: true }).click();
  await page.getByText("导入报告预览", { exact: true }).waitFor();
  await page.getByRole("button", { name: "确认并写入知识库", exact: true }).click();
  await page.getByRole("button", { name: "完成设置", exact: true }).click();
}
