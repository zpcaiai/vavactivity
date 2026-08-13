from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from vav.modules.profile_media.domain import MediaKind, ProfileMediaRuleError
from vav.modules.profile_media.inspection import inspect_media, inspect_photo, inspect_video


def _jpeg(*, exif: bool = False) -> bytes:
    image = Image.new("RGB", (640, 480), color=(30, 80, 120))
    output = io.BytesIO()
    metadata = Image.Exif()
    if exif:
        metadata[0x010E] = "private profile description"
        metadata[0x013B] = "member name"
    image.save(output, format="JPEG", exif=metadata)
    return output.getvalue()


def test_photo_bytes_are_decoded_and_reencoded_without_exif() -> None:
    inspected = inspect_photo(_jpeg(exif=True), "image/jpeg")

    assert inspected.mime_type == "image/jpeg"
    assert inspected.byte_size == len(inspected.content)
    with Image.open(io.BytesIO(inspected.content)) as result:
        assert not result.getexif()
        assert result.size == (640, 480)


def test_a_spoofed_photo_content_type_is_rejected() -> None:
    with pytest.raises(ProfileMediaRuleError) as error:
        inspect_media(
            kind=MediaKind.PHOTO,
            payload=b"this is not an image",
            declared_mime_type="image/jpeg",
        )

    assert error.value.code == "MEDIA_CONTENT_INVALID"


def test_a_photo_above_the_pixel_budget_is_rejected_before_full_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)

    with pytest.raises(ProfileMediaRuleError) as error:
        inspect_photo(_jpeg(), "image/jpeg")

    assert error.value.code == "MEDIA_CONTENT_INVALID"


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg inspection runtime is not installed on this host",
)
def test_video_duration_comes_from_a_decodable_stream_not_the_client(tmp_path: Path) -> None:
    video = tmp_path / "short.mp4"
    result = subprocess.run(
        [
            str(shutil.which("ffmpeg")),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x120:d=3.4",
            "-c:v",
            "mpeg4",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(video),
        ],
        check=False,
        timeout=20,
    )
    assert result.returncode == 0

    inspected = inspect_video(video.read_bytes(), "video/mp4")

    assert inspected.mime_type == "video/mp4"
    assert inspected.duration_seconds is not None
    assert 3.3 <= inspected.duration_seconds <= 3.6


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg inspection runtime is not installed on this host",
)
def test_long_audio_track_cannot_hide_behind_a_short_video_track(tmp_path: Path) -> None:
    video = tmp_path / "short-picture-long-audio.mp4"
    result = subprocess.run(
        [
            str(shutil.which("ffmpeg")),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x120:d=3.4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=40",
            "-c:v",
            "mpeg4",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(video),
        ],
        check=False,
        timeout=30,
    )
    assert result.returncode == 0

    with pytest.raises(ProfileMediaRuleError) as error:
        inspect_video(video.read_bytes(), "video/mp4")

    assert error.value.code == "MEDIA_VIDEO_TOO_LONG"
    assert float(error.value.details["duration_seconds"]) >= 39.9


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg inspection runtime is not installed on this host",
)
def test_multiple_video_streams_cannot_change_the_sanitized_duration(tmp_path: Path) -> None:
    video = tmp_path / "two-video-streams.mp4"
    result = subprocess.run(
        [
            str(shutil.which("ffmpeg")),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x120:d=1.0",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=160x120:d=3.4",
            "-map",
            "0:v",
            "-map",
            "1:v",
            "-c:v",
            "mpeg4",
            "-y",
            str(video),
        ],
        check=False,
        timeout=30,
    )
    assert result.returncode == 0

    with pytest.raises(ProfileMediaRuleError) as error:
        inspect_video(video.read_bytes(), "video/mp4")

    assert error.value.code == "MEDIA_VIDEO_DIMENSIONS_INVALID"


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg inspection runtime is not installed on this host",
)
def test_video_metadata_is_removed_from_the_final_container(tmp_path: Path) -> None:
    source = tmp_path / "private-metadata.mp4"
    result = subprocess.run(
        [
            str(shutil.which("ffmpeg")),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x120:d=3.4",
            "-metadata",
            "title=SECRET_GLOBAL_TITLE",
            "-metadata",
            "location=SECRET_GPS_LOCATION",
            "-metadata:s:v:0",
            "title=SECRET_STREAM_TITLE",
            "-c:v",
            "mpeg4",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(source),
        ],
        check=False,
        timeout=20,
    )
    assert result.returncode == 0

    inspected = inspect_video(source.read_bytes(), "video/mp4")
    sanitized = tmp_path / "sanitized.mp4"
    sanitized.write_bytes(inspected.content)
    probe = subprocess.run(
        [
            str(shutil.which("ffprobe")),
            "-v",
            "error",
            "-show_entries",
            "format_tags:stream_tags",
            "-of",
            "json",
            str(sanitized),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert probe.returncode == 0
    assert "SECRET_" not in probe.stdout
    assert inspected.duration_seconds is not None
    assert 3.3 <= inspected.duration_seconds <= 3.6


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg inspection runtime is not installed on this host",
)
def test_container_metadata_without_a_decodable_frame_is_rejected() -> None:
    # The old parser accepted hand-built ftyp/moov/handler metadata without
    # proving that the file had media samples. FFmpeg must reject these bytes.
    fake = b"\x00\x00\x00\x14ftypisom\x00\x00\x02\x00isom" + b"\x00\x00\x00\x08moov"

    with pytest.raises(ProfileMediaRuleError) as error:
        inspect_video(fake, "video/mp4")

    assert error.value.code == "MEDIA_VIDEO_INVALID"
