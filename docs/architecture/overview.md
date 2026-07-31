# 系统架构概览

VAV 从模块化单体开始：一个 FastAPI 进程持有事务业务规则，一个 Celery Worker 处理可重试异步工作，用户端和运营端独立构建。PostgreSQL 是事务事实来源，Redis 只承担缓存与任务传输，MinIO 保存默认私有的对象。

```text
User Web ─────┐
              ├── OpenAPI SDK ── FastAPI ── PostgreSQL + pgvector
Admin Web ────┘                    │   │
                                  │   └── Redis ── Celery Worker
                                  ├── MinIO
                                  └── Mail provider adapter
```

## 边界

- FastAPI 是权限、价格、订单、支付、关系状态和风险处置的唯一权威。
- 两个 Vue 应用不共享路由、会话入口或布局，只共享生成契约和设计令牌。
- 业务模块不得从原始 HTTP 请求直接操作其他模块的数据表；跨模块操作通过应用服务和事件完成。
- Outbox 为后续可靠事件投递保留事务边界，幂等表为 Webhook 和命令重试保留去重边界。
- AI 能力默认关闭，其不可用不能影响核心服务健康。

## 时间与标识

数据库时间统一使用 `TIMESTAMPTZ` 并按 UTC 存储，展示时区由配置决定。主键统一为 UUID。金额模块落地时必须使用最小货币单位的整数，禁止浮点数。

