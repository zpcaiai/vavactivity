from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_every_backend_module_declares_a_production_contract() -> None:
    modules = sorted((ROOT / "services/api/src/vav/modules").glob("*/module.yaml"))
    assert len(modules) == 19
    codes: set[str] = set()
    revisions: list[int] = []
    for path in modules:
        contract = yaml.safe_load(path.read_text(encoding="utf-8"))
        codes.add(contract["module"]["code"])
        assert contract["module"]["owner"]
        assert contract["module"]["version"]
        assert contract["health"]
        revisions.extend(contract["database"]["revisions"])
    assert len(codes) == 19
    assert sorted(revisions) == list(range(1, 84))


def test_openapi_operation_ids_and_routes_are_unique() -> None:
    contract = json.loads(
        (ROOT / "packages/contracts/openapi.json").read_text(encoding="utf-8")
    )
    operation_ids: list[str] = []
    for path, methods in contract["paths"].items():
        assert path.startswith("/")
        for method, operation in methods.items():
            if method.lower() not in {"get", "put", "post", "delete", "patch"}:
                continue
            assert operation.get("operationId"), f"missing operationId: {method} {path}"
            operation_ids.append(operation["operationId"])
    assert len(operation_ids) == len(set(operation_ids))
    assert len(operation_ids) >= 750


def test_seed_event_and_permission_manifests_are_closed_world() -> None:
    seeds = yaml.safe_load(
        (ROOT / "config/seeds/manifest.yaml").read_text(encoding="utf-8")
    )
    events = yaml.safe_load(
        (ROOT / "config/events/manifest.yaml").read_text(encoding="utf-8")
    )
    features = yaml.safe_load(
        (ROOT / "config/features/manifest.yaml").read_text(encoding="utf-8")
    )
    seed_modules = [module for group in seeds["groups"].values() for module in group]
    assert all(
        (
            ROOT / "services/api/src" / Path(*module.split(".")).with_suffix(".py")
        ).is_file()
        for module in seed_modules
    )
    assert len(set(events["events"])) == len(events["events"])
    assert all(name.endswith(".v1") for name in events["events"])
    protected = ("safety.", "privacy.", "payment.", "authorization.", "encryption.")
    assert not any(code.startswith(protected) for code in features["flags"])
