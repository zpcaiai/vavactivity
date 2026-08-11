from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _selected_seed_modules() -> list[str]:
    groups = {"system", "reference"}
    current_group = ""
    modules: list[str] = []
    for raw_line in (
        (ROOT / "config/seeds/manifest.yaml").read_text(encoding="utf-8").splitlines()
    ):
        line = raw_line.split("#", 1)[0].rstrip()
        if line.startswith("  ") and line.endswith(":") and not line.startswith("    "):
            current_group = line.strip().removesuffix(":")
        elif current_group in groups and line.strip().startswith("- "):
            modules.append(line.strip().removeprefix("- "))
    return modules


def test_seed_skips_clean_state_without_unbound_array(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
case "$*" in
  *"get_settings().environment"*) printf 'development\n' ;;
  *) printf 'unexpected docker invocation: %s\n' "$*" >&2; exit 9 ;;
esac
""",
    )

    manifest = ROOT / "config/seeds/manifest.yaml"
    state_file = tmp_path / "seed-state.txt"
    state_lines = [f"manifest_sha={hashlib.sha256(manifest.read_bytes()).hexdigest()}"]
    for module in _selected_seed_modules():
        module_file = (
            ROOT / "services/api/src/vav/cli" / f"{module.rsplit('.', 1)[-1]}.py"
        )
        state_lines.append(
            f"module:{module}={hashlib.sha256(module_file.read_bytes()).hexdigest()}"
        )
    state_file.write_text("\n".join(state_lines) + "\n", encoding="utf-8")

    result = subprocess.run(
        [str(ROOT / "scripts/vavctl"), "seed"],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "VAV_SEED_STATE_FILE": str(state_file),
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "seed module checksums unchanged; skipping seed execution" in result.stdout
