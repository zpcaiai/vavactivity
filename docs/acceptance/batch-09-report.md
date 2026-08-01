# Batch 9 验收报告

- 验收对象：可信知识库、授权治理、私有导入、结构化解析、版本、Chunk、Embedding、
  pgvector/FTS 混合检索、引用、索引切换、评测与管理端知识库中心
- 验收日期：2026-08-01
- 数据库版本：`20260731_0030`
- 状态：本地容器化业务验收通过；外部冷构建与生产门禁未完成

## 验收结果

- 建立隔离的 Knowledge Space、Source、Document 与不可变 Document Version；数据库
  触发器阻止已进入复核/批准/发布流程的原始载荷被原位修改。
- 来源级与文档级授权分别保存 RAG、引用、地区、有效期、证据、审批和撤销状态；检索
  时在 SQL 层重新执行空间 ACL、角色 ACL、授权、地区、语言、有效期和版本过滤。
- 私有文件通过 MinIO Presigned URL 上传，并校验大小、真实 MIME、SHA-256 与已声明的
  病毒扫描边界；导入后保持“等待授权与人工复核”，不会直接进入生产索引。
- 文本、Markdown、HTML、JSON、DOCX 和带文本层 PDF 转换为带页码、标题路径与来源定位
  的 Parsed Block；扫描件/OCR 明确转人工复核，不把低质量结果伪装成可发布正文。
- CMS、Course、Activity、Counseling 连接器只读取已发布公共投影；学习者答案、报名资料、
  私密辅导记录和实时可用性均被排除。本地种子导入 50 个待审版本。
- 构建父子 Chunk、前后邻接、内容 Hash 和 profile-bound 64 维测试向量；使用 pgvector、
  PostgreSQL FTS 和确定性 RRF，并在返回前再次检查授权与 ACL。
- 引用绑定 Document、Document Version、Chunk、来源定位与片段 SHA-256，可独立验证，
  撤销来源后立即 fail closed，同时保留历史引用和审计身份。
- 候选索引采用 blue/green 生命周期，只有评测通过且授权/ACL 泄漏为零时才可原子激活；
  失败候选不影响旧索引，并支持有理由、有审计记录的回滚。
- 管理端提供空间、来源/同步、私有导入、文档/解析溯源、授权、指定空间检索调试、索引、
  评测与审计界面；权限种子为 191 项权限、21 个角色。

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| Python 静态检查 | `ruff check ...`、`mypy ...` | PASS，14 个核心源文件 |
| 知识单元/集成测试 | `make knowledge-test` | PASS，14 tests |
| 混合检索测试 | `make knowledge-retrieval-test` | PASS，3 tests |
| 授权与安全测试 | `make knowledge-security-test` | PASS，3 tests |
| 连接器导入 | `make knowledge-ingest-fixtures` | PASS，50 个待审版本，私密记录排除 |
| 候选索引构建 | `make knowledge-build-index` | PASS，v8，9 chunks，9 embeddings |
| 检索评测 | `make knowledge-eval` | PASS，32/32，授权违规 0，ACL 泄漏 0 |
| 管理端组件测试 | `pnpm --filter @vav/admin-web test -- --run` | PASS，6 tests |
| 管理端生产构建 | `pnpm --filter @vav/admin-web build` | PASS |
| OpenAPI SDK | `./scripts/generate-openapi-client.sh` | PASS，契约与 TypeScript 类型已更新 |
| 管理端浏览器验收 | `make knowledge-admin-e2e` | PASS，1 test |
| Batch 1-8 递归业务回归 | `make knowledge-verify` | 业务、并发、安全和 E2E 门禁全部 PASS |
| 全仓冷镜像重建 | 递归末端 `make verify` | BLOCKED，Docker Hub 连接重置且 GHCR 并发连接被拒绝 |

## 真实边界

本验收使用本地 PostgreSQL/pgvector、MinIO、确定性 fake embedding、Fake Commerce、
Fake Meeting 与 Chromium。完整 PDF 排版恢复、扫描件 OCR、音视频转录、外部内容连接器、
真实向量供应商、供应商批处理/限流/成本账单、真实法务授权材料和生产数据集仍为
`NOT_RUN`；生产配置会拒绝 fake embedding。Docker Hub/GHCR 网络失败没有被记为构建
成功；管理端浏览器验收使用依赖锁未变化的本地镜像增量覆盖，主机生产构建已独立通过。
真实云对象存储、生产部署、长周期延迟/成本观察、外部安全测试、用户试点和上线认证均为
`NOT_RUN` / `NOT_CERTIFIED`。
