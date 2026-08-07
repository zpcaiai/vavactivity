"""VAV Skill CLI entrypoint."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import yaml
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from vav_skill_cli.api import SkillApiClient
from vav_skill_cli.generator import create_skill
from vav_skill_cli.supply_chain import (
    generate_provenance,
    generate_sbom,
    scan_secrets,
    sign_package,
    verify_package,
)
from vav_skill_contracts import compare_schemas, generate_contracts
from vav_skill_sdk.manifest import validate_manifest
from vav_skill_sdk.package import build_package


def _json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def _skill_ref(value: str) -> tuple[str, str]:
    if "@" not in value:
        raise ValueError("Skill reference must use name@version")
    return tuple(value.rsplit("@", 1))  # type: ignore[return-value]


def _schema(path: str | Path) -> dict[str, Any]:
    value = cast(dict[str, Any], json.loads(Path(path).read_text(encoding="utf-8")))
    Draft202012Validator.check_schema(value)
    return value


def _run_local(args: argparse.Namespace) -> object:
    if args.command == "create":
        target = create_skill(
            args.directory, name=args.name, skill_type=args.type, runtime=args.runtime
        )
        return {"created": str(target)}
    if args.command == "validate":
        manifest = validate_manifest(Path(args.directory) / "skill.yaml")
        findings = scan_secrets(args.directory)
        if findings:
            raise ValueError(f"secret scan rejected files: {list(findings)}")
        return {"valid": True, "name": manifest.metadata.name, "version": manifest.metadata.version}
    if args.command == "test":
        manifest = validate_manifest(Path(args.directory) / "skill.yaml")
        command = shlex.split(manifest.spec.tests.command)
        result = subprocess.run(command, cwd=args.directory, check=False, timeout=args.timeout)
        if result.returncode:
            raise RuntimeError(f"Skill tests failed with exit code {result.returncode}")
        return {"passed": True, "command": command}
    if args.command == "build":
        findings = scan_secrets(args.directory)
        if findings:
            raise ValueError(f"secret scan rejected files: {list(findings)}")
        build = build_package(args.directory, args.output)
        return {
            "archive": str(build.archive),
            "packageSha256": build.package_sha256,
            "contentSha256": build.content_sha256,
            "files": build.files,
        }
    if args.command == "sbom":
        return generate_sbom(args.directory, args.output)
    if args.command == "provenance":
        return generate_provenance(
            args.package,
            args.sbom,
            args.output,
            source_root=args.source,
            builder_id=args.builder_id,
        )
    if args.command == "sign":
        return sign_package(args.package, args.key, args.output, key_id=args.key_id)
    if args.command == "verify-signature":
        return verify_package(args.package, args.signature, args.public_key)
    if args.command == "schema":
        if args.schema_command == "check":
            checked = _schema(args.schema)
            return {"valid": True, "id": checked.get("$id")}
        if args.schema_command == "generate":
            generated = generate_contracts(args.schema, args.output, name=args.name)
            return {
                "python": str(generated.python_path),
                "typescript": str(generated.typescript_path),
                "fixture": str(generated.fixture_path),
            }
        diff = compare_schemas(_schema(args.from_schema), _schema(args.to_schema))
        return {
            "breaking": diff.breaking,
            "reviewRequired": diff.review_required,
            "requiredVersion": diff.require_version(),
            "changes": [change.__dict__ for change in diff.changes],
        }
    if args.command == "doctor":
        root = Path(args.directory).resolve()
        results = {
            "manifest": (root / "skill.yaml").is_file(),
            "schemas": all(
                (root / f"schemas/{name}.schema.json").is_file()
                for name in ("input", "output", "error")
            ),
            "secretsClean": not scan_secrets(root),
            "apiConfigured": bool(os.getenv("VAV_API_URL")),
            "accessTokenConfigured": bool(os.getenv("VAV_ACCESS_TOKEN")),
        }
        results["ready"] = all(results[key] for key in ("manifest", "schemas", "secretsClean"))
        return results
    raise ValueError(f"unsupported local command: {args.command}")


def _remote(args: argparse.Namespace) -> object:
    client = SkillApiClient()
    command = args.command
    if command == "search":
        skills = client.request("GET", "/skills")
        query = args.query.casefold()
        return [item for item in skills if query in json.dumps(item, ensure_ascii=False).casefold()]
    if command == "info":
        return client.request("GET", f"/skills/{quote(args.name, safe='')}")
    if command == "versions":
        return client.request("GET", f"/skills/{quote(args.name, safe='')}/versions")
    if command == "publish":
        manifest = yaml.safe_load(Path(args.manifest).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a YAML object")
        package_payload = Path(args.package).read_bytes()
        return client.request(
            "POST",
            "/admin/skills/registry/versions",
            {
                "publisher_id": args.publisher_id,
                "manifest": manifest,
                "package_base64": base64.b64encode(package_payload).decode(),
                "package_checksum": hashlib.sha256(package_payload).hexdigest(),
                "signature_envelope": json.loads(Path(args.signature).read_text(encoding="utf-8")),
                "sbom": json.loads(Path(args.sbom).read_text(encoding="utf-8")),
                "provenance": json.loads(Path(args.provenance).read_text(encoding="utf-8")),
                "input_schema": _schema(args.input_schema),
                "output_schema": _schema(args.output_schema),
                "error_schema": _schema(args.error_schema),
            },
        )
    if command in {"list", "status"}:
        return client.request("GET", "/admin/skill-installations")
    if command in {"executions", "logs"}:
        return client.request("GET", "/admin/skill-executions")
    if command == "trace":
        return client.request("GET", f"/admin/skill-executions/{quote(args.execution_id, safe='')}")
    if command == "install-plan":
        name, version = _skill_ref(args.reference)
        return client.request(
            "POST",
            "/admin/skill-installations/plans",
            {
                "skill_name": name,
                "semantic_version": version,
                "environment": args.environment,
                "granted_permissions": args.permission,
                "configuration": {},
            },
        )
    if command == "install":
        return client.request(
            "POST",
            "/admin/skill-installations",
            {
                "plan_id": args.plan_id,
                "expected_plan_checksum": args.plan_checksum,
                "configuration": {},
            },
        )
    if command in {"disable", "enable", "rollback", "uninstall"}:
        operation = "activate" if command == "enable" else command
        payload = None if operation == "activate" else {"reason_code": args.reason}
        return client.request(
            "POST",
            f"/admin/skill-installations/{quote(args.installation_id, safe='')}/{operation}",
            payload,
        )
    if command == "upgrade":
        return client.request(
            "POST",
            f"/admin/skill-installations/{quote(args.installation_id, safe='')}/upgrade",
            {
                "target_version_id": args.version_id,
                "expected_version": args.expected_version,
                "granted_permissions": args.permission,
            },
        )
    if command in {"permissions", "dependencies"}:
        detail = client.request("GET", f"/skills/{quote(args.name, safe='')}")
        return detail.get(command, detail) if isinstance(detail, dict) else detail
    raise ValueError(f"unsupported remote command: {command}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="vav skill", description="Governed VAV Skill tooling")
    commands = root.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--type", required=True)
    create.add_argument("--runtime", default="python")
    create.add_argument("--directory", required=True)
    for name in ("validate", "doctor"):
        item = commands.add_parser(name)
        item.add_argument("--directory", default=".")
    test = commands.add_parser("test")
    test.add_argument("--directory", default=".")
    test.add_argument("--timeout", type=int, default=300)
    build = commands.add_parser("build")
    build.add_argument("--directory", default=".")
    build.add_argument("--output", required=True)
    sbom = commands.add_parser("sbom")
    sbom.add_argument("--directory", default=".")
    sbom.add_argument("--output", required=True)
    provenance = commands.add_parser("provenance")
    provenance.add_argument("--package", required=True)
    provenance.add_argument("--sbom", required=True)
    provenance.add_argument("--source", default=".")
    provenance.add_argument("--builder-id", required=True)
    provenance.add_argument("--output", required=True)
    sign = commands.add_parser("sign")
    sign.add_argument("--package", required=True)
    sign.add_argument("--key", required=True)
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--output", required=True)
    verify = commands.add_parser("verify-signature")
    verify.add_argument("--package", required=True)
    verify.add_argument("--signature", required=True)
    verify.add_argument("--public-key", required=True)

    schema = commands.add_parser("schema")
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    schema_check = schema_commands.add_parser("check")
    schema_check.add_argument("--schema", required=True)
    schema_generate = schema_commands.add_parser("generate")
    schema_generate.add_argument("--schema", required=True)
    schema_generate.add_argument("--name", required=True)
    schema_generate.add_argument("--output", required=True)
    schema_diff = schema_commands.add_parser("diff")
    schema_diff.add_argument("--from-schema", required=True)
    schema_diff.add_argument("--to-schema", required=True)

    search = commands.add_parser("search")
    search.add_argument("query")
    for name in ("info", "versions", "permissions", "dependencies"):
        item = commands.add_parser(name)
        item.add_argument("name")
    publish = commands.add_parser("publish")
    publish.add_argument("--publisher-id", required=True)
    publish.add_argument("--manifest", default="skill.yaml")
    publish.add_argument("--package", required=True)
    publish.add_argument("--signature", required=True)
    publish.add_argument("--sbom", required=True)
    publish.add_argument("--provenance", required=True)
    publish.add_argument("--input-schema", default="schemas/input.schema.json")
    publish.add_argument("--output-schema", default="schemas/output.schema.json")
    publish.add_argument("--error-schema", default="schemas/error.schema.json")
    for name in ("list", "status", "executions", "logs"):
        commands.add_parser(name)
    trace = commands.add_parser("trace")
    trace.add_argument("execution_id")
    plan = commands.add_parser("install-plan")
    plan.add_argument("reference")
    plan.add_argument("--environment", default="development")
    plan.add_argument("--permission", action="append", default=[])
    install = commands.add_parser("install")
    install.add_argument("--plan-id", required=True)
    install.add_argument("--plan-checksum", required=True)
    for name in ("disable", "enable", "rollback", "uninstall"):
        item = commands.add_parser(name)
        item.add_argument("installation_id")
        item.add_argument("--reason", default="operator_request")
    upgrade = commands.add_parser("upgrade")
    upgrade.add_argument("installation_id")
    upgrade.add_argument("--version-id", required=True)
    upgrade.add_argument("--expected-version", type=int, required=True)
    upgrade.add_argument("--permission", action="append", default=[])
    return root


LOCAL_COMMANDS = {
    "create",
    "validate",
    "test",
    "build",
    "sbom",
    "provenance",
    "sign",
    "verify-signature",
    "schema",
    "doctor",
}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = _run_local(args) if args.command in LOCAL_COMMANDS else _remote(args)
        _json(result)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
