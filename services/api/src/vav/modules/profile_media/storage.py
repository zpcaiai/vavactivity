"""Object-storage binding for profile media (PROFILE-001).

Why this module exists: the rest of the profile-media code was written against
``private_media_path()``, which returns ``/media/private/<token>``. Nothing in
this repository serves that path — not the API, not a proxy, nothing — so an
upload had nowhere to send its bytes and an ``<img src>`` pointing at it would
404. The domain rules (opaque token, unguessable URL, signed per-viewer grant)
were all in place; the storage binding under them was missing.

This platform's convention, stated in ``core/http_hardening`` and implemented in
``modules/content/media``, is that object bytes never pass through the API:
clients PUT to a presigned storage URL and GET from one. This module applies
that convention to profile media, keeping the guarantee that made the token
design worth having — the object key is derived from the opaque token, so a
member's media is not enumerable from an asset id, a user id, or a sequence.

``private_media_path`` keeps its meaning as the asset's *logical identity* and
stays in payloads for logging and comparison. It is not a fetchable URL, and
callers that need one ask for a grant.
"""

from __future__ import annotations

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


def object_key(access_token: str) -> str:
    """The storage key for one asset.

    Derived from the opaque token and nothing else. Using the asset id or the
    owner id here would make the whole bucket walkable by anyone who learned one
    key, which is exactly what ``assert_url_is_not_predictable`` exists to stop
    at the URL layer.
    """

    token = (access_token or "").strip()
    if not token:
        raise VavError("MEDIA_TOKEN_INVALID", "A private media token is required.")
    return f"{OBJECT_PREFIX}/{token}"


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
        config=Config(signature_version="s3v4"),
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
    """A one-shot upload target for the bytes of a newly registered asset.

    This is a presigned **POST policy**, not a presigned PUT URL, and the reason
    is the size cap. A presigned PUT cannot enforce one: ``ContentLength`` is
    not carried in the signature, so a client that registered a 1 KB photo could
    PUT two gigabytes and storage would accept it. A POST policy carries a
    ``content-length-range`` condition that storage itself enforces, which is
    the difference between a documented limit and a real one.

    Returns the form target and the exact fields that must accompany the upload;
    the caller sends them verbatim rather than reconstructing any of them.
    """

    settings = get_settings()
    client = _client(settings, endpoint=settings.media_s3_public_endpoint)
    try:
        presigned = client.generate_presigned_post(
            Bucket=settings.media_bucket_private,
            Key=object_key(access_token),
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


def measure_object(access_token: str) -> dict[str, object] | None:
    """The size and type storage actually recorded, or ``None`` if absent.

    This is what makes "limits are enforced twice" true. Finalization used to
    re-validate the numbers the *client* sent, which is the same trust boundary
    as registration — checking a client's claim twice is still checking a claim.
    Reading them back from storage checks the bytes.
    """

    settings = get_settings()
    client = _client(settings)
    try:
        head = client.head_object(
            Bucket=settings.media_bucket_private, Key=object_key(access_token)
        )
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
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
    }


def presigned_read_url(access_token: str, *, ttl_seconds: int) -> str:
    """A short-lived GET URL for an asset the caller has been granted.

    Authorization happened before this is called. This function only turns an
    already-made decision into something a browser can fetch, and it must never
    be reachable from a path that has not made that decision.
    """

    settings = get_settings()
    return _presign(
        "get_object",
        {"Bucket": settings.media_bucket_private, "Key": object_key(access_token)},
        ttl_seconds,
    )


def object_exists(access_token: str) -> bool:
    """Whether any bytes landed at all.

    A missing object means the member abandoned the upload, which must not be
    recorded as a finished asset.
    """

    return measure_object(access_token) is not None
