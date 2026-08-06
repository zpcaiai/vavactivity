# Batch 21 集成清单

> 状态：以下片段在当前仓库中**已经存在**（由本批次或主控代理先前合并）。
> 保留本清单用于回归校验：合并其他批次时请确认这些片段仍然在位。

## services/api/src/vav/api/router.py

导入（import 区，按字母序）：
```python
from vav.modules.quality.admin_router import router as quality_admin_router
```

注册（文件末尾）：
```python
api_router.include_router(quality_admin_router, tags=["quality-admin"])
```

校验：`grep -n "quality_admin_router" services/api/src/vav/api/router.py` 应有 2 处命中。

## services/api/src/vav/core/config.py

在 `Settings` 类里（放在 skills 设置之后）：
```python
    quality_enabled: bool = Field(default=True, validation_alias="QUALITY_ENABLED")
    quality_manifest_version: str = Field(
        default="1.0.0", validation_alias="QUALITY_MANIFEST_VERSION"
    )
    quality_requirement_import_enabled: bool = Field(
        default=True, validation_alias="QUALITY_REQUIREMENT_IMPORT_ENABLED"
    )
    quality_source_scan_enabled: bool = Field(
        default=True, validation_alias="QUALITY_SOURCE_SCAN_ENABLED"
    )
    quality_blocker_trace_coverage_required: float = Field(
        default=1.0, ge=0, le=1, validation_alias="QUALITY_BLOCKER_TRACE_COVERAGE_REQUIRED"
    )
    quality_critical_verification_required: float = Field(
        default=1.0, ge=0, le=1, validation_alias="QUALITY_CRITICAL_VERIFICATION_REQUIRED"
    )
    quality_critical_flow_closure_required: float = Field(
        default=1.0, ge=0, le=1, validation_alias="QUALITY_CRITICAL_FLOW_CLOSURE_REQUIRED"
    )
    quality_allow_blocker_waivers: bool = Field(
        default=False, validation_alias="QUALITY_ALLOW_BLOCKER_WAIVERS"
    )
    quality_waiver_max_days: int = Field(
        default=30, ge=1, le=90, validation_alias="QUALITY_WAIVER_MAX_DAYS"
    )
    quality_evidence_expiry_enabled: bool = Field(
        default=True, validation_alias="QUALITY_EVIDENCE_EXPIRY_ENABLED"
    )
    quality_release_certification_required: bool = Field(
        default=True, validation_alias="QUALITY_RELEASE_CERTIFICATION_REQUIRED"
    )
    quality_fail_release_on_orphan_critical_page: bool = Field(
        default=True, validation_alias="QUALITY_FAIL_RELEASE_ON_ORPHAN_CRITICAL_PAGE"
    )
    quality_fail_release_on_critical_dead_letter: bool = Field(
        default=True, validation_alias="QUALITY_FAIL_RELEASE_ON_CRITICAL_DEAD_LETTER"
    )
    quality_fail_release_on_open_critical_risk: bool = Field(
        default=True, validation_alias="QUALITY_FAIL_RELEASE_ON_OPEN_CRITICAL_RISK"
    )
```

fail-closed 校验器（`model_validator` 区）：
```python
        if self.quality_allow_blocker_waivers:
            raise ValueError("blocker quality gates cannot be waived")
        if not all(
            (
                self.quality_evidence_expiry_enabled,
                self.quality_release_certification_required,
                self.quality_fail_release_on_orphan_critical_page,
                self.quality_fail_release_on_critical_dead_letter,
                self.quality_fail_release_on_open_critical_risk,
            )
        ):
            raise ValueError("quality release controls must fail closed")
```

`public_summary()` 的 features 字典里：
```python
                "quality": self.quality_enabled,
```

## .env.example

```dotenv
# Batch 21 quality governance (fail closed)
QUALITY_ENABLED=true
QUALITY_MANIFEST_VERSION=1.0.0
QUALITY_REQUIREMENT_IMPORT_ENABLED=true
QUALITY_SOURCE_SCAN_ENABLED=true
QUALITY_BLOCKER_TRACE_COVERAGE_REQUIRED=1.0
QUALITY_CRITICAL_VERIFICATION_REQUIRED=1.0
QUALITY_CRITICAL_FLOW_CLOSURE_REQUIRED=1.0
QUALITY_ALLOW_BLOCKER_WAIVERS=false
QUALITY_WAIVER_MAX_DAYS=30
QUALITY_EVIDENCE_EXPIRY_ENABLED=true
QUALITY_RELEASE_CERTIFICATION_REQUIRED=true
QUALITY_FAIL_RELEASE_ON_ORPHAN_CRITICAL_PAGE=true
QUALITY_FAIL_RELEASE_ON_CRITICAL_DEAD_LETTER=true
QUALITY_FAIL_RELEASE_ON_OPEN_CRITICAL_RISK=true
```

## project-manifest.yaml

`module_registry:` 下：
```yaml
  quality: {owner: quality_engineering, status: foundation_in_progress, phase: phase_4}
```

`production_assembly.migration_head` 必须 ≥ `"20260806_0087"`。

## services/api/src/vav/modules/identity/permissions.py

`QUALITY_PERMISSIONS` 集合（59 项，前缀 `quality.`）必须并入聚合权限集合，且被 `python -m vav.cli.seed_permissions` 种子化。角色 `quality_analyst`、`quality_engineer`、`quality_release_manager`、`quality_governance_reviewer` 按 batch-21 规格第 38 节授权；需求实现者不得批准自己的 Waiver。

## Makefile 聚合目标建议

- `verify-all` 追加：`quality-verify`
- `acceptance` 之后追加：`quality-gate-evaluate`（离线、无需数据库，可在 CI 早期阶段执行）

`make/batch-21.mk` 已由 `-include make/batch-*.mk` 自动加载，主 `Makefile` 无需其他改动。
