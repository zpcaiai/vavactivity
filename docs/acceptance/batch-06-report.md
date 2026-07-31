# Batch 6 验收报告

- 验收对象：活动发布、报名、候补、签到、分组与活动后互选
- 验收日期：2026-07-31
- 状态：本地容器化验收通过

## 验收结果

- 活动价格和有限名额只读取 Catalog/Inventory 权威数据，活动域不复制价格或库存。
- 发布前校验覆盖多语言内容、活动时段、私密地点/会议配置、票种价格、库存与售票窗口。
- 报名支持免费、付费、人工审核和规则辅助路径；零价订单仍通过 Commerce 权益投影确认。
- 候补顺序确定且可审计，并使用 PostgreSQL 事务锁保证一个释放名额只产生一份有效邀请。
- 取消活动会停止售票、撤销签到凭证、取消报名与候补，并生成最小化事件和 Commerce 待处理动作。
- 签到使用短时凭证、窗口校验与幂等事件；撤销签到只追加审计事件。
- 分组支持固定随机种子、锁定、审计解锁和成员移动历史。
- 活动后互选要求到场和明确展示同意；单向选择不对普通运营人员开放，双向匹配也不披露联系方式。
- 用户端覆盖公开发现、权威票价/余量、报名、候补、私密通行、分组和互选入口；管理端覆盖发布、审核、候补、签到、分组和聚合分析。

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 活动单元/集成测试 | `make activity-test` | PASS，8 tests |
| PostgreSQL 并发测试 | `make activity-concurrency-test` | PASS，4 tests |
| 活动安全测试 | `make activity-security-test` | PASS，4 tests |
| 用户活动浏览器验收 | `make activity-user-e2e` | PASS，2 tests |
| 后台活动浏览器验收 | `make activity-admin-e2e` | PASS，1 test |
| Batch 1–5 回归与平台验收 | `make activity-verify` | PASS |
| 平台后端回归 | `make verify`（由上一门禁串联） | PASS，96 tests |
| 前端组件测试 | `make verify`（由上一门禁串联） | PASS，12 tests |
| 两端生产构建与 OpenAPI SDK | `make verify`（由上一门禁串联） | PASS |
| 补丁格式检查 | `git diff --check` | PASS |

## 边界声明

本报告证明当前工作区的本地 PostgreSQL、Redis、MinIO、Mailpit、Fake Commerce
和 Chromium 验收环境通过。真实 Stripe/PayPal、生产邮件、外部身份提供商、生产部署、
退款运营审批、合规审批、用户试点与联系方式交换政策均未在本次验收中执行，不能据此
声明生产认证或外部服务验收完成。
