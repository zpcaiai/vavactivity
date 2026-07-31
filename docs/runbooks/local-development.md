# 本地开发运行手册

## 首次启动

安装 Docker Desktop、Python 3.12、uv、Node.js 22–26 和 Corepack，然后执行：

```bash
cp .env.example .env
make bootstrap
make dev
```

首次构建会下载固定版本镜像和依赖。`api` 会在监听请求前自动执行 `alembic upgrade head`，MinIO 初始化任务会创建私有桶。

## 健康检查

```bash
curl --fail http://localhost:8000/api/v1/health/live
curl --fail http://localhost:8000/api/v1/health/ready
docker compose ps
```

`live` 只说明 API 进程可响应；`ready` 同时检查 PostgreSQL 与 Redis。只有后者成功才代表实例可以接收业务流量。

## 常见故障

- 端口占用：停止占用 5173、5174、8000、5432、6379、9000、9001 或 8025 的本机服务。
- 依赖下载中断：重新运行 `make bootstrap`，uv 和 pnpm 会复用完整缓存。
- 数据库迁移失败：运行 `docker compose logs api postgres`，不要手工改表。
- Web 页面不可达：运行 `docker compose logs user-web admin-web` 并确认 API 已健康。

## 从零验证

`make reset` 会删除本项目的 PostgreSQL、Redis 和 MinIO Docker Volume，属于本地破坏性操作。确认不需要本地数据后再运行：

```bash
make reset
make verify
```

