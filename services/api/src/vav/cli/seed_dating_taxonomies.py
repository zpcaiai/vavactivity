"""Seed the versioned dating-profile schema release and taxonomies."""

# ruff: noqa: E501

from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import text

from vav.core.database import session_factory
from vav.modules.matchmaking_profiles.taxonomies import (
    COMPLETENESS_POLICY,
    FIELD_MANIFEST,
    SCHEMA_CODE,
    SCHEMA_SEMANTIC_VERSION,
    SUBMISSION_POLICY,
    TAXONOMIES,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


async def seed_dating_taxonomies() -> None:
    async with session_factory() as session:
        owner_id = await session.scalar(text("SELECT id FROM users ORDER BY created_at LIMIT 1"))
        if owner_id is None:
            print("No users exist yet; run the base seed first.")
            return

        release_id = await session.scalar(
            text(
                "SELECT id FROM dating_profile_schema_releases WHERE schema_code=:code AND semantic_version=:version"
            ),
            {"code": SCHEMA_CODE, "version": SCHEMA_SEMANTIC_VERSION},
        )
        if release_id is not None:
            # Re-activate an existing release if the environment has none active.
            await session.execute(
                text(
                    "UPDATE dating_profile_schema_releases SET status='active' WHERE id=:id "
                    "AND status <> 'active' AND NOT EXISTS ("
                    "SELECT 1 FROM dating_profile_schema_releases WHERE schema_code=:code AND status='active')"
                ),
                {"id": release_id, "code": SCHEMA_CODE},
            )
        if release_id is None:
            release_id = await session.scalar(
                text(
                    "INSERT INTO dating_profile_schema_releases "
                    "(schema_code,semantic_version,status,field_manifest,completeness_policy,submission_policy,"
                    "created_by,approved_by,approved_at) "
                    "VALUES (:code,:version,'active',CAST(:manifest AS jsonb),CAST(:completeness AS jsonb),"
                    "CAST(:submission AS jsonb),:owner,:owner,now()) RETURNING id"
                ),
                {
                    "code": SCHEMA_CODE,
                    "version": SCHEMA_SEMANTIC_VERSION,
                    "manifest": _json(FIELD_MANIFEST),
                    "completeness": _json(COMPLETENESS_POLICY),
                    "submission": _json(SUBMISSION_POLICY),
                    "owner": owner_id,
                },
            )
            for index, definition in enumerate(FIELD_MANIFEST):
                await session.execute(
                    text(
                        "INSERT INTO dating_profile_field_definitions "
                        "(schema_release_id,field_code,section_code,field_type,value_schema,required_for_submission,"
                        "required_for_recommendation,sensitivity,default_visibility,searchable,recommendation_eligible,sort_order) "
                        "VALUES (:release,:code,:section,:type,CAST(:schema AS jsonb),:required,:recommended,"
                        ":sensitivity,:visibility,:searchable,:rec_eligible,:sort) "
                        "ON CONFLICT (schema_release_id,field_code) DO NOTHING"
                    ),
                    {
                        "release": release_id,
                        "code": definition["field_code"],
                        "section": definition["section_code"],
                        "type": definition["field_type"],
                        "schema": _json(definition["value_schema"]),
                        "required": definition["required_for_submission"],
                        "recommended": definition["required_for_recommendation"],
                        "sensitivity": definition["sensitivity"],
                        "visibility": definition["default_visibility"],
                        "searchable": definition["searchable"],
                        "rec_eligible": definition["recommendation_eligible"],
                        "sort": index,
                    },
                )

        taxonomy_count = 0
        for taxonomy_code, values in TAXONOMIES.items():
            taxonomy_id = await session.scalar(
                text(
                    "SELECT id FROM dating_taxonomies WHERE taxonomy_code=:code AND semantic_version='1.0.0'"
                ),
                {"code": taxonomy_code},
            )
            if taxonomy_id is None:
                taxonomy_id = await session.scalar(
                    text(
                        "INSERT INTO dating_taxonomies (taxonomy_code,semantic_version,status,values_manifest,"
                        "approved_by,approved_at) "
                        "VALUES (:code,'1.0.0','active',CAST(:values AS jsonb),:owner,now()) RETURNING id"
                    ),
                    {
                        "code": taxonomy_code,
                        "values": _json(
                            [
                                {"code": value["code"], "enabled": value["enabled"]}
                                for value in values
                            ]
                        ),
                        "owner": owner_id,
                    },
                )
                taxonomy_count += 1
            for value in values:
                for locale, label in value["labels"].items():
                    await session.execute(
                        text(
                            "INSERT INTO dating_taxonomy_localizations (taxonomy_id,value_code,locale,label) "
                            "VALUES (:taxonomy,:code,:locale,:label) "
                            "ON CONFLICT (taxonomy_id,value_code,locale) DO UPDATE SET label=EXCLUDED.label"
                        ),
                        {
                            "taxonomy": taxonomy_id,
                            "code": value["code"],
                            "locale": locale,
                            "label": label,
                        },
                    )
        await session.commit()
    print(
        f"Dating taxonomy seed complete: schema {SCHEMA_CODE}@{SCHEMA_SEMANTIC_VERSION}, "
        f"{len(FIELD_MANIFEST)} fields, {len(TAXONOMIES)} taxonomies ({taxonomy_count} new)"
    )


if __name__ == "__main__":
    asyncio.run(seed_dating_taxonomies())
