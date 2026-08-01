# Batch 10 验收报告

- 验收对象：Hanna AI 关系助理、LangGraph 编排、模型/Prompt/安全/工具注册表、
  加密会话与摘要、授权 RAG、风险分流、人工转介、受控写操作、离线评测与管理端治理
- 验收日期：2026-08-01
- 数据库版本：`20260801_0034`
- 状态：本地主机业务验收通过；外部模型、冷镜像构建与生产门禁未完成

## 验收结果

- 使用 `langgraph==1.2.9` 的 `StateGraph` 实现显式节点和条件边，分类、完整性检查、
  风险筛查、检索、工具、回答、安全复核与落库均留下节点 Trace 和 Checkpoint。
- 会话、消息、摘要和 Checkpoint 的用户内容使用应用层加密；对话只允许本人访问，
  管理端默认展示脱敏摘要，敏感查看需要独立权限、理由和审计事件。
- 首次对话分别取得 AI 披露确认和可选长期记忆同意；用户可撤销记忆、删除/墓碑化对话，
  摘要只保存事实性内容，并将推断字段保持为空。
- 输入先执行结构化分类与风险策略。中度、高度和即时风险均停止普通建议并进入受限转介；
  即时风险暂停后续普通对话，不把 AI 描述成紧急、医疗、法律或持牌辅导服务。
- 检索复用 Batch 9 的 Space ACL、角色 ACL、授权、地区、语言、有效期和版本过滤；引用绑定
  文档版本、Chunk、来源定位和内容 Hash，来源撤销后继续 fail closed。
- 注册 14 个受控工具，其中 11 个只读、3 个写入。写操作只能由用户界面申请一个与用户、
  会话、工具和参数 Hash 绑定的十分钟单次 Token；服务端拒绝模型伪造、篡改和重放，并以
  幂等键避免重复副作用。
- Prompt、模型路由、安全策略和工具均版本化并可审计；生产环境拒绝确定性测试模型、
  明文/缺失加密配置和允许外部训练的数据策略。
- 管理端提供脱敏会话、理由门禁敏感查看、安全转介、Prompt、模型、受控工具、评测与审计；
  不允许通过界面或 API 创建任意代码工具。权限种子为 221 项权限、24 个角色。
- 本地种子包括 4 个模型 Profile、4 条路由、1 个 Prompt Release、3 个本地化安全策略、
  14 个工具和 36 个评测用例。最新评测运行 `16a4665d-f561-4435-a6d4-1cdf143fd1af`
  为 36/36，通过率 100%，隐私泄漏、未授权工具调用和跨用户访问均为 0。

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 数据库迁移 | `alembic upgrade head`、查询 `alembic_version` | PASS，`20260801_0031` 至 `0034` |
| Python 静态检查 | `ruff check src/vav/modules/ai_assistant`、`mypy ...` | PASS，11 个核心源文件 |
| 完整后端回归 | `AI_ENABLED=true uv run --package vav-platform-api pytest services/api/tests -q` | PASS，156 tests |
| AI 专项测试 | 完整回归内的 `tests/ai_assistant` | PASS，17 tests，覆盖单元、集成、安全、越权、并发与确认重放 |
| 离线安全评测 | `python -m vav.cli.run_ai_evaluation` | PASS，36/36，三项严重失败计数均为 0 |
| User Web 测试 | `vitest run` | PASS，7 tests |
| Admin Web 测试 | `vitest run` | PASS，6 tests |
| 双端类型与生产构建 | `vue-tsc -b`、`vite build` | PASS |
| 双端 ESLint | `eslint . --quiet` | PASS，0 errors |
| OpenAPI SDK | `./scripts/generate-openapi-client.sh` | PASS，契约和 TypeScript 类型包含最终确认端点 |
| 用户/管理端浏览器验收 | `playwright test e2e/ai.user.spec.ts e2e/ai.admin.spec.ts` | PASS，2/2 |
| 冷 API 镜像重建 | `docker compose build api` | BLOCKED，依赖下载先超时；延长超时后长时间无进展并人工终止 |

## 本地审计快照

数据库当前包含 37 个测试会话、34 个已落库 Turn、308 个 Checkpoint、232 个节点 Trace、
5 个事实摘要、116 个模型调用记录、22 个工具执行、8 个行动项和 14 个安全转介。
这些数字只用于证明审计链在本地验收路径中实际写入，不是生产容量或质量指标。

## 真实边界

本验收使用本地 PostgreSQL/pgvector、MinIO、Batch 9 确定性检索、确定性模型 Provider 和
Chrome。没有调用或认证真实外部 LLM，也没有证明供应商数据保留、训练退出、区域路由、
限流、成本、可用性或事故响应；这些项目为 `NOT_RUN`。生产会拒绝确定性 Provider，不能
把本地 36/36 评测解释为外部模型质量证明。

各地区紧急资源文案、真实人工接单与升级 SLA、法务/隐私审批、生产保留期、真实用户试点、
红队/渗透、负载与 SLO、灾备、云部署和上线认证仍为 `NOT_RUN` / `NOT_CERTIFIED`。
冷镜像网络阻塞保留为 `BLOCKED`，没有被记为容器构建成功；本轮业务验收由当前源码的主机
API、两端开发服务器、独立生产构建和完整本地测试共同完成。
