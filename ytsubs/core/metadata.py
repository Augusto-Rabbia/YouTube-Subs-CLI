from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

from .models import Video
from .store import Store
from .util import debug_log
from .youtube import YouTubeClient


class VideoMetadataService:
    """Enrich displayed videos with reusable, remotely resolved metadata."""

    DURATION_RETRY_AFTER = timedelta(hours=6)
    MAX_WORKERS = 6

    def __init__(self, store: Store, youtube: YouTubeClient):
        self.store = store
        self.youtube = youtube

    def with_durations(self, videos: list[Video]) -> list[Video]:
        pending = list(
            dict.fromkeys(
                video.video_id
                for video in videos
                if video.duration_seconds is None
                and self.store.needs_video_duration_fetch(video.video_id, self.DURATION_RETRY_AFTER)
            )
        )
        resolved: dict[str, int | None] = {}
        if pending:
            debug_log(1, f"Resolving durations for {len(pending)} displayed videos")
            workers = min(self.MAX_WORKERS, len(pending))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                for video_id, duration in executor.map(self._fetch_duration, pending):
                    self.store.set_video_duration(video_id, duration)
                    resolved[video_id] = duration

        return [
            replace(video, duration_seconds=resolved.get(video.video_id, video.duration_seconds))
            for video in videos
        ]

    def _fetch_duration(self, video_id: str) -> tuple[str, int | None]:
        try:
            return video_id, self.youtube.fetch_video_duration(video_id)
        except Exception as exc:
            debug_log(1, f"Could not resolve duration for {video_id}: {exc}")
            return video_id, None
