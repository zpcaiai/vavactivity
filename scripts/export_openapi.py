#!/usr/bin/env python3
"""Export the FastAPI contract deterministically."""

from __future__ import annotations

import json
from pathlib import Path

from vav.main import app

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "packages" / "contracts" / "openapi.json"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"OpenAPI exported to {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

