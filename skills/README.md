# VAV Skills 分批交付目录

本目录把《ChatGPT-Codex 实现项目方案.md》拆成 32 个可独立审查的交付批次：

- `batch-01`–`batch-20`：产品能力，从项目基座到 Skill SDK/Runtime；
- `batch-21`–`batch-32`：质量、体验、安全、性能、韧性和最终认证。

每个批次包含一个主控 `SKILL.md` 和按顺序编号的子技能。主控文件规定前置依赖、实现边界、不变量和验收门禁；子技能描述单个可执行实现单元。批次依赖和子技能数量以 [`catalog.yaml`](./catalog.yaml) 为准。

## 交付与验证

先验证技能目录，再执行对应批次的运行门禁：

```bash
make skill-catalog-check
make verify                 # Batch 01
make auth-verify            # Batch 02
make cms-verify             # Batch 03
make catalog-verify         # Batch 04
make commerce-verify       # Batch 05
make activity-verify       # Batch 06
make course-verify          # Batch 07
make counseling-verify     # Batch 08
make knowledge-verify      # Batch 09
make ai-verify              # Batch 10
```

后续批次继续使用 `catalog.yaml` 中的 `verification` 命令。目录校验只证明 Skill 产物完整、顺序正确且 frontmatter 可读；它不替代运行时、真实 Provider、浏览器、生产或人工认证证据。未实际执行的门禁必须保留 `NOT_RUN`、`NOT_CERTIFIED` 或对应的配置阻塞状态。
