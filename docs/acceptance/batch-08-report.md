# Batch 8 验收报告

- 验收对象：真人辅导服务、导师、时段、预约、交付、记录、跟进与安全转介
- 验收日期：2026-07-31
- 状态：本地容器化验收通过；外部与政策门禁仍未完成

## 验收结果

- 公开服务与导师支持本地化，价格由 Catalog SKU/Price 权威返回。
- 可见时段按 IANA 时区和循环规则生成；创建占位及最终预约使用 PostgreSQL
  事务锁，已确认预约另有数据库排他约束。
- 同一时段双用户并发只允许一条有效占位；重复幂等键只生成一条记录。
- 问卷、私密记录、安全转介详情和会议引用加密保存，公共 DTO 不返回私密字段。
- 预约状态机覆盖审核、提议、付款待确认、确认、改期、取消、拒绝、完成和未到。
- 付费预约只能由服务端验证后的 `counseling_credits` Entitlement 投影确认；浏览器
  支付返回不能确认预约。完成会谈原子消费预留权益并防止重复消费。
- 会谈入口仅在时间窗口内签发短效、会话与用户双绑定令牌；录音和转写默认关闭。
- 用户端支持服务发现、边界说明、选时、占位、预约与预约中心；运营端按 RBAC
  分层管理导师、服务、预约和安全记录。

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 咨询单元/集成测试 | `make counseling-test` | PASS，4 tests |
| PostgreSQL 并发测试 | `make counseling-concurrency-test` | PASS，2 tests |
| 咨询安全测试 | `make counseling-security-test` | PASS，3 tests |
| 用户咨询浏览器验收 | `make counseling-user-e2e` | PASS，1 test |
| 后台咨询浏览器验收 | `make counseling-admin-e2e` | PASS，1 test |
| Batch 1-7 递归回归 | `make counseling-verify` | 业务门禁全部 PASS |
| 平台后端回归 | `VAV_VERIFY_REUSE_BUILT_IMAGES=true make verify` | PASS，109 tests |
| 前端组件回归 | 同上 | PASS，12 tests |
| 两端构建与 OpenAPI SDK | 同上 | PASS |

## 真实边界

本验收只覆盖本地 PostgreSQL、Fake Meeting、Fake Commerce 和 Chromium。正式取消/
退款规则、未到扣点、录音/转写同意、记录保留期限与专业服务边界仍在决策登记中并保持
fail closed。真实 Stripe/PayPal、真实会议供应商、通知供应商、生产部署、长周期观察与用户
试点均为 `NOT_RUN`，不能据此宣称生产认证完成。最终全仓重建曾因 GHCR 与 Docker Hub
匿名令牌 `EOF` 失败两次；验收复用了同一时段已成功构建的本地镜像，未把网络失败伪装
为构建成功。
