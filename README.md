---
title: VAV Activity
emoji: 💞
colorFrom: pink
colorTo: purple
sdk: docker
app_port: 7860
hardware: cpu-basic
fullWidth: true
---

# VAV 婚恋智能服务平台

VAV 是一个前后端分离的 Python + Vue 平台。本仓库交付 Batch 1–20 的用户与运营业务闭环，并包含后续质量治理模块：FastAPI 模块化单体、用户端、运营管理端、Celery、PostgreSQL/pgvector、Redis、MinIO、Mailpit、共享 OpenAPI SDK 和完整质量门禁。

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
- `make dating-profile-verify`：执行 Batch 13 婚恋档案的迁移、种子、四类测试与前后台 E2E。
- `make recommendation-verify`：执行 Batch 14 推荐引擎的迁移、种子、五类测试、离线评测与前后台 E2E。

## 产品边界

阶段范围和未决政策以 `project-manifest.yaml` 为准。所有未决事项采用关闭或显式缺失配置，不能被实现为生产默认值；外部支付、AI、自动审核和生产数据接入必须在部署环境显式配置并通过相应门禁。

婚恋档案（Batch 13）为成年用户限定，默认严格隐私：联系方式在任何查看场景都不会自动公开，
资料完整度只衡量填写完成度，照片需人工审核，择偶条件仅本人与推荐引擎可见。

推荐引擎（Batch 14）只读取批准后的推荐投影，双方硬条件必须同时通过，缺失信息降低置信度而不是判定不合格。
用户端不显示任何匹配百分比或对方对你的评分；喜欢、互选与认识邀请属于 Batch 15。

更多资料见 `docs/product`、`docs/architecture`、`docs/security`、`docs/runbooks` 和 `docs/acceptance`。

Hugging Face Docker Space 会在 `7860` 端口同时提供用户端 `/` 和运营端 `/admin/`。需要数据接口的页面必须在 Space Settings 中把 `VITE_API_BASE_URL` 变量设置为可公开访问的 VAV API 根地址；未配置时 `/api/*` 会明确返回 `503`，不会把 SPA HTML 误当成 JSON。

提交到 `main` 的数据库迁移会在后端质量门禁通过后自动应用到 Neon。连接密钥、执行顺序和
失败处理见 `docs/runbooks/neon-migrations.md`。

用户端测试登录账号为 `test`，密码为 `test`。该账号无管理权限，仅供测试环境使用。

# vavactivity
