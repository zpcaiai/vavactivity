"""Object-storage binding for profile media (PROFILE-001).

Why this module exists: the rest of the profile-media code was written against
``private_media_path()``, which returns ``/media/private/<token>``. Nothing in
this repository serves that path — not the API, not a proxy, nothing — so an
upload had nowhere to send its bytes and an ``<img src>`` pointing at it would
404. The domain rules (opaque token, unguessable URL, signed per-viewer grant)
were all in place; the storage binding under them was missing.

This platform's convention, stated in ``core/http_hardening`` and implemented in
``modules/content/media``, is that object bytes never pass through the public
API: clients POST to a presigned storage target and GET from one. Uploads land
under a temporary prefix. Finalization verifies the bytes and then writes a
different final key that the presigned policy can never overwrite. Keeping the
two namespaces separate is essential: a presigned URL remains usable until it
expires, so signing the eventual read key would let a client replace bytes after
moderation.

``private_media_path`` keeps its meaning as the asset's *logical identity* and
stays in payloads for logging and comparison. It is not a fetchable URL, and
callers that need one ask for a grant.
"""

from __future__ import annotations

import hashlib
import re

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from vav.common.exceptions import VavError
from vav.core.config import Settings, get_settings

#: Presigned upload lifetime. Long enough for a phone on a slow connection to
#: push a 100 MB video, short enough that a leaked URL is not a standing grant.
UPLOAD_URL_TTL_SECONDS = 900

#: Storage prefix. Kept separate from the CMS media library's ``media/`` prefix
#: so a bucket policy or lifecycle rule can treat member media differently from
#: editorial assets without pattern-matching on anything ambiguous.
OBJECT_PREFIX = "profile-media"
_TOKEN_PATTERN = re.compile(r"^[A-Z2-7]{26}$")


def _token(access_token: str) -> str:
    token = (access_token or "").strip()
    if _TOKEN_PATTERN.fullmatch(token) is None:
        raise VavError(
            "MEDIA_TOKEN_INVALID",
            "A private media token must be a 26-character base32 value.",
        )
    return token


def upload_object_key(access_token: str) -> str:
    """Temporary key a browser may write during the upload window."""

    return f"{OBJECT_PREFIX}/uploads/{_token(access_token)}"


def object_key(access_token: str) -> str:
    """Immutable final storage key for one asset.

    Derived from the opaque token and nothing else. Using the asset id or the
    owner id here would make the whole bucket walkable by anyone who learned one
    key, which is exactly what ``assert_url_is_not_predictable`` exists to stop
    at the URL layer.
    """

    return f"{OBJECT_PREFIX}/assets/{_token(access_token)}"


def legacy_object_key(access_token: str) -> str:
    """Key used before uploads and final objects were separated.

    Existing active rows keep this exact key in ``profile_media_assets``. New
    writes never use it, but retaining the helper lets a forward migration keep
    already-uploaded media readable without a bucket-wide synchronous copy.
    """

    return f"{OBJECT_PREFIX}/{_token(access_token)}"


def validate_storage_key(access_token: str, storage_key: str) -> str:
    """Refuse a database value that does not belong to this asset token."""

    key = (storage_key or "").strip()
    allowed = {
        upload_object_key(access_token),
        object_key(access_token),
        legacy_object_key(access_token),
    }
    if key not in allowed:
        raise VavError(
            "MEDIA_STORAGE_KEY_INVALID",
            "The stored media key does not belong to this asset.",
            status_code=500,
        )
    return key


def _client(settings: Settings, *, endpoint: str | None = None) -> BaseClient:
    # SigV4 is pinned rather than left to the default. Under the older SigV2
    # scheme boto emits ``Expires=<epoch>`` and silently drops several signed
    # parameters, which is how the size cap below came to be claimed but not
    # enforced. Most S3-compatible providers also require v4 outright.
    return boto3.client(
        "s3",
        endpoint_url=endpoint or settings.media_s3_endpoint,
        region_name=settings.media_s3_region,
        aws_access_key_id=settings.media_s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.media_s3_secret_key.get_secret_value(),
        config=Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=15,
            # The PostgreSQL deletion intent already owns durable exponential
            # backoff. Keep SDK retries small so one black-holed provider does
            # not hold a database transaction and worker slot indefinitely.
            retries={"mode": "standard", "total_max_attempts": 2},
        ),
    )


