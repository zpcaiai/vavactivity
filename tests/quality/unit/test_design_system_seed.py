from __future__ import annotations

import json
from pathlib import Path

import pytest

from vav.cli.seed_design_system import PAGE_CATALOG, _pages


def test_page_catalog_is_complete_and_produces_unique_records() -> None:
    pages = _pages(PAGE_CATALOG)

    assert len(pages) >= 150
    assert {page["application"] for page in pages} == {"user-web", "admin-web"}
    identities = {(page["application"], page["route_name"]) for page in pages}
    assert len(identities) == len(pages)
    assert all(page["source"].endswith(".vue") for page in pages)


def test_page_catalog_rejects_unsafe_frontend_source(tmp_path: Path) -> None:
    catalog = tmp_path / "page-catalog.yaml"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "routes": [
                    {
                        "application": "user-web",
                        "route_path": "/unsafe",
                        "component": "UnsafePage",
                        "source": "apps/user-web/src/../../secrets.vue",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsafe source path"):
        _pages(catalog)


def test_page_catalog_rejects_duplicate_routes(tmp_path: Path) -> None:
    route = {
        "application": "admin-web",
        "route_path": "/admin/duplicate",
        "component": "DuplicatePage",
        "source": "apps/admin-web/src/pages/DuplicatePage.vue",
    }
    catalog = tmp_path / "page-catalog.yaml"
    catalog.write_text(
        json.dumps({"schema_version": "1.0.0", "routes": [route, route]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate route"):
        _pages(catalog)
