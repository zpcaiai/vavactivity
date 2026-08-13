"""Database + object-storage lifecycle coverage for private profile media."""

from __future__ import annotations

import io
from typing import Any
from uuid import UUID

import boto3
import pytest
from moto import mock_aws
from PIL import Image
from sqlalchemy import text

from tests.privacy.helpers import create_privacy_user
from vav.common.exceptions import VavError
from vav.core.database import session_factory
from vav.modules.profile_media import service, storage

BUCKET = "vav-private-service-flow"


def _jpeg(colour: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (320, 240), color=colour)
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


class _Secret:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


class _StorageSettings:
    media_s3_endpoint = None
    media_s3_public_endpoint = None
    media_s3_region = "us-east-1"
    media_s3_access_key = _Secret("test")
    media_s3_secret_key = _Secret("test")
    media_bucket_private = BUCKET


def _put_staged(s3: Any, registration: dict[str, Any], payload: bytes) -> None:
    fields = registration["upload"]["fields"]
    s3.put_object(
        Bucket=BUCKET,
        Key=fields["key"],
        Body=payload,
        ContentType="image/jpeg",
    )


@pytest.mark.asyncio
async def test_register_finalize_replace_delete_and_physical_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with mock_aws():
        s3 = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        s3.create_bucket(Bucket=BUCKET)
        monkeypatch.setattr(storage, "get_settings", lambda: _StorageSettings())

        first_bytes = _jpeg((10, 20, 30))
        second_bytes = _jpeg((90, 80, 70))
        async with session_factory() as session:
            user = await create_privacy_user(session)
            owner_id = user.id

            first = await service.register_upload(
                session,
                owner_id=owner_id,
                payload={
                    "kind": "photo",
                    "mime_type": "image/jpeg",
                    "byte_size": len(first_bytes),
                    "duration_seconds": None,
                    "position": 1,
                },
            )
            _put_staged(s3, first, first_bytes)
            finalized = await service.finalize_upload(
                session,
                owner_id=owner_id,
                asset_id=UUID(first["asset_id"]),
                payload={
                    "mime_type": "image/jpeg",
                    "byte_size": len(first_bytes),
                    "duration_seconds": None,
                },
            )
            assert finalized["assets"][0]["state"] == "active"
            await service.decide_moderation(
                session,
                asset_id=UUID(first["asset_id"]),
                actor_id=owner_id,
                payload={"decision": "approved", "reason_code": None, "note": None},
            )
            first_row = (
                (
                    await session.execute(
                        text(
                            "SELECT access_token,storage_key,storage_etag,checksum_sha256,"
                            "storage_verified_at FROM profile_media_assets WHERE id=:id"
                        ),
                        {"id": first["asset_id"]},
                    )
                )
                .mappings()
                .one()
            )
            assert first_row["storage_key"] == storage.object_key(first_row["access_token"])
            assert first_row["storage_etag"]
            assert first_row["checksum_sha256"]
            assert first_row["storage_verified_at"] is not None
            grant = await service.issue_media_grant(
                session, viewer_id=owner_id, asset_id=UUID(first["asset_id"])
            )
            assert grant["media_url"]

            # Even a same-length privileged overwrite is denied on the next
            # grant. Browser policies can never write this namespace, but the
            # integrity binding also catches operator/provider corruption.
            original = s3.get_object(Bucket=BUCKET, Key=first_row["storage_key"])
            original_content = original["Body"].read()
            original_metadata = original["Metadata"]
            s3.put_object(
                Bucket=BUCKET,
                Key=first_row["storage_key"],
                Body=b"x" * len(original_content),
                ContentType="image/jpeg",
                Metadata=original_metadata,
            )
            with pytest.raises(VavError) as integrity_error:
                await service.issue_media_grant(
                    session, viewer_id=owner_id, asset_id=UUID(first["asset_id"])
                )
            assert integrity_error.value.code == "MEDIA_STORAGE_INTEGRITY_MISMATCH"
            s3.put_object(
                Bucket=BUCKET,
                Key=first_row["storage_key"],
                Body=original_content,
                ContentType="image/jpeg",
                Metadata=original_metadata,
            )

            replacement = await service.replace_asset(
                session,
                owner_id=owner_id,
                asset_id=UUID(first["asset_id"]),
                payload={
                    "kind": "photo",
                    "mime_type": "image/jpeg",
                    "byte_size": len(second_bytes),
                    "duration_seconds": None,
                },
            )
            # Registering a replacement does not downline the current asset.
            assert (
                await session.scalar(
                    text("SELECT state FROM profile_media_assets WHERE id=:id"),
                    {"id": first["asset_id"]},
                )
                == "active"
            )
            _put_staged(s3, replacement, second_bytes)
            await service.finalize_upload(
                session,
                owner_id=owner_id,
                asset_id=UUID(replacement["asset_id"]),
                payload={
                    "mime_type": "image/jpeg",
                    "byte_size": len(second_bytes),
                    "duration_seconds": None,
                },
            )
            assert (
                await session.scalar(
                    text("SELECT state FROM profile_media_assets WHERE id=:id"),
                    {"id": first["asset_id"]},
                )
                == "active"
            )
            assert (
                await session.scalar(
                    text("SELECT state FROM profile_media_assets WHERE id=:id"),
                    {"id": replacement["asset_id"]},
                )
                == "uploading"
            )
            assert (
                await service.issue_admin_media_grant(
                    session,
                    viewer_id=owner_id,
                    asset_id=UUID(replacement["asset_id"]),
                )
            )["media_url"]
            assert (
                await service.issue_media_grant(
                    session,
                    viewer_id=owner_id,
                    asset_id=UUID(replacement["asset_id"]),
                )
            )["media_url"]

            # The reviewed old photo stays public while its replacement is
            # pending. Approval performs the slot swap atomically.
            await service.decide_moderation(
                session,
                asset_id=UUID(replacement["asset_id"]),
                actor_id=owner_id,
                payload={"decision": "approved", "reason_code": None, "note": None},
            )
            assert (
                await session.scalar(
                    text("SELECT state FROM profile_media_assets WHERE id=:id"),
                    {"id": first["asset_id"]},
                )
                == "replaced"
            )
            assert (
                await session.scalar(
                    text("SELECT state FROM profile_media_assets WHERE id=:id"),
                    {"id": replacement["asset_id"]},
                )
                == "active"
            )

            rejected = await service.replace_asset(
                session,
                owner_id=owner_id,
                asset_id=UUID(replacement["asset_id"]),
                payload={
                    "kind": "photo",
                    "mime_type": "image/jpeg",
                    "byte_size": len(first_bytes),
                    "duration_seconds": None,
                },
            )
            _put_staged(s3, rejected, first_bytes)
            await service.finalize_upload(
                session,
                owner_id=owner_id,
                asset_id=UUID(rejected["asset_id"]),
                payload={
                    "mime_type": "image/jpeg",
                    "byte_size": len(first_bytes),
                    "duration_seconds": None,
                },
            )
            await service.decide_moderation(
                session,
                asset_id=UUID(rejected["asset_id"]),
                actor_id=owner_id,
                payload={
                    "decision": "rejected",
                    "reason_code": "CONTENT_UNACCEPTABLE",
                    "note": None,
                },
            )
            assert (
                await session.scalar(
                    text("SELECT state FROM profile_media_assets WHERE id=:id"),
                    {"id": replacement["asset_id"]},
                )
                == "active"
            )
            assert (
                await session.scalar(
                    text("SELECT state FROM profile_media_assets WHERE id=:id"),
                    {"id": rejected["asset_id"]},
                )
                == "deleted"
            )

            orphaned_target = await service.replace_asset(
                session,
                owner_id=owner_id,
                asset_id=UUID(replacement["asset_id"]),
                payload={
                    "kind": "photo",
                    "mime_type": "image/jpeg",
                    "byte_size": len(first_bytes),
                    "duration_seconds": None,
                },
            )
            _put_staged(s3, orphaned_target, first_bytes)
            await service.finalize_upload(
                session,
                owner_id=owner_id,
                asset_id=UUID(orphaned_target["asset_id"]),
                payload={
                    "mime_type": "image/jpeg",
                    "byte_size": len(first_bytes),
                    "duration_seconds": None,
                },
            )
            await service.delete_asset(
                session,
                owner_id=owner_id,
                asset_id=UUID(replacement["asset_id"]),
            )
            # Rejecting a verified candidate must still clean it up if its old
            # target was removed while moderation was pending.
            await service.decide_moderation(
                session,
                asset_id=UUID(orphaned_target["asset_id"]),
                actor_id=owner_id,
                payload={
                    "decision": "rejected",
                    "reason_code": "TARGET_REMOVED",
                    "note": None,
                },
            )
            pending = int(
                await session.scalar(
                    text(
                        "SELECT count(*) FROM profile_media_storage_deletions WHERE state='pending'"
                    )
                )
                or 0
            )
            assert pending >= 4

            # Final objects are immediately due, but staged keys stay until the
            # browser POST policy has expired; deleting earlier would allow the
            # still-valid policy to recreate an orphan after cleanup completed.
            delayed = int(
                await session.scalar(
                    text(
                        "SELECT count(*) FROM profile_media_storage_deletions "
                        "WHERE state='pending' AND next_attempt_at > now()"
                    )
                )
                or 0
            )
            assert delayed == 4
            first_cleanup = await service.process_storage_deletions(session, limit=20)
            assert first_cleanup == {"completed": pending - delayed, "failed": 0}

            # Simulate reaching the policy/grace deadline without sleeping.
            await session.execute(
                text(
                    "UPDATE profile_media_storage_deletions SET next_attempt_at=now() "
                    "WHERE state='pending'"
                )
            )
            await session.commit()
            final_cleanup = await service.process_storage_deletions(session, limit=20)
            assert final_cleanup == {"completed": delayed, "failed": 0}

        remaining = s3.list_objects_v2(Bucket=BUCKET).get("Contents", [])
        assert remaining == []
