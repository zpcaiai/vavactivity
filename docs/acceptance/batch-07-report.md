# Batch 7 验收报告

- 验收对象：课程目录、版本化课纲、视频访问、权益注册、学习进度、练习与证书
- 验收日期：2026-07-31
- 状态：本地容器化验收通过

## 验收结果

- 课程商品价格来自 Catalog，付费访问只由 `course_access` Entitlement 投影开通。
- Enrollment 固定到不可变 Course Version，实时新增课时不能越过固定版本访问边界。
- 公开试听只返回明确标记为 `public` 的课时，私有视频引用、答案键和学习答案均不进入公共 DTO。
- 播放会话使用短时、绑定会话的签名地址；服务端心跳保持单调并对重复序列幂等。
- 学习事件使用事务锁、幂等键和序列约束，多设备并发不会降低已记录进度。
- 练习支持草稿保存、自动/人工评分、次数与冷却期；回答和反馈保持加密。
- 完成计算读取 Enrollment 固定版本，并发评估只生成一条 Completion Record 和一张证书。
- 课程详情提供权威价格、访问期限、讲师、目录和试听；用户端新增证书中心及固定课时路由。
- 管理 API 补齐乐观锁更新、讲师关联、先修关系、Catalog 映射和显式发布动作。

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 课程单元/集成测试 | `make course-test` | PASS，8 tests |
| PostgreSQL 并发测试 | `make course-concurrency-test` | PASS，4 tests |
| 课程安全测试 | `make course-security-test` | PASS，3 tests |
| 用户课程浏览器验收 | `make course-user-e2e` | PASS，1 test |
| 后台课程浏览器验收 | `make course-admin-e2e` | PASS，1 test |
| Batch 1–6 回归与平台验收 | `make course-verify` | PASS |
| 平台后端回归 | `make verify`（由上一门禁串联） | PASS，100 tests |
| 前端组件测试 | `make verify`（由上一门禁串联） | PASS，12 tests |
| 两端生产构建与 OpenAPI SDK | `make verify`（由上一门禁串联） | PASS |

## 边界声明

本报告只证明本地 PostgreSQL、Fake Private Video Provider、Fake Commerce 和 Chromium
环境通过。真实视频供应商、真实支付、生产对象存储、会员课程政策、正式证书姓名公开政策、
生产部署与用户试点均未执行，不能据此声明生产或外部供应商认证完成。
