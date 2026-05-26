from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ChannelCandidate:
    channel_id: str
    title: str
    handle: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class Video:
    video_id: str
    channel_id: str
    channel_name: str
    title: str
    url: str
    published_at: datetime
    duration_seconds: int | None = None

    @property
    def share_url(self) -> str:
        return f"https://youtu.be/{self.video_id}"


@dataclass(frozen=True)
class VideoListContext:
    purpose: str
    heading: str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_date(dt: datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def fmt_duration(seconds: int | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    parts.append(f"{remaining_seconds}s")
    return "".join(parts)
