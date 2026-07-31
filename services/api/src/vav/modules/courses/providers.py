from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.models.courses import CourseVideoAsset


@dataclass(frozen=True)
class PlaybackManifest:
    provider: str
    playback_type: str
    asset_reference: str
    duration_seconds: int | None
    download_enabled: bool


class CourseVideoProvider(Protocol):
    async def create_playback_manifest(self, video: CourseVideoAsset) -> PlaybackManifest: ...

    async def processing_status(self, video: CourseVideoAsset) -> str: ...

    async def revoke_playback_session(self, playback_session_id: str) -> None: ...


class FakePrivateVideoProvider:
    async def create_playback_manifest(self, video: CourseVideoAsset) -> PlaybackManifest:
        return PlaybackManifest(
            provider="fake_private",
            playback_type=video.playback_format or "hls",
            asset_reference=f"private-asset:{video.id}",
            duration_seconds=video.duration_seconds,
            download_enabled=False,
        )

    async def processing_status(self, video: CourseVideoAsset) -> str:
        return video.processing_status

    async def revoke_playback_session(self, playback_session_id: str) -> None:
        return None


def get_course_video_provider() -> CourseVideoProvider:
    provider = get_settings().course_video_provider
    if provider == "fake_private":
        return FakePrivateVideoProvider()
    raise VavError(
        "COURSE_VIDEO_PROVIDER_NOT_CONFIGURED",
        "The configured private video provider adapter is unavailable.",
        status_code=503,
    )
