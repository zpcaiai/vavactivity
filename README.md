# VAV 婚恋智能服务平台

VAV 是一个前后端分离的 Python + Vue 平台。本仓库当前交付 Batch 1 工程基座：FastAPI 模块化单体、用户端、运营管理端、Celery、PostgreSQL/pgvector、Redis、MinIO、Mailpit、共享 OpenAPI SDK 和完整质量门禁。

## 本地地址

| 服务 | 地址 |
| --- | --- |
| 用户端 | <http://localhost:5173> |
| 运营管理端 | <http://localhost:5174/admin/login> |
| API | <http://localhost:8000> |
| OpenAPI | <http://localhost:8000/docs> |
| Mailpit | <http://localhost:8025> |
| MinIO 控制台 | <http://localhost:9001> |

## 开始使用

前置条件：Docker Desktop、Python 3.12、uv、Node.js 22+、Corepack/pnpm。

```bash
cp .env.example .env
make bootstrap
make dev
```

另一个终端可执行：

```bash
make test
make verify
```

`make reset` 会删除本项目 Docker 数据卷，仅用于需要验证从零迁移的本地环境。生产环境不得使用 `.env.example` 的开发凭据。

## 常用命令

- `make migrate`：运行 Alembic 迁移。
- `make openapi`：从 FastAPI 生成 OpenAPI JSON 和 TypeScript 类型。
- `make lint`：检查 Python 与 TypeScript 代码。
- `make test`：运行后端和前端测试。
- `make verify`：从 Compose 配置到服务探针执行完整 Batch 1 验收。

## 产品边界

阶段范围和未决政策以 `project-manifest.yaml` 为准。所有未决事项采用关闭或显式缺失配置，不能被实现为生产默认值。Batch 1 不包含真实注册、支付、AI 辅导或匹配业务。

更多资料见 `docs/product`、`docs/architecture`、`docs/security`、`docs/runbooks` 和 `docs/acceptance`。

提交到 `main` 的数据库迁移会在后端质量门禁通过后自动应用到 Neon。连接密钥、执行顺序和
失败处理见 `docs/runbooks/neon-migrations.md`。

# vavactivity
