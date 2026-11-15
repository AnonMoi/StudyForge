# LearningWorkstation 阶段七开发概览

> 当前状态：需求基准对齐，SQLite migration v38。任务验收证据、文件导入/写入撤销、Agent 变更审计、报告反馈提案、能力评估闭环、练习与代码沙箱、项目深化、错题分析和加密同步已完成；Agent 增量聊天、输出类型/转换预览、驾驶舱实际进步信号、目录规则 UI、首次启动资料导入闭环和流式断线重连已完成。Python 3.12.13 全量回归、真实后端/Chrome 验收已完成。

## 已完成

- 统计复盘升级为按日趋势、主题维度、能力画像成长证据和模型用量汇总。
- 能力评估纳入知识主题与教学作答，并将自动生成的证据写入 `capability_evidence`。
- 备份字段级合并支持 `selections` 字段选择，覆盖复习、教学和模型记录的匹配入口。
- 新增 `backup_merge_batches`，记录合并审计并提供冲突保护撤销。
- 前端统计复盘接入趋势柱状图、主题卡片、能力成长条和 Token/成本摘要。
- 前端备份恢复接入字段勾选、合并批次审计和撤销入口。
- 能力画像接入评估历史和确认式补强计划；新增练习与沙箱工作区，支持算法、SQL 和受限 Python 运行。
- 项目工作台接入独立里程碑实体、看板、时间线和成果证据；复习卡片接入错误类型、主题、日期趋势和补救建议。
- 新增实体已纳入 JSON 导出、备份恢复、审计与恢复撤销。
- 数据库迁移已升级到 v38；设置页和备份恢复页均提供加密同步入口，WebDAV 默认关闭并仅传输加密包。
- 阶段七专项测试已纳入后端测试集，并覆盖统计、备份合并、账单边界和浏览器验收后的关键交互；运行与审计页新增后台提醒调度器状态、最近执行和错误显示。
- 首页导出菜单新增完整学习资料的 Markdown、TXT、HTML 阅读版，后端 `/api/exports/{format}` 覆盖目标、阶段、任务、学习记录、笔记、知识主题和项目；WebDAV 基础地址校验与上传体积边界、笔记 `md` 导出别名已补齐。
- 新任务现在先经过 `/api/tasks/impact-preview` 评估主线关系、前置知识和本周负荷，计划页确认后才写入；Agent 创建任务预览复用同一评估。后端启动脚本已增加 Python 自动探测和 `PYTHON_EXECUTABLE` 覆盖。
- 首次启动向导已补齐“画像/首个计划确认 → 资料目录授权 → 本地扫描 → 导入报告预览 → 用户确认写入”闭环；资料可跳过，向导默认关闭云端发送和写入权限，并可重复打开而不自动执行操作。

## 验证结果

- 前端 TypeScript `--noEmit`：通过。
- 前端 Vite 生产构建：通过，已生成 `frontend/dist/`。
- 后端 `compileall`：通过。
- `git diff --check`：通过。
- 前端 e2e 冒烟脚本 `node --check`：通过；最新生产预览 `http://127.0.0.1:4178` + 本机 Chrome 的 `frontend/e2e-smoke.mjs` 为 **44/44 passed**，桌面/390px 移动端无横向溢出且控制台无错误。
- Python 3.12.13 + `backend\\.venv312` 后端全量回归：**341 个测试收集项全部通过，3 warnings**；没有注入 `pywebpush` stub，依赖不可用时由可选通道降级；`dependency-doctor` 报告 0 findings。
- 目标切片 focused 回归：**75 passed**，覆盖画像草稿、Agent 输出/转换/SSE/Ollama JSON 行/fallback、阶段能力目标、项目元数据、目录规则和驾驶舱进步信号。
- 独立真实后端 `127.0.0.1:8003` 的 ready/config/models/runtime/dashboard 接口通过；真实 Ollama Agent 流式接口收到增量 token、`meta` 和 `done`，调度器无错误。
- `scripts/start-backend.ps1 -ValidateOnly` 已用显式 Python 3.12.13 入口通过；脚本现在优先使用 3.12 原生包，再补充项目依赖，避免 uv trampoline 和 CPython 3.11 ABI 冲突。

## 后续

- 补充更深入的移动端长文本/复杂表单验收，以及全页面无障碍专项复验。
- 供应商账单自动同步和教学结构化评价已完成；后续如接入具体供应商，仍需在本地 `.env` 配置接口地址和密钥，并保持自动同步默认关闭。

## 接续验收（2026-08-20）

- Python 3.12.13 已正确接入：`scripts/start-backend.ps1 -ValidateOnly` 返回 `valid=true`；无 npm fallback 的 `scripts/start-frontend.ps1 -ValidateOnly` 通过；完整回归 **341 个测试通过**。
- 独立 8003 后端真实 API：ready/config/model health/runtime/dashboard 全部通过；本机 Ollama 可用，真实 Agent 流式输出通过，调度器无错误。
- 生产预览 4178 + 本机 Chrome 上 `frontend/e2e-smoke.mjs`：**44/44 passed**；另有 75 个目标切片 focused 测试通过。
- 新增本地可用闭环：计划目标/阶段编辑删除入口；历史学习日志原文和结构化字段可修正并确认保存。

剩余限制主要是外部联调条件：本地 `.env` 已创建但真实 HTTPS WebDAV、云端模型、Web Push VAPID 和 Windows 通知权限仍需用户提供地址/凭据/密钥并显式开启；流式断线自动重连已实现。Agent 输出分类仍是保守规则元数据而非模型自评。
