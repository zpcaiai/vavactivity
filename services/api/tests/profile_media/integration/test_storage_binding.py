"""The profile-media storage binding must actually resolve (PROFILE-001).

These tests exist because the module they cover was written after discovering
that ``private_media_path()`` — the only URL the upload and read paths returned
— is served by nothing in this repository. An upload had nowhere to send its
bytes and an ``<img src>`` pointing at it would 404, while every unit test still
passed, because the unit tests only ever checked the *shape* of that string.

So the assertions here are deliberately about reachability and about the
guarantees that survive the move to object storage: the key is unguessable, the
signed URL constrains what may be uploaded, and a missing object is detectable.
"""

from __future__ import annotations

import base64
import json
from uuid import uuid4

import boto3
import pytest
from moto import mock_aws

from vav.common.exceptions import VavError
from vav.modules.profile_media import storage
from vav.modules.profile_media.domain import derive_asset_token

BUCKET = "vav-private"


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch):
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        client.create_bucket(Bucket=BUCKET)

        class _Secret:
            def __init__(self, value: str) -> None:
                self._value = value

            def get_secret_value(self) -> str:
                return self._value

        class _Settings:
            media_s3_endpoint = None
            media_s3_public_endpoint = None
            media_s3_region = "us-east-1"
            media_s3_access_key = _Secret("test")
            media_s3_secret_key = _Secret("test")
            media_bucket_private = BUCKET

        monkeypatch.setattr(storage, "get_settings", lambda: _Settings())
        yield client


def test_object_key_is_derived_from_the_token_and_nothing_else() -> None:
    """A key built from an asset id or an owner id makes the bucket walkable."""

    asset_id = uuid4()
    owner_id = uuid4()
    token = derive_asset_token(asset_id, secret="a-server-secret")

    key = storage.object_key(token)

    assert key == f"profile-media/{token}"
    assert str(asset_id) not in key
    assert str(owner_id) not in key


def test_an_empty_token_is_refused_rather_than_writing_to_the_prefix_root() -> None:
    with pytest.raises(VavError):
        storage.object_key("   ")


def test_an_upload_round_trips_and_is_then_measurable_and_readable(s3) -> None:
    token = derive_asset_token(uuid4(), secret="a-server-secret")
    payload = b"\xff\xd8\xff\xe0 fake jpeg bytes"

    # Before the upload the object genuinely does not exist — this is the check
    # that stops an abandoned registration becoming an "active" asset.
    assert storage.object_exists(token) is False
    assert storage.measure_object(token) is None

    upload = storage.presigned_upload(token, mime_type="image/jpeg", max_bytes=10 * 1024 * 1024)
    assert upload["method"] == "POST"
    assert storage.object_key(token) == upload["fields"]["key"]

    s3.put_object(
        Bucket=BUCKET, Key=storage.object_key(token), Body=payload, ContentType="image/jpeg"
    )

    assert storage.object_exists(token) is True

    # Measured from storage, which is what makes the finalize check meaningful.
    measured = storage.measure_object(token)
    assert measured == {"byte_size": len(payload), "mime_type": "image/jpeg"}

    read_url = storage.presigned_read_url(token, ttl_seconds=300)
    assert storage.object_key(token) in read_url

    stored = s3.get_object(Bucket=BUCKET, Key=storage.object_key(token))["Body"].read()
    assert stored == payload


def test_the_upload_policy_carries_a_size_ceiling_storage_enforces(s3) -> None:
    """A presigned PUT cannot cap size; a POST policy can, so this uses one.

    Without the condition a member who registered a 1 KB photo could upload two
    gigabytes and storage would accept it — the documented limit would be a
    comment rather than a control.
    """

    token = derive_asset_token(uuid4(), secret="a-server-secret")

    upload = storage.presigned_upload(token, mime_type="image/png", max_bytes=1024)

    policy = json.loads(base64.b64decode(str(upload["fields"]["policy"])))
    conditions = policy["conditions"]
    assert ["content-length-range", 1, 1024] in conditions
    assert {"Content-Type": "image/png"} in conditions
    assert upload["max_bytes"] == 1024


def test_a_photo_and_a_video_get_different_ceilings(s3) -> None:
    photo = storage.presigned_upload(
        derive_asset_token(uuid4(), secret="s"), mime_type="image/png", max_bytes=10 * 1024 * 1024
    )
    video = storage.presigned_upload(
        derive_asset_token(uuid4(), secret="s"), mime_type="video/mp4", max_bytes=100 * 1024 * 1024
    )

    assert photo["max_bytes"] < video["max_bytes"]


def test_read_urls_carry_the_requested_lifetime(s3) -> None:
    """SigV4 is pinned precisely so this is expressible and checkable."""

    token = derive_asset_token(uuid4(), secret="a-server-secret")

    short = storage.presigned_read_url(token, ttl_seconds=30)
    long = storage.presigned_read_url(token, ttl_seconds=900)

    assert "X-Amz-Expires=30" in short
    assert "X-Amz-Expires=900" in long


def test_storage_failure_is_not_reported_as_a_missing_asset(
    monkeypatch: pytest.MonkeyPatch, s3
) -> None:
    """503 and 404 mean different things and must not be interchangeable.

    "That asset does not exist" is the vocabulary reserved for a permission
    decision, and a member must not be told their photo was deleted because a
    bucket was briefly unreachable.
    """

    token = derive_asset_token(uuid4(), secret="a-server-secret")

    def explode(*args: object, **kwargs: object) -> None:
        from botocore.exceptions import EndpointConnectionError

        raise EndpointConnectionError(endpoint_url="http://storage.invalid")

    monkeypatch.setattr(
        storage, "_client", lambda *a, **k: type("C", (), {"head_object": explode})()
    )

    with pytest.raises(VavError) as error:
        storage.object_exists(token)

    assert error.value.code == "MEDIA_STORAGE_UNAVAILABLE"
    assert error.value.status_code == 503