def _presign(operation: str, params: dict[str, object], ttl_seconds: int) -> str:
    settings = get_settings()
    # The browser-reachable endpoint, not the in-cluster one: a URL signed
    # against the internal hostname is valid but unreachable from a phone.
    client = _client(settings, endpoint=settings.media_s3_public_endpoint)
    try:
        return str(client.generate_presigned_url(operation, Params=params, ExpiresIn=ttl_seconds))
    except (BotoCoreError, ClientError) as error:
        # Storage being down must not read as "this asset does not exist" —
        # that is the vocabulary reserved for a permission decision.
        raise VavError(
            "MEDIA_STORAGE_UNAVAILABLE",
            "Media storage is unavailable.",
            status_code=503,
        ) from error


def presigned_upload(access_token: str, *, mime_type: str, max_bytes: int) -> dict[str, object]:
    """A short-lived staging target for the bytes of a newly registered asset.

    This is a presigned **POST policy**, not a presigned PUT URL, and the reason
    is the size cap. A presigned PUT cannot enforce one: ``ContentLength`` is
    not carried in the signature, so a client that registered a 1 KB photo could
    PUT two gigabytes and storage would accept it. A POST policy carries a
    ``content-length-range`` condition that storage itself enforces, which is
    the difference between a documented limit and a real one.

    Returns the form target and the exact fields that must accompany the upload;
    the caller sends them verbatim rather than reconstructing any of them. The
    staging key may be overwritten until this policy expires; finalization reads
    one complete version into server memory and conditionally creates a distinct
    immutable final key, so such a retry cannot replace published bytes.
    """

    settings = get_settings()
    try:
        versioning = str(
            _client(settings)
            .get_bucket_versioning(Bucket=settings.media_bucket_private)
            .get("Status")
            or ""
        )
    except (BotoCoreError, ClientError) as error:
        raise VavError(
            "MEDIA_STORAGE_UNAVAILABLE", "Media storage is unavailable.", status_code=503
        ) from error
    if versioning in {"Enabled", "Suspended"}:
        # A reusable POST policy against a versioned staging key can create an
        # unbounded number of retained versions without another API request.
        # Keep this shared bucket versioning-off until staging/final namespaces
        # are split into independently governed buckets.
        raise VavError(
            "MEDIA_STORAGE_CONFIGURATION_INVALID",
            "Profile media staging requires bucket versioning to be disabled.",
            status_code=503,
        )
    client = _client(settings, endpoint=settings.media_s3_public_endpoint)
    try:
        presigned = client.generate_presigned_post(
            Bucket=settings.media_bucket_private,
            Key=upload_object_key(access_token),
            Fields={"Content-Type": mime_type},
            Conditions=[
                {"Content-Type": mime_type},
                # Zero-length is excluded deliberately: an empty object would
                # pass ``object_exists`` and become an "active" broken asset.
                ["content-length-range", 1, int(max_bytes)],
            ],
            ExpiresIn=UPLOAD_URL_TTL_SECONDS,
        )
    except (BotoCoreError, ClientError) as error:
        raise VavError(
            "MEDIA_STORAGE_UNAVAILABLE",
            "Media storage is unavailable.",
            status_code=503,
        ) from error
    return {
        "url": presigned["url"],
        "method": "POST",
        "fields": presigned["fields"],
        "max_bytes": int(max_bytes),
        "expires_in_seconds": UPLOAD_URL_TTL_SECONDS,
    }


def _not_found(error: ClientError) -> bool:
    return str(error.response.get("Error", {}).get("Code", "")) in {
        "404",
        "NoSuchKey",
        "NotFound",
    }


