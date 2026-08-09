#!/usr/bin/env python3
"""Fail when Alembic has divergent migration heads."""

from __future__ import annotations

import subprocess
import sys


def main() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        check=True,
        capture_output=True,
        text=True,
        cwd="services/api",
    )
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    if len(heads) != 1:
        raise SystemExit(f"expected exactly one Alembic head, found {len(heads)}: {heads}")
    print(f"single migration head: {heads[0]}")


if __name__ == "__main__":
    main()
