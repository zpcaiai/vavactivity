# VAV 前端功能与布局重设计方案（2026-08）

状态：已实施（本文件与 `apps/`、`packages/` 中的代码同批提交）
适用范围：`apps/user-web`、`apps/admin-web`、`packages/design-tokens`、`packages/ui-core`、`packages/ui-user`、`packages/ui-admin`

---

## 一、为什么要重做

对现有代码的审阅得到 5 条结构性结论，它们共同解释了「功能设计和页面布局不够好」：

### 1. 登录后没有产品外壳（最严重）

`apps/user-web/src/router/index.ts` 中 **60 余条 `/account/*` 路由全部挂在 `PublicLayout` 之下**。
`PublicLayout` 是一个营销站头部：品牌字标 + 5 条一级链接 + 汉堡菜单。这意味着：

- 用户付费后进入的「会员空间」，和未登录用户看到的官网，是同一套导航；
- 婚恋主线（推荐 / 互选 / 邀请 / 关系）在导航里**没有任何入口**，只能靠深链接抵达；
- `AccountPage.vue` 作为账户首页只有 4 个裸链接，承担不了枢纽职责。

### 2. 「巨型页面」：一个组件服务 5–16 条路由

| 组件 | 服务的路由数 | 切换机制 |
|---|---|---|
| `PrivacyCenterPage.vue` (417 行) | 11 | `route.meta` |
| `MatchmakingInteractionsPage.vue` (390 行) | 7 | `route.meta.interactionSection` |
| `MembershipPage.vue` (208 行) | 9 | 路径判断 |
| `SafetyCenterPage.vue` (251 行) | 6 | 路径判断 |
| `ExperiencePage.vue` (203 行) | 5 | `route.meta.experienceSection` |
| `DatingProfilePage.vue` (830 行) | 7 | 内部 tab |
| 管理端 15 个 `*ManagementPage.vue` | 10–17 各 | `route.meta.*Section` |

后果：URL 变了但页面骨架不变，每个页面没有属于自己的标题层级、工具条、空/错/载状态与操作区；组件内部靠 `v-if` 堆叠，无法复用也无法单独测试。

### 3. 设计系统存在，但被绕开

`packages/design-tokens` 已有 primitive / semantic / component / density / layout / motion 六层 token，`ui-core` 已有 9 个可访问性良好的基础组件。但：

- `apps/user-web/src/assets/main.css` 有 **2126 行**、大量硬编码色值（`#a62a2a`、`#f7f1e8`、`#e2d8c8`…），与 `--vav-*` token 并行且冲突；
- 深色 / 高对比主题因此只对 `ui-core` 组件生效，页面级样式全部失效；
- Tailwind 已引入但几乎未使用，属于纯负担。

### 4. i18n 存在，但被绕开

三语 locale 文件齐全，`ExperiencePage`、`PublicLayout` 页脚、`AccountPage` 等却直接硬编码简体中文，繁体与英文用户会看到中英混排。

### 5. 管理端导航是 30 条平铺列表

`AdminLayout.vue` 的菜单是一个无分组的 30 项 `el-menu`，而路由实际有 250+ 条。运营人员无法建立心智模型；每个模块的 10–17 个 section 只能通过页面内部的自绘 tab 抵达，形态各不相同。

---

## 二、功能重规划

### 2.1 以真实用户旅程重组，而非以后端模块重组

现状是「后端有什么模块，前端就有什么页面」。重规划后按用户旅程分为 5 个空间：

