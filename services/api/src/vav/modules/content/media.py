from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import boto3
from botocore.client import BaseClient
from PIL import Image, UnidentifiedImageError
from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vav.common.exceptions import VavError
from vav.core.config import Settings, get_settings
from vav.models.content import ContentLocalization, MediaAsset

ALLOWED_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/avif",
    "application/pdf",
}
IMAGE_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "image/avif": "AVIF",
}
DERIVATIVE_WIDTHS = {
    "thumbnail": 320,
    "small": 640,
    "medium": 1280,
    "large": 1920,
}


def detected_media_type(payload: bytes) -> str | None:
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    if (
        len(payload) >= 12
        and payload[4:8] == b"ftyp"
        and payload[8:12] in {b"avif", b"avis"}
    ):
        return "image/avif"
    if payload.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def image_derivatives(payload: bytes, mime_type: str) -> tuple[int, int, dict[str, bytes]]:
    try:
        with Image.open(BytesIO(payload)) as candidate:
            candidate.verify()
        with Image.open(BytesIO(payload)) as source:
            if source.format != IMAGE_FORMATS[mime_type]:
                raise VavError("MEDIA_MIME_MISMATCH", "Uploaded media type does not match.")
            width, height = source.size
            derivatives: dict[str, bytes] = {}
            for name, target_width in DERIVATIVE_WIDTHS.items():
                rendered = source.copy()
                rendered.thumbnail((target_width, target_width * 8), Image.Resampling.LANCZOS)
                if rendered.mode not in {"RGB", "RGBA"}:
                    output_mode = "RGBA" if "transparency" in rendered.info else "RGB"
                    rendered = rendered.convert(output_mode)
                output = BytesIO()
                rendered.save(output, format="WEBP", quality=82, method=6)
                derivatives[name] = output.getvalue()
            return width, height, derivatives
    except (KeyError, UnidentifiedImageError, OSError, SyntaxError) as error:
        raise VavError("MEDIA_CONTENT_INVALID", "Uploaded image content is invalid.") from error


class MediaService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def client(self, endpoint_url: str | None = None) -> BaseClient:
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url or self.settings.media_s3_endpoint,
            region_name=self.settings.media_s3_region,
            aws_access_key_id=self.settings.media_s3_access_key.get_secret_value(),
            aws_secret_access_key=self.settings.media_s3_secret_key.get_secret_value(),
        )

    async def create_upload(
        self,
        session: AsyncSession,
        *,
        filename: str,
        mime_type: str,
        byte_size: int,
        checksum_sha256: str,
        visibility: str,
        actor_id: UUID,
    ) -> tuple[MediaAsset, str]:
        if mime_type not in ALLOWED_MEDIA_TYPES:
            raise VavError("MEDIA_TYPE_NOT_ALLOWED", "Media type is not allowed.")
        size_limit = (
            self.settings.media_max_image_size_mb * 1024 * 1024
            if mime_type.startswith("image/")
            else 25 * 1024 * 1024
        )
        if byte_size > size_limit:
            raise VavError("MEDIA_TOO_LARGE", "Media exceeds the configured size limit.")
        suffix = Path(filename).suffix.casefold()
        bucket = (
            self.settings.media_bucket_public
            if visibility == "public"
            else self.settings.media_bucket_private
        )
        asset_id = uuid4()
        object_key = f"media/{asset_id}{suffix}"
        asset = MediaAsset(
            id=asset_id,
            storage_provider="s3",
            bucket_name=bucket,
            object_key=object_key,
            original_filename=Path(filename).name,
            media_type="image" if mime_type.startswith("image/") else "document",
            mime_type=mime_type,
            byte_size=byte_size,
            checksum_sha256=checksum_sha256.casefold(),
            visibility=visibility,
            processing_status="pending_upload",
            uploaded_by=actor_id,
        )
        session.add(asset)
        await session.commit()
        url = self.client(self.settings.media_s3_public_endpoint).generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": object_key,
                "ContentType": mime_type,
                "Metadata": {"sha256": checksum_sha256.casefold()},
            },
            ExpiresIn=900,
        )
        return asset, url

    async def complete(
        self, session: AsyncSession, asset: MediaAsset, checksum_sha256: str
    ) -> None:
        if checksum_sha256.casefold() != asset.checksum_sha256:
            raise VavError("MEDIA_CHECKSUM_MISMATCH", "Media checksum does not match.")
        client = self.client()
        response = await asyncio.to_thread(
            client.get_object,
            Bucket=asset.bucket_name,
            Key=asset.object_key,
        )
        body = response.get("Body")
        if body is None:
            raise VavError("MEDIA_OBJECT_MISSING", "Uploaded media object is unavailable.")
        payload = await asyncio.to_thread(body.read)
        if len(payload) != asset.byte_size:
            raise VavError("MEDIA_SIZE_MISMATCH", "Uploaded media size does not match.")
        if hashlib.sha256(payload).hexdigest() != asset.checksum_sha256:
            raise VavError("MEDIA_CHECKSUM_MISMATCH", "Uploaded media checksum does not match.")
        if detected_media_type(payload) != asset.mime_type:
            raise VavError("MEDIA_MIME_MISMATCH", "Uploaded media type does not match.")
        metadata = response.get("Metadata", {})
        if metadata.get("sha256") != asset.checksum_sha256:
            raise VavError("MEDIA_CHECKSUM_MISMATCH", "Uploaded media checksum does not match.")
        if asset.mime_type.startswith("image/"):
            width, height, derivatives = await asyncio.to_thread(
                image_derivatives,
                payload,
                asset.mime_type,
            )
            asset.width = width
            asset.height = height
            for variant, derivative in derivatives.items():
                await asyncio.to_thread(
                    client.put_object,
                    Bucket=asset.bucket_name,
                    Key=f"media/{asset.id}/{variant}.webp",
                    Body=derivative,
                    ContentType="image/webp",
                    CacheControl="public, max-age=31536000, immutable",
                )
        asset.processing_status = "ready"
        await session.commit()

    async def read_public(
        self,
        asset: MediaAsset,
        variant: str | None,
    ) -> tuple[bytes, str]:
        if variant and variant not in DERIVATIVE_WIDTHS:
            raise VavError("MEDIA_VARIANT_INVALID", "Media variant is invalid.", status_code=404)
        if variant and asset.media_type != "image":
            raise VavError("MEDIA_VARIANT_INVALID", "Media variant is invalid.", status_code=404)
        key = f"media/{asset.id}/{variant}.webp" if variant else asset.object_key
        try:
            response = await asyncio.to_thread(
                self.client().get_object,
                Bucket=asset.bucket_name,
                Key=key,
            )
            body = response.get("Body")
            if body is None:
                raise VavError("MEDIA_NOT_FOUND", "Media was not found.", status_code=404)
            payload = await asyncio.to_thread(body.read)
        except VavError:
            raise
        except Exception as error:
            raise VavError("MEDIA_NOT_FOUND", "Media was not found.", status_code=404) from error
        return payload, "image/webp" if variant else asset.mime_type

    async def references(self, session: AsyncSession, asset_id: UUID) -> list[ContentLocalization]:
        return list(
            (
                await session.scalars(
                    select(ContentLocalization).where(
                        or_(
                            ContentLocalization.cover_media_id == asset_id,
                            cast(ContentLocalization.content_blocks, String).contains(
                                str(asset_id)
                            ),
                        )
                    )
                )
            ).all()
        )


media_service = MediaService()
