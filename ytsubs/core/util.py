from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
WATCH_URL_ID_RE = re.compile(r"(?:youtu\.be/|v=|/shorts/|/embed/)([0-9A-Za-z_-]{11})")

_DEBUG_LEVEL = 0

def set_debug_level(level: int) -> None:
    global _DEBUG_LEVEL
    _DEBUG_LEVEL = level

def get_debug_level() -> int:
    return _DEBUG_LEVEL

def debug_log(level: int, msg: str) -> None:
    if _DEBUG_LEVEL >= level:
        prefix = f"\033[36m[DEBUG-{level}]\033[0m"
        print(f"{prefix} {msg}")
def extract_video_id(value: str) -> str | None:
    value = value.strip()
    if re.fullmatch(r"[0-9A-Za-z_-]{11}", value):
        return value
    match = WATCH_URL_ID_RE.search(value)
    if match:
        return match.group(1)
    return None


def parse_days_token(token: str) -> int | None:
    token = token.strip().lower()
    if not token.endswith("d"):
        return None
    number = token[:-1]
    if not number.isdigit():
        return None
    days = int(number)
    if days <= 0:
        raise ValueError("days must be positive")
    return days


def extract_channel_id(spec: str) -> str | None:
    spec = spec.strip()
    if CHANNEL_ID_RE.match(spec):
        return spec
    if not spec:
        return None
    parsed = urlparse(spec if "://" in spec else "https://" + spec)
    parts = [p for p in parsed.path.split("/") if p]
    for i, part in enumerate(parts):
        if part == "channel" and i + 1 < len(parts) and CHANNEL_ID_RE.match(parts[i + 1]):
            return parts[i + 1]
    qs = parse_qs(parsed.query)
    for key in ("channel_id", "channelId"):
        if key in qs and qs[key] and CHANNEL_ID_RE.match(qs[key][0]):
            return qs[key][0]
    return None