```
公共空间 (public)        未登录可见 · 营销与内容
  首页 / 关于 / 见证 / 文章 / 活动 / 课程 / 辅导 / 服务目录 / 会员方案 / 帮助 / 安全说明

会员空间 (app)           登录后 · 产品主体
  ├─ 概览        今日待办、进行中旅程、未读通知、会员状态、下一步建议
  ├─ 缘分        婚恋档案 · 推荐 · 喜欢与互选 · 认识邀请 · 关系旅程
  ├─ 成长        我的活动 · 我的课程 · 辅导预约 · AI 辅导
  ├─ 交易        订单 · 订阅 · 权益 · 会员与用量
  └─ 账户        资料 · 通知偏好 · 隐私与数据权利 · 安全中心 · 登录会话

专注空间 (focus)         全屏无干扰 · 单任务
  结账 / 支付处理 / 课程学习 / AI 对话 / 婚恋档案引导 / 活动后互选调研

登录空间 (auth)          登录 · 注册 · 验证 · 找回密码
```

**为什么这样分**：概览页解决 P2「统一 Dashboard 与待办聚合」；「缘分」把此前散落在 6 个入口的婚恋主线收成一条线；「专注空间」让结账、学习、AI 对话、档案引导摆脱营销导航干扰——这四类是转化与完成率最敏感的流程。

### 2.2 概览页（新增，会员空间首页）

聚合 `GET /experience/home`（已存在，返回 `critical_tasks` / `next_tasks` / `membership` / `unread_notifications` / `active_journeys` / `priority_policy`），按后端既定优先级顺序渲染：

```
安全 > 隐私 > 付款 > 已购服务 > 下一步 > 发现 > 营销
```

版块：**必须处理**（critical_tasks，红色强调）→ **建议下一步**（next_tasks）→ **进行中的旅程** → **我的服务快捷区** → **会员与用量**。
空态不是「暂无数据」，而是给出该分区的第一个可执行动作。

### 2.3 页面拆分（巨型页面 → 真实子页面）

| 原巨型页面 | 拆分为 | 状态 |
|---|---|---|
| `ExperiencePage`（5 条路由） | `DashboardPage` · `TasksPage` · `JourneysPage` · `SearchPage` · `HelpPage` | ✅ |
| `MatchmakingInteractionsPage`（7 条路由） | `MatchesPage` · `MatchDetailPage` · `InvitationsPage` · `InvitationDetailPage` · `LikesPage` · `SkipsPage` · `ContactExchangePage` | ✅ |
| `PrivacyCenterPage`（11 条路由，417 行） | `ProfilePage` · `PrivacySettingsPage` · `ConsentsPage` · `DataRequestsPage` · `AiMemoryPage` | ✅ |
| `MembershipPage`（9 条路由） | `PlansPage` · `MyMembershipPage` · `BenefitsPage` · `UsagePage` · `ManageMembershipPage` · `MembershipHistoryPage` | ✅ |
| `SafetyCenterPage`（6 条路由） | `SafetySupportPage` · `SafetyOverviewPage` · `ReportsPage` · `BlocksPage` · `RestrictionsPage` · `AppealsPage` | ✅ |
| `DatingProfilePage`（830 行 / 7 条路由） | `ProfileOverviewPage` · `ProfileFieldsPage` · `ProfilePhotosPage` · `ProfilePreferencesPage` · `ProfilePrivacyPage` · `ProfilePreviewPage` · `ProfileReviewPage` | ✅ |

六个巨型组件全部移出 `src`（现存于 `_to_delete/superseded-pages/`，确认无回归后可删除），替换为 **35 个真实页面 + 4 个共享 composable + 2 个展示组件**。

拆分同时修掉了三个具体缺陷：

1. **过度取数**。旧隐私中心每次切换分区都并发请求 6 个端点，包括马上要隐藏的那几个；现在每页只取自己渲染的数据。
2. **冷启动感**。婚恋档案的 7 个步骤原本共享组件内 state，改成路由后如果各自取数会变成 7 次冷启动；因此 `useDatingProfile` 用模块级单例保存 schema、草稿值与完整度，`ensureLoaded()` 全流程只取一次。
3. **原始 JSON 暴露给用户**。旧安全中心把账号限制文档直接 `JSON.stringify` 打在页面上；现在标量字段走描述列表，其余结构收进 `<details>`。

### 2.4 与 Requirement V1.6 差距的对应关系