def measure_object(
    access_token: str, *, storage_key: str | None = None
) -> dict[str, object] | None:
    """The size and type storage actually recorded, or ``None`` if absent.

    This is what makes "limits are enforced twice" true. Finalization used to
    re-validate the numbers the *client* sent, which is the same trust boundary
    as registration — checking a client's claim twice is still checking a claim.
    Reading them back from storage checks the bytes.
    """

    settings = get_settings()
    client = _client(settings)
    try:
        key = validate_storage_key(access_token, storage_key or upload_object_key(access_token))
        head = client.head_object(Bucket=settings.media_bucket_private, Key=key)
    except ClientError as error:
        if _not_found(error):
            return None
        raise VavError(
            "MEDIA_STORAGE_UNAVAILABLE", "Media storage is unavailable.", status_code=503
        ) from error
    except BotoCoreError as error:
        raise VavError(
            "MEDIA_STORAGE_UNAVAILABLE", "Media storage is unavailable.", status_code=503
        ) from error
    return {
        "byte_size": int(head.get("ContentLength") or 0),
        "mime_type": str(head.get("ContentType") or ""),
        "etag": str(head.get("ETag") or "").strip('"'),
        "version_id": str(head.get("VersionId") or "") or None,
        "checksum_sha256": str((head.get("Metadata") or {}).get("sha256") or "") or None,
        "storage_key": key,
    }


def read_object(access_token: str, *, storage_key: str, max_bytes: int) -> dict[str, object]:
    """Read a bounded staged object for server-side content inspection.

    The POST policy is the first size control. This bound is independent of the
    policy and protects finalization if a bucket policy is accidentally relaxed
    or a legacy object predates the POST flow.
    """

    settings = get_settings()
    key = validate_storage_key(access_token, storage_key)
    client = _client(settings)
    try:
        response = client.get_object(Bucket=settings.media_bucket_private, Key=key)
        length = int(response.get("ContentLength") or 0)
        if length < 1 or length > int(max_bytes):
            raise VavError(
                "MEDIA_FILE_TOO_LARGE" if length > int(max_bytes) else "MEDIA_FILE_EMPTY",
                "The uploaded file is outside the permitted size range.",
                status_code=422,
                details=[{"byte_size": length, "max_bytes": int(max_bytes)}],
            )
        body = response.get("Body")
        if body is None:
            raise VavError(
                "MEDIA_BYTES_MISSING",
                "No uploaded content was found for this asset.",
                status_code=409,
            )
        payload = body.read(int(max_bytes) + 1)
        if len(payload) != length or len(payload) > int(max_bytes):
            raise VavError(
                "MEDIA_SIZE_MISMATCH",
                "The uploaded object changed while it was being inspected.",
                status_code=409,
            )
    except VavError:
        raise
    except ClientError as error:
        if _not_found(error):
            raise VavError(
                "MEDIA_BYTES_MISSING",
                "No uploaded content was found for this asset.",
                status_code=409,
            ) from error
        raise VavError(
            "MEDIA_STORAGE_UNAVAILABLE", "Media storage is unavailable.", status_code=503
        ) from error
    except (BotoCoreError, OSError) as error:
        raise VavError(
            "MEDIA_STORAGE_UNAVAILABLE", "Media storage is unavailable.", status_code=503
        ) from error
    return {
        "content": payload,
        "byte_size": len(payload),
        "mime_type": str(response.get("ContentType") or ""),
        "etag": str(response.get("ETag") or "").strip('"'),
        "version_id": str(response.get("VersionId") or "") or None,
        "checksum_sha256": hashlib.sha256(payload).hexdigest(),
        "storage_key": key,
    }


