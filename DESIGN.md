# Design — StudyForge

StudyForge 的锁定设计系统。所有应用页面先读取本文件；扩展系统时修改这里，不为单页另起主题。

> 前端实施与验收基线见 [`FRONTEND_DESIGN_PLAN.md`](./FRONTEND_DESIGN_PLAN.md)。两份文档如有冲突，以用户最新确认的前端需求为准；当前阶段只改首页、全局导航壳与杏菜助手，不顺带重做其他业务页。

## Direction Contract

- **THESIS**：界面是一座校准式学习观测台；拒绝“侧栏 + 顶栏 + 一屏圆角卡片”的通用后台。
- **OWN WORLD**：深校园蓝负责结构，偏冷纸白承载工作内容，黄色只标记当前步骤与确认；状态同时由文字、线型和图标表达。
- **STORY**：用户先看见今天要推进的任务，再开始学习、提交证据，最后通过证据轨道进入复习与周期判断。
- **FIRST VIEWPORT**：五域导航位于左侧；顶部只保留位置、搜索和统一系统状态；首页上方是缩短的咨询室场景，下方立即进入当前任务与证据工作台。
- **FORM**：Operate / Workbench；方向种子 `9b2d43a2`。签名元素是“学习证据轨道”，不是装饰性卡片。
- **FINISH**：unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

## Genre

playful-operate：亲切但不幼稚，功能密度和扫描效率优先。品牌个性集中在首页场景、杏菜对白和证据确认节点。

## Macrostructure Family

- App shell：Workbench，以五个任务域和上下文工作区组织功能。
- 高频学习页：Calibrated Rail，当前任务和证据沿一条稳定纵轴组织。
- 内容阅读页：Long Document，减少容器，依靠标题、段落和细分隔线。
- 系统配置页：Spec Sheet，以固定列、明确状态和风险等级组织设置。

## Theme

- Paper：`oklch(98% 0.008 250)`
- Paper 2：`oklch(95% 0.014 250)`
- Ink：`oklch(26% 0.035 250)`
- Ink 2：`oklch(48% 0.03 250)`
- Rule：`oklch(84% 0.025 250)`
- Structure：`oklch(35% 0.09 250)`
- Accent：`oklch(78% 0.14 85)`
- Focus：`oklch(54% 0.15 250)`

紫色仅允许出现在首页咨询室背景及其直接衍生状态，不进入普通页面、按钮或数据可视化。

## Typography

- Display：`Trebuchet MS` + `Microsoft YaHei`，600–700，normal；仅用于品牌、首页主句和杏菜对白。
- Body：`Segoe UI` + `Microsoft YaHei`，400–650；用于所有操作界面。
- Mono/Data：`Cascadia Mono` + `Consolas`，400–600；用于时间、ID、日志和对齐数字。
- 正文默认 15px、行高 1.65；辅助文字不小于 12px。
- 数值容器使用 `font-variant-numeric: tabular-nums`。

## Spacing

使用 4px 基准的命名间距。页面不得通过随手写入的新数值制造另一套节奏。

## Motion

- 只动画 `transform` 和 `opacity`。
- 页面本身不做普遍滚动淡入。
- 状态轨道允许一次 160–220ms 的定位移动；杏菜场景保留轻微入场和指针景深。
- `prefers-reduced-motion` 下退化为不超过 150ms 的透明度变化或无动画。

## Microinteractions Stance

- 保存结果优先静默更新；跨上下文异步结果才使用通知。
- 可撤销操作优先“执行 + 撤销”，不可逆操作保留确认。
- 焦点环立即出现，不参与过渡。
- 所有交互控件覆盖 default、hover、focus、active、disabled、loading、error、success 中适用的状态。

## CTA Voice

- Primary：黄色实底、深蓝文字、8px 圆角，使用具体动词，例如“开始任务”“保存记录”“确认写入”。
- Secondary：纸面底 + 蓝灰细边框，不使用发光阴影或玻璃效果。
- 文本链接：只在低风险导航中使用，带稳定下划线或箭头。

## Product Components

- `DomainRail`：五个任务域，不直接复制源码模块列表。
- `EvidenceRail`：来源、时间、确认状态、关联任务。
- `TaskLifecycleRow`：计划、计时、证据、验收、复习状态。
- `LearningPath`：目标、阶段、任务的结构关系。
- `ReviewQueue`：到期、错误类型、回忆质量。
- `SystemBoundaryNotice`：本地、云端、写入权限和失败恢复。

## Per-page Allowances

- 首页可以使用已批准的杏菜与咨询室图像。
- 普通应用页不得新增装饰图像、渐变背景、漂浮图形或无业务意义的插画。
- 知识图谱和统计可使用业务数据图形，但必须提供文字替代与窄屏滚动策略。

## What Pages Must Share

- 五域导航、顶部位置与统一系统状态入口。
- 颜色、字体、按钮语言、触控目标和状态语义。
- 内容容器以规则线和版式组织，阴影只属于浮层。
- 证据、模型推断与用户确认的视觉区分。

## What Pages May Differ

- 高频操作页可以使用证据轨道；阅读页可以使用连续文档；系统页可以使用规格表。
- 首页场景可以更具角色感，其他页面保持安静。
- 页面密度根据任务改变，但不改变主题和控件语言。

## Exports

生产 Token 位于 `tokens.css`。项目当前不使用 Tailwind 或 shadcn；若未来接入，必须从 `tokens.css` 映射，而不是另建主题。
