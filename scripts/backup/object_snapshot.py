#!/usr/bin/env python3
"""Create a deterministic tar snapshot of configured S3-compatible buckets."""

from __future__ import annotations

import argparse
import json
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

import boto3

from vav.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=settings.media_s3_endpoint,
        aws_access_key_id=settings.media_s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.media_s3_secret_key.get_secret_value(),
        region_name=settings.media_s3_region,
    )
    records: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="vav-object-backup-") as temporary:
        root = Path(temporary)
        for bucket in (settings.media_bucket_private, settings.media_bucket_public):
            token: str | None = None
            while True:
                request = {"Bucket": bucket}
                if token:
                    request["ContinuationToken"] = token
                response = client.list_objects_v2(**request)
                for item in response.get("Contents", []):
                    key = str(item["Key"])
                    pure = PurePosixPath(key)
                    if pure.is_absolute() or ".." in pure.parts:
                        raise ValueError(f"unsafe object key: {key}")
                    target = root / bucket / Path(*pure.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    client.download_file(bucket, key, str(target))
                    records.append(
                        {
                            "bucket": bucket,
                            "key": key,
                            "size": int(item["Size"]),
                            "etag": str(item.get("ETag", "")).strip('"'),
                        }
                    )
                if not response.get("IsTruncated"):
                    break
                token = str(response["NextContinuationToken"])
        (root / "object-manifest.json").write_text(
            json.dumps({"objects": records}, indent=2, sort_keys=True), encoding="utf-8"
        )
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(args.destination, "w") as archive:
            for path in sorted(root.rglob("*")):
                archive.add(path, arcname=path.relative_to(root), recursive=False)
    print(f"object snapshot complete: {len(records)} objects")


if __name__ == "__main__":
    main()