def write_final_object(
    access_token: str,
    *,
    content: bytes,
    mime_type: str,
    checksum_sha256: str,
) -> dict[str, object]:
    """Write inspected bytes to the final namespace and return stored truth."""

    settings = get_settings()
    key = object_key(access_token)
    client = _client(settings)
    try:
        client.put_object(
            Bucket=settings.media_bucket_private,
            Key=key,
            Body=content,
            ContentType=mime_type,
            Metadata={"sha256": checksum_sha256},
            CacheControl="private, no-store",
            IfNoneMatch="*",
        )
    except ClientError as error:
        if str(error.response.get("Error", {}).get("Code", "")) in {
            "412",
            "PreconditionFailed",
        }:
            measured = measure_object(access_token, storage_key=key)
            if (
                measured is not None
                and int(str(measured["byte_size"])) == len(content)
                and measured["checksum_sha256"] == checksum_sha256
            ):
                # A database commit may fail after the immutable object write.
                # Retrying the same inspected bytes is safe and idempotent.
                return {**measured, "checksum_sha256": checksum_sha256}
            raise VavError(
                "MEDIA_FINAL_OBJECT_CONFLICT",
                "A different finalized object already exists for this asset.",
                status_code=409,
            ) from error
        raise VavError(
            "MEDIA_STORAGE_UNAVAILABLE", "Media storage is unavailable.", status_code=503
        ) from error
    except BotoCoreError as error:
        raise VavError(
            "MEDIA_STORAGE_UNAVAILABLE", "Media storage is unavailable.", status_code=503
        ) from error
    measured = measure_object(access_token, storage_key=key)
    if measured is None:
        raise VavError(
            "MEDIA_STORAGE_UNAVAILABLE", "Final media storage verification failed.", status_code=503
        )
    if int(str(measured["byte_size"])) != len(content):
        raise VavError(
            "MEDIA_SIZE_MISMATCH",
            "The finalized object size does not match the inspected bytes.",
            status_code=409,
        )
    if measured["checksum_sha256"] != checksum_sha256:
        raise VavError(
            "MEDIA_STORAGE_INTEGRITY_MISMATCH",
            "The finalized object checksum metadata does not match the inspected bytes.",
            status_code=409,
        )
    return {**measured, "checksum_sha256": checksum_sha256}


def delete_storage_key(access_token: str, *, storage_key: str) -> None:
    """Idempotently remove every physical version belonging to one key.

    On a versioned bucket, plain ``DeleteObject`` only creates a delete marker;
    the private bytes remain recoverable and a privacy queue must not call that
    "completed".  Enumerate and delete exact-key versions and markers when
    versioning is enabled or suspended, then verify that no version remains.
    """

    settings = get_settings()
    key = validate_storage_key(access_token, storage_key)
    client = _client(settings)
    try:
        bucket = settings.media_bucket_private
        versioning = str(client.get_bucket_versioning(Bucket=bucket).get("Status") or "")
        if versioning in {"Enabled", "Suspended"}:
            paginator = client.get_paginator("list_object_versions")
            for page in paginator.paginate(Bucket=bucket, Prefix=key):
                objects = [
                    {"Key": key, "VersionId": str(item["VersionId"])}
                    for group in ("Versions", "DeleteMarkers")
                    for item in page.get(group, [])
                    if item.get("Key") == key and item.get("VersionId") is not None
                ]
                if objects:
                    client.delete_objects(
                        Bucket=bucket,
                        Delete={"Objects": objects, "Quiet": True},
                    )
            residual = [
                item
                for page in paginator.paginate(Bucket=bucket, Prefix=key)
                for group in ("Versions", "DeleteMarkers")
                for item in page.get(group, [])
                if item.get("Key") == key
            ]
            if residual:
                raise VavError(
                    "MEDIA_STORAGE_DELETE_INCOMPLETE",
                    "Media storage still contains object versions after deletion.",
                    status_code=503,
                )
        else:
            client.delete_object(Bucket=bucket, Key=key)
    except (BotoCoreError, ClientError) as error:
        raise VavError(
            "MEDIA_STORAGE_UNAVAILABLE", "Media storage is unavailable.", status_code=503
        ) from error


def presigned_read_url(
    access_token: str, *, storage_key: str | None = None, ttl_seconds: int
) -> str:
    """A short-lived GET URL for an asset the caller has been granted.

    Authorization happened before this is called. This function only turns an
    already-made decision into something a browser can fetch, and it must never
    be reachable from a path that has not made that decision.
    """

    settings = get_settings()
    return _presign(
        "get_object",
        {
            "Bucket": settings.media_bucket_private,
            "Key": validate_storage_key(access_token, storage_key or object_key(access_token)),
        },
        ttl_seconds,
    )


def object_exists(access_token: str) -> bool:
    """Whether any bytes landed at all.

    A missing object means the member abandoned the upload, which must not be
    recorded as a finished asset.
    """

    return measure_object(access_token) is not None