本次前端重构直接消化的差距项：

- **P2 会员中心**「Profile 中统一呈现任务、通知、报名、互选、测评报告」→ 概览页 + 任务页已落地。
- **P0 活动互选**「按性别展示、最多选 3 位、暂不选择须理由」→ 前端已实现候选性别分组、`0/3` 名额计数与上限阻断、`pass` 时的原因枚举表单；`pass_reason` 需后端补字段后才能持久化（见 §六）。
- **P0 推荐**「三次免费 / 每次最多 3 位 / 空结果不扣次数 / 等待池」→ 前端已实现额度展示位、固定免责声明文案与等待池空态；扣减语义属后端（见 §六）。
- **P0 推荐**「非单身完全隐藏入口和额度」→ 前端已完成三层校验中的两层：IA 层（导航按 `relationship_status` 过滤）与路由层（守卫拦截并跳转说明页）。

---

## 三、布局规范

### 3.1 应用外壳（会员空间）

```
┌───────────────────────────────────────────────┐
│ 顶栏  品牌 │ 全局搜索 │ 通知 │ 语言 │ 账户菜单 │  56–64px
├──────────┬────────────────────────────────────┤
│ 侧栏     │  页面区                             │
│ 240px    │  ┌ 面包屑 ─────────────────────┐   │
│          │  │ H1 + 说明 + 页面级操作      │   │
│ 分区导航 │  ├ Section 二级导航（如有）───┤   │
│ +二级项  │  │ 内容（栅格 / 卡片 / 表单）  │   │
│          │  └────────────────────────────┘   │
└──────────┴────────────────────────────────────┘
```

- **≥ 64rem**：侧栏常驻，可折叠为 72px 图标栏（偏好持久化于 localStorage）。
- **< 64rem**：侧栏转为抽屉，顶栏出现汉堡；底部出现 5 项 Tab Bar（概览 / 缘分 / 成长 / 交易 / 我的），符合移动端拇指区。
- 内容宽度三档 token：`reading` 阅读流、`standard` 常规、`wide` 表格与仪表盘。

### 3.2 页面骨架契约

每个页面必须提供：标题（唯一 H1，路由切换后接收焦点）、一句话说明、可选操作区、可选 section 导航、内容区，并且四态齐备：**载入 / 空 / 错误 / 正常**。由 `UserPageLayout` 与 `AdminPage` 强制。

### 3.3 管理端外壳

侧栏由 30 条平铺改为 **6 组可折叠导航**：

| 组 | 模块 |
|---|---|
| 工作台 | 工作台 · 统一管理平台 |
| 内容与站点 | 页面 · 文章 · 见证 · 媒体库 · 导航 · 网站设置 |
| 商业 | 服务目录 · 订单 · 支付 · 订阅 · 退款 · 对账 · 权益 · 会员 |
| 服务运营 | 活动 · 课程 · 辅导 · 知识库 · AI 辅导 · 通知 |
| 婚恋 | 婚恋档案 · 推荐 · 互动 · 关系 |
| 信任与合规 | 信任与安全 · 隐私 · 用户 · 管理员与权限 · 审计 |
| 平台治理 | 系统运维 · 质量 · 设计系统 · 体验 · 流程 · 数据治理 · Skill |

每个模块的 section 从各页面自绘 tab 上移为**统一的二级导航**，由 `admin-nav.ts` 单一事实源驱动，并与既有权限码一一对应（无权限的 section 不渲染，而非渲染后报错）。

---

## 四、设计系统改造

### 4.1 新增 token

| 组 | token | 用途 |
|---|---|---|
| layout | `shell-sidebar-width` / `shell-sidebar-collapsed` / `shell-header-height` / `shell-gutter` | 应用外壳几何 |
| elevation | `elevation-raised` / `elevation-overlay` / `elevation-sticky` | 卡片、抽屉、吸顶条 |
| zIndex | `z-sticky` / `z-drawer` / `z-modal` / `z-toast` | 层级仲裁，消除魔法数字 |
| status surface | `surface-success` / `surface-warning` / `surface-danger` / `surface-info` / `surface-accent` | 状态底色（此前全靠硬编码） |
| interaction | `interactive-hover` / `interactive-active` / `interactive-selected` | 悬停、按下、选中态 |

