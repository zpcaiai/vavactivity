"""Server-side inspection and normalization for private profile media.

Object metadata is supplied by the uploader and is therefore not evidence of a
file's type or duration. Photos are decoded and re-encoded without metadata;
videos are probed and an actual frame is decoded by FFmpeg with network
protocols disabled. An object does not become active until this module has
accepted the bytes.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pillow_heif  # type: ignore[import-untyped]
from PIL import Image, ImageOps, UnidentifiedImageError

from vav.modules.profile_media.domain import (
    MAX_VIDEO_DURATION_SECONDS,
    MediaKind,
    ProfileMediaRuleError,
)

pillow_heif.register_heif_opener()

MAX_IMAGE_PIXELS = 40_000_000
MAX_VIDEO_FRAME_PIXELS = 16_777_216
MAX_VIDEO_STREAMS = 1
MAX_AUDIO_STREAMS = 2
MAX_MEDIA_STREAMS = 4
MAX_TOTAL_VIDEO_FRAME_PIXELS = 20_000_000
# Pillow's own decompression-bomb guard runs while opening the file, before the
# explicit dimension check below. Keep both: the library guard blocks hostile
# allocations, while our lower product limit gives a stable domain error.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

_IMAGE_FORMAT_TO_MIME: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "HEIF": "image/heic",
    "HEIC": "image/heic",
}


@dataclass(frozen=True)
class InspectedMedia:
    content: bytes
    mime_type: str
    byte_size: int
    checksum_sha256: str
    duration_seconds: float | None


def _run_media_tool(arguments: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ProfileMediaRuleError(
            "MEDIA_VIDEO_INSPECTION_TIMEOUT", "The video could not be inspected in time."
        ) from error


def _duration(probe: dict[str, Any]) -> float:
    """Return the longest declared container/stream duration.

    A short video track does not make a container short: a longer audio track
    still consumes download, decode and playback time.  Taking the first video
    stream used to accept a 3.4-second picture track paired with 40 seconds of
    audio, so every stream and the container duration participate in the cap.
    """

    candidates = [probe.get("format", {}).get("duration")]
    candidates.extend(stream.get("duration") for stream in probe.get("streams", []))
    measured: list[float] = []
    for candidate in candidates:
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            measured.append(value)
    if measured:
        return max(measured)
    raise ProfileMediaRuleError(
        "MEDIA_VIDEO_DURATION_UNKNOWN", "The video duration could not be measured."
    )


def inspect_video(payload: bytes, declared_mime_type: str) -> InspectedMedia:
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if ffprobe is None or ffmpeg is None:
        # Fail closed: accepting a video when the inspection runtime vanished is
        # precisely how client-declared duration becomes authoritative again.
        raise ProfileMediaRuleError(
            "MEDIA_VIDEO_INSPECTION_UNAVAILABLE",
            "Video inspection is temporarily unavailable.",
        )
    suffix = ".mov" if declared_mime_type.strip().lower() == "video/quicktime" else ".mp4"
    with tempfile.TemporaryDirectory(prefix="vav-profile-media-") as directory:
        path = Path(directory) / f"upload{suffix}"
        path.write_bytes(payload)
        probe_result = _run_media_tool(
            [
                ffprobe,
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-probesize",
                "10485760",
                "-analyzeduration",
                "10000000",
                "-show_entries",
                "format=format_name,duration:format_tags=major_brand:"
                "stream=codec_type,duration,width,height",
                "-of",
                "json",
                str(path),
            ],
            timeout=15,
        )
        if probe_result.returncode != 0:
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_INVALID", "The uploaded file is not a decodable video."
            )
        try:
            probe: dict[str, Any] = json.loads(probe_result.stdout)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_INVALID", "The video inspection result is invalid."
            ) from error
        video_streams = [
            stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"
        ]
        if not video_streams:
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_INVALID", "The uploaded container has no video track."
            )
        audio_streams = [
            stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"
        ]
        if (
            len(audio_streams) > MAX_AUDIO_STREAMS
            or len(video_streams) + len(audio_streams) > MAX_MEDIA_STREAMS
        ):
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_STREAMS_INVALID",
                "The video contains too many media streams.",
                details={
                    "video_streams": len(video_streams),
                    "audio_streams": len(audio_streams),
                    "max_audio_streams": MAX_AUDIO_STREAMS,
                    "max_media_streams": MAX_MEDIA_STREAMS,
                },
            )
        dimensions = [
            (int(stream.get("width") or 0), int(stream.get("height") or 0))
            for stream in video_streams
        ]
        total_pixels = sum(width * height for width, height in dimensions)
        invalid_dimensions = any(
            width < 1 or height < 1 or width * height > MAX_VIDEO_FRAME_PIXELS
            for width, height in dimensions
        )
        if (
            len(video_streams) > MAX_VIDEO_STREAMS
            or invalid_dimensions
            or total_pixels > MAX_TOTAL_VIDEO_FRAME_PIXELS
        ):
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_DIMENSIONS_INVALID",
                "The video dimensions are outside the permitted range.",
                details={
                    "dimensions": dimensions,
                    "stream_count": len(video_streams),
                    "max_streams": MAX_VIDEO_STREAMS,
                    "max_pixels_per_stream": MAX_VIDEO_FRAME_PIXELS,
                    "max_total_pixels": MAX_TOTAL_VIDEO_FRAME_PIXELS,
                },
            )
        formats = {
            item.strip() for item in str(probe.get("format", {}).get("format_name", "")).split(",")
        }
        major_brand = str(probe.get("format", {}).get("tags", {}).get("major_brand", ""))
        is_quicktime = major_brand.strip().lower() == "qt"
        detected_mime = "video/quicktime" if is_quicktime else "video/mp4"
        if not formats.intersection({"mov", "mp4", "m4v", "3gp", "3g2", "mj2"}):
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_INVALID", "The video container type is unsupported."
            )
        if declared_mime_type.strip().lower() != detected_mime:
            raise ProfileMediaRuleError(
                "MEDIA_MIME_MISMATCH",
                "The video bytes do not match the declared media type.",
                details={"declared": declared_mime_type, "detected": detected_mime},
            )
        duration = _duration(probe)
        if duration > MAX_VIDEO_DURATION_SECONDS:
            # Reject before decoding an attacker-controlled long stream.  The
            # domain repeats this check when it validates the inspected result.
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_TOO_LONG",
                f"The video must be at most {MAX_VIDEO_DURATION_SECONDS} seconds.",
                details={
                    "duration_seconds": duration,
                    "max_duration_seconds": MAX_VIDEO_DURATION_SECONDS,
                },
            )
        # Probe metadata alone is not sufficient. Decode every selected video
        # and audio packet to a null sink so corruption after the first frame is
        # caught.  Duration, dimensions, one decode thread, allocation cap and
        # wall-clock timeout bound the work.
        decode_result = _run_media_tool(
            [
                ffmpeg,
                "-v",
                "error",
                "-xerror",
                "-max_alloc",
                "268435456",
                "-protocol_whitelist",
                "file",
                "-err_detect",
                "explode",
                "-threads",
                "1",
                "-i",
                str(path),
                "-map",
                "0:v",
                "-map",
                "0:a?",
                "-sn",
                "-dn",
                "-f",
                "null",
                "-",
            ],
            timeout=45,
        )
        if decode_result.returncode != 0:
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_INVALID", "The uploaded video stream cannot be decoded completely."
            )
        # Store a sanitized container, not the uploader's original bytes.
        # Global/stream metadata (for example QuickTime GPS, device and title),
        # chapters and extra subtitle/data/attachment tracks are private-data
        # leakage surfaces. Keep one verified video and optional audio stream;
        # copying the already-decoded elementary streams avoids generational
        # loss while rebuilding only the allowed container structure.
        normalized_path = Path(directory) / f"normalized{suffix}"
        normalize_result = _run_media_tool(
            [
                ffmpeg,
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-sn",
                "-dn",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                "-y",
                str(normalized_path),
            ],
            timeout=30,
        )
        if normalize_result.returncode != 0:
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_INVALID", "The video could not be sanitized safely."
            )
        content = normalized_path.read_bytes()
        if not content:
            raise ProfileMediaRuleError("MEDIA_VIDEO_INVALID", "The sanitized video is empty.")
        normalized_probe_result = _run_media_tool(
            [
                ffprobe,
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-show_entries",
                "format=duration:stream=codec_type,duration,width,height",
                "-of",
                "json",
                str(normalized_path),
            ],
            timeout=10,
        )
        if normalized_probe_result.returncode != 0:
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_INVALID", "The sanitized video could not be verified."
            )
        try:
            normalized_probe: dict[str, Any] = json.loads(normalized_probe_result.stdout)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProfileMediaRuleError(
                "MEDIA_VIDEO_INVALID", "The sanitized video inspection result is invalid."
            ) from error
        duration = _duration(normalized_probe)
    return InspectedMedia(
        content=content,
        mime_type=detected_mime,
        byte_size=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        duration_seconds=duration,
    )


def inspect_photo(payload: bytes, declared_mime_type: str) -> InspectedMedia:
    try:
        with Image.open(io.BytesIO(payload)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(payload)) as source:
            detected_format = (source.format or "").upper()
            detected_mime = _IMAGE_FORMAT_TO_MIME.get(detected_format)
            declared = declared_mime_type.strip().lower()
            if detected_mime is None:
                raise ProfileMediaRuleError(
                    "MEDIA_MIME_NOT_ALLOWED", "The decoded image type is not accepted."
                )
            heif_aliases = {"image/heic", "image/heif"}
            if declared != detected_mime and not (
                declared in heif_aliases and detected_mime in heif_aliases
            ):
                raise ProfileMediaRuleError(
                    "MEDIA_MIME_MISMATCH",
                    "The image bytes do not match the declared media type.",
                    details={"declared": declared, "detected": detected_mime},
                )
            width, height = source.size
            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                raise ProfileMediaRuleError(
                    "MEDIA_IMAGE_DIMENSIONS_INVALID",
                    "The image dimensions are outside the permitted range.",
                    details={"width": width, "height": height, "max_pixels": MAX_IMAGE_PIXELS},
                )
            oriented = ImageOps.exif_transpose(source)
            converted = oriented.convert("RGB")
            # Copy pixel data into a fresh image so EXIF/GPS/XMP/ICC metadata is
            # not carried into the private final object.
            sanitized = Image.new("RGB", converted.size)
            sanitized.paste(converted)
            output = io.BytesIO()
            sanitized.save(output, format="JPEG", quality=88, optimize=True)
            content = output.getvalue()
    except ProfileMediaRuleError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError) as error:
        raise ProfileMediaRuleError(
            "MEDIA_CONTENT_INVALID", "The uploaded image cannot be decoded safely."
        ) from error
    return InspectedMedia(
        content=content,
        mime_type="image/jpeg",
        byte_size=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        duration_seconds=None,
    )


def inspect_media(*, kind: MediaKind, payload: bytes, declared_mime_type: str) -> InspectedMedia:
    if kind is MediaKind.PHOTO:
        return inspect_photo(payload, declared_mime_type)
    return inspect_video(payload, declared_mime_type)
