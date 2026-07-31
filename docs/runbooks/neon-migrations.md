# Neon 数据库迁移运行手册

## 自动执行规则

每次代码推送到 `main` 后，`Backend CI` 会先在隔离的 PostgreSQL 服务中执行后端测试、
完整 Alembic 迁移和模型漂移检查。只有这些检查全部通过，`Apply migrations to Neon`
任务才会对 Neon 执行一次幂等的 `alembic upgrade head`，随后再次检查线上 schema。

迁移任务按 `neon-production-migrations` 并发组串行运行。迁移失败会让 Backend CI
失败，不能被当作数据库发布成功。Pull Request 和本地 `pre-commit` 不访问 Neon，避免
不受信任的代码或测试数据写入线上数据库。

## GitHub 密钥

仓库必须配置 Actions 密钥 `NEON_DATABASE_URL`。该值使用 Neon 的直连地址，而不是主机名
包含 `-pooler` 的连接池地址；Alembic 等 schema 迁移工具应使用直连。连接串还必须：

- 使用 `postgresql+asyncpg://` driver；
- 指向 `*.neon.tech`；
- 包含 `sslmode=require`；
- 移除 asyncpg 不支持的 `channel_binding` 参数。

连接串只能保存在 GitHub Actions secret 或受控的运行环境中，不得写入仓库、日志、Issue
或验收报告。应用运行时可以另外使用池化连接；迁移密钥只负责 schema 变更。

## 验证与故障处理

在 GitHub 的 `Backend CI` 中确认以下步骤成功：

1. `Validate Neon migration connection`
2. `Verify a single migration head`
3. `Apply pending migrations to Neon`
4. `Verify the live Neon schema`

若迁移失败，先保留失败日志并停止后续数据库发布。修复应新增向前迁移；不要在生产 Neon
上手工改表或直接执行 `alembic downgrade`。需要恢复数据时，使用 Neon 分支或时间点恢复，
并在恢复后重新运行完整迁移门禁。