三套主题（light / dark / high-contrast）全部补齐同名 token，页面样式因此可以随主题切换。

### 4.2 新增组件

`ui-core`：`VCard` `VSection` `VTabs` `VBreadcrumbs` `VMetric` `VAvatar` `VProgress` `VDescriptionList` `VToolbar` `VChip`
`ui-user`：`AppShell` `AppSidebar` `AppTopbar` `AppMobileTabBar` `SectionNav`（`UserPageLayout` 升级）
`ui-admin`：`AdminPage` `AdminSectionNav` `AdminNavTree`

### 4.3 样式分层

`apps/user-web/src/assets/main.css`（2126 行、硬编码）拆为：

```
styles/base.css        重置、排版、焦点样式、滚动行为
styles/layout.css      外壳、栅格、内容宽度
styles/components.css  按钮、卡片、表单、徽章等页面级复用类
styles/pages.css       仅限单页特例
```

规则：**页面样式中不允许出现十六进制色值**，一律走 `--vav-color-*`。已通过 `scripts/check-design-tokens.mjs` 静态校验。

---

## 五、验证口径

本次可在开发机执行并已通过：

| 检查 | 结果 |
|---|---|
| `vue-tsc -b`（user-web） | 通过 |
| `vue-tsc -b`（admin-web） | 通过 |
| `eslint src`（user-web / admin-web） | 通过，0 problems |
| `node scripts/check-design-tokens.mjs apps/user-web/src apps/admin-web/src packages` | 通过（此前 103 处硬编码色值，现为 0） |
| `node scripts/check-i18n.mjs`（user-web） | 3 语言 733 key 对齐 |
| `node scripts/check-i18n.mjs`（admin-web） | 3 语言 224 key 对齐 |
| `node --test packages/design-tokens/tests` | 2 passed |
| 路由命中验证脚本 | 15/15 路径命中正确布局 |

以上检查在 `vavactivity` 与 `vavactivityWeb` 两个仓库分别跑过。

**未能执行**：`vitest` 与 `playwright` —— 开发机 `node_modules` 中的 rollup/esbuild 为 darwin 原生二进制，在当前 Linux 沙箱内无法加载；`pytest` 与 Alembic 迁移 —— 本机未启动 PostgreSQL/Redis。这两类需在你本机 `pnpm -r test` 与 `make dev` 环境下复跑。

---

## 六、本次未落地、需后端配合的清单

以下项前端已预留 UI 与状态位，但**必须**先有后端字段与迁移，故本次未提交后端改动（当前环境无 DB，无法跑迁移与 pytest，不宜盲改）：

1. `activity_post_event_choices` 增加 `pass_reason` 枚举列（`not_my_type` / `no_chemistry` / `distance` / `faith_mismatch` / `stage_mismatch` / `other`）与 `pass_reason_note`，并在 `PUT /account/activities/{id}/choices` 校验「choice=pass 时必填」。
2. 活动后调研模型：`activity_surveys` / `activity_survey_questions` / `activity_survey_responses`，含截止时间、截止前可修改、到期提醒事件与「进入会员空间待办」的 experience task 投影。
3. 结果信：`activity_result_letters` 模板 + 审核状态机 + 发布事件。
4. 推荐免费额度：`matchmaking.free_attempt = 3` 的事务性扣减（仅在生成出 ≥1 位新合格人选时扣减），空结果不扣；`recommendation_wait_pool` 与历史去重。
5. `relationship_status != single` 时，`GET /recommendations*` 应直接返回 403 + 说明码（前端已按此形态处理）。

每一项的字段、状态机与验收点见 `docs/product/feature-redesign-2026-08.md`。
