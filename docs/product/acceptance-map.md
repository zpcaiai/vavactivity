# 需求到验收追踪矩阵

| 需求 | 模块 | API/页面 | 自动验收 |
| --- | --- | --- | --- |
| 服务存活 | core | `GET /api/v1/health/live` | `test_health.py::test_liveness` |
| 依赖就绪 | core | `GET /api/v1/health/ready` | Compose 健康检查、`scripts/verify.sh` |
| 版本可追踪 | core | `GET /api/v1/system/version` | `test_system.py` |
| 安全配置可见性 | core | `GET /api/v1/system/config` | `test_system.py` 验证不泄露密钥 |
| 用户端可访问 | public_site | `/{locale}/` 及公共服务路由 | Vitest、Vite build、curl |
| 管理端可访问 | admin | `/admin/*` | Vitest、Vite build、curl |
| 管理端权限接口 | admin | 路由元数据、`v-permission` | 指令单元测试 |
| 数据库可重建 | core | Alembic `upgrade head` | backend CI、`make migrate` |
| API 契约共享 | core | `packages/contracts/openapi.json` | OpenAPI 差异门禁 |
| 本地依赖可复现 | platform | Docker Compose 八个服务 | `make verify` |
| 待决策项安全关闭 | product | `project-manifest.yaml` | `scripts/validate_manifest.py` |

