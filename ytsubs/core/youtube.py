from __future__ import annotations

from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .models import ChannelCandidate, Video, parse_datetime
from .paths import CACHE_DIR
from .util import CHANNEL_ID_RE, extract_channel_id, extract_video_id, debug_log

try:
    import yt_dlp
except Exception:  # pragma: no cover - import error is handled at runtime
    yt_dlp = None

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def ydl_opts() -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "nocheckcertificate": False,
        "cachedir": str(CACHE_DIR / "yt-dlp"),
        "extractor_args": {
            "youtubetab": {
                "approximate_date": [""]
            }
        }
    }


class YouTubeClient:
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }

    def resolve_channel(self, spec: str) -> ChannelCandidate:
        spec = spec.strip()
        debug_log(1, f"Resolving channel with input: {spec!r}")
        channel_id = extract_channel_id(spec)
        if channel_id:
            debug_log(2, f"Extracted channel ID directly: {channel_id}")
            return self._candidate_from_channel_id(channel_id)

        if yt_dlp is None:
            raise RuntimeError("yt-dlp is not installed; cannot resolve handles or searches")

        url = self._normalize_channel_url(spec)
        debug_log(2, f"Normalized channel URL for yt-dlp: {url}")

        if "/@" in url:
            debug_log(1, f"Attempting fast-path HTML resolution for handle URL: {url}")
            try:
                import re
                html_bytes = self._fetch_bytes(url)
                html = html_bytes.decode("utf-8", errors="ignore")
                
                # Regex patterns to find channel ID
                patterns = [
                    r"channel_id=(UC[A-Za-z0-9_-]{22})",
                    r"itemprop=\"channelId\" content=\"(UC[A-Za-z0-9_-]{22})\"",
                    r"itemprop=\"identifier\" content=\"(UC[A-Za-z0-9_-]{22})\"",
                    r"\"channelId\":\"(UC[A-Za-z0-9_-]{22})\""
                ]
                
                found_id = None
                for pat in patterns:
                    m = re.search(pat, html)
                    if m:
                        found_id = m.group(1)
                        debug_log(2, f"Fast-path matched channel ID: {found_id} using pattern {pat!r}")
                        break
                        
                if found_id:
                    # Extract channel title
                    title = None
                    m_title = re.search(r"property=\"og:title\" content=\"([^\"]+)\"", html)
                    if m_title:
                        title = m_title.group(1)
                    else:
                        m_title = re.search(r"<title>([^<]+)</title>", html)
                        if m_title:
                            title = m_title.group(1)
                            if title.endswith(" - YouTube"):
                                title = title[:-10]
                    
                    if not title:
                        title = found_id
                        
                    handle = self._handle_from_url(url)
                    debug_log(1, f"Fast-path resolved channel: {title} ({found_id})")
                    return ChannelCandidate(
                        channel_id=found_id,
                        title=title,
                        handle=handle,
                        url=url
                    )
            except Exception as e:
                debug_log(1, f"Fast-path HTML resolution failed: {e}. Falling back to yt-dlp.")

        debug_log(1, f"Invoking yt-dlp to extract channel info for {url}")
        with yt_dlp.YoutubeDL(ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        candidate = self._candidate_from_ydl_info(info, fallback_url=url)
        if not candidate:
            debug_log(1, f"Failed to resolve channel for {spec}")
            raise ValueError(f"Could not resolve channel: {spec}")
        debug_log(1, f"Resolved channel: {candidate.title} ({candidate.channel_id})")
        return candidate

    def search_channels(self, query: str, limit: int = 10) -> list[ChannelCandidate]:
        if yt_dlp is None:
            raise RuntimeError("yt-dlp is not installed; cannot search channels")

        query = query.strip()
        if not query:
            return []

        debug_log(1, f"Searching channels for query: {query!r} (limit={limit})")
        candidates: dict[str, ChannelCandidate] = {}
        search_url = f"ytsearch{max(limit * 4, 10)}:{query}"
        debug_log(2, f"Search URL: {search_url}")
        with yt_dlp.YoutubeDL(ydl_opts()) as ydl:
            info = ydl.extract_info(search_url, download=False)

        entries = (info or {}).get("entries") or []
        debug_log(2, f"Found {len(entries)} raw search entries from yt-dlp")
        for entry in entries:
            if not entry:
                continue
            channel_id = (
                entry.get("channel_id")
                or entry.get("uploader_id")
                or extract_channel_id(entry.get("channel_url") or "")
                or extract_channel_id(entry.get("uploader_url") or "")
            )
            if not channel_id or not CHANNEL_ID_RE.match(channel_id):
                continue
            title = entry.get("channel") or entry.get("uploader") or entry.get("creator") or channel_id
            url = entry.get("channel_url") or entry.get("uploader_url") or f"https://www.youtube.com/channel/{channel_id}"
            handle = self._handle_from_url(url)
            if channel_id not in candidates:
                debug_log(2, f"Found candidate: {title} ({channel_id})")
                candidates[channel_id] = ChannelCandidate(channel_id, title, handle, url)
            if len(candidates) >= limit:
                break

        debug_log(1, f"Search returned {len(candidates)} channels")
        return list(candidates.values())

    def fetch_channel_feed(self, channel_id: str) -> list[Video]:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        debug_log(1, f"Fetching RSS feed for channel: {channel_id}")
        try:
            xml_bytes = self._fetch_bytes(url)
            root = ET.fromstring(xml_bytes)
            channel_name = self._text(root, "atom:title") or channel_id
            videos: list[Video] = []
            for entry in root.findall("atom:entry", self.ns):
                video_id = self._text(entry, "yt:videoId") or extract_video_id(self._entry_link(entry))
                if not video_id:
                    continue
                author = entry.find("atom:author", self.ns)
                author_name = self._text(author, "atom:name") if author is not None else None
                published_raw = self._text(entry, "atom:published") or self._text(entry, "atom:updated")
                published_at = self._parse_feed_published_at(published_raw)
                if published_at is None:
                    debug_log(1, f"Skipping RSS video {video_id}: publication date is unavailable or invalid")
                    continue
                videos.append(
                    Video(
                        video_id=video_id,
                        channel_id=channel_id,
                        channel_name=author_name or channel_name,
                        title=self._text(entry, "atom:title") or "Untitled",
                        url=self._entry_link(entry) or f"https://www.youtube.com/watch?v={video_id}",
                        published_at=published_at,
                    )
                )
            debug_log(2, f"Parsed {len(videos)} videos from RSS feed for channel {channel_name}")
            return videos
        except Exception as rss_exc:
            debug_log(1, f"RSS feed failed for {channel_id}: {rss_exc}")
            if yt_dlp is None:
                raise RuntimeError(f"RSS feed failed ({rss_exc}) and yt-dlp is not installed.") from rss_exc

            channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"
            debug_log(1, f"Falling back to yt-dlp flat extraction for channel: {channel_id}")
            try:
                opts = ydl_opts()
                opts["playlist_items"] = "1-30"
                opts["playlistend"] = 30
                debug_log(2, f"Running yt-dlp flat-extraction on {channel_url}")
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(channel_url, download=False)
                if not info:
                    raise RuntimeError("No info returned by yt-dlp")

                channel_name = info.get("title") or info.get("uploader") or channel_id
                entries = info.get("entries") or []
                videos: list[Video] = []
                for entry in entries:
                    if not entry:
                        continue
                    video_id = entry.get("id")
                    if not video_id:
                        continue

                    title = entry.get("title") or "Untitled"
                    video_url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
                    published_at = self._parse_ydl_published_at(entry)
                    if published_at is None:
                        debug_log(1, f"Skipping fallback video {video_id}: publication date is unavailable")
                        continue

                    videos.append(
                        Video(
                            video_id=video_id,
                            channel_id=channel_id,
                            channel_name=entry.get("uploader") or channel_name,
                            title=title,
                            url=video_url,
                            published_at=published_at,
                            duration_seconds=self._parse_duration_seconds(entry),
                        )
                    )
                debug_log(2, f"Parsed {len(videos)} videos from yt-dlp fallback for channel {channel_name}")
                return videos
            except Exception as ytdl_exc:
                debug_log(1, f"yt-dlp fallback also failed for {channel_id}: {ytdl_exc}")
                raise RuntimeError(f"Both RSS feed failed ({rss_exc}) and yt-dlp flat extraction failed ({ytdl_exc}).") from ytdl_exc

    def fetch_video_duration(self, video_id: str) -> int | None:
        if yt_dlp is None:
            raise RuntimeError("yt-dlp is not installed; cannot resolve video duration")

        opts = ydl_opts()
        opts["extract_flat"] = False
        opts["noplaylist"] = True
        url = f"https://youtu.be/{video_id}"
        debug_log(2, f"Resolving duration for video {video_id}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return self._parse_duration_seconds(info or {})

    def _candidate_from_channel_id(self, channel_id: str) -> ChannelCandidate:
        debug_log(2, f"Generating candidate info for channel ID: {channel_id}")
        try:
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            xml_bytes = self._fetch_bytes(url)
            root = ET.fromstring(xml_bytes)
            title = self._text(root, "atom:title") or channel_id
        except Exception as exc:
            debug_log(2, f"Failed to fetch candidate name from RSS: {exc}")
            title = channel_id
        return ChannelCandidate(
            channel_id=channel_id,
            title=title,
            handle=None,
            url=f"https://www.youtube.com/channel/{channel_id}",
        )

    @classmethod
    def _text(cls, element: ET.Element | None, path: str) -> str | None:
        if element is None:
            return None
        found = element.find(path, cls.ns)
        if found is None or found.text is None:
            return None
        text = found.text.strip()
        return text or None

    @classmethod
    def _entry_link(cls, entry: ET.Element) -> str:
        for link in entry.findall("atom:link", cls.ns):
            href = link.attrib.get("href")
            rel = link.attrib.get("rel")
            if href and (rel == "alternate" or rel is None):
                return href
        return ""

    @staticmethod
    def _parse_feed_published_at(raw_value: str | None) -> datetime | None:
        if not raw_value:
            return None
        try:
            return parse_datetime(raw_value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_ydl_published_at(entry: dict) -> datetime | None:
        for key in ("timestamp", "release_timestamp"):
            timestamp = entry.get(key)
            if timestamp is None:
                continue
            try:
                return datetime.fromtimestamp(float(timestamp), timezone.utc)
            except (OSError, OverflowError, TypeError, ValueError):
                continue

        for key in ("upload_date", "release_date"):
            raw_date = entry.get(key)
            if not isinstance(raw_date, str) or len(raw_date) != 8:
                continue
            try:
                return datetime.strptime(raw_date, "%Y%m%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_duration_seconds(info: dict) -> int | None:
        duration = info.get("duration")
        if duration is None:
            return None
        try:
            return max(0, int(round(float(duration))))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fetch_bytes(url: str) -> bytes:
        debug_log(2, f"HTTP GET Request: {url}")
        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=20) as response:
                res_bytes = response.read()
                debug_log(2, f"HTTP GET Success: {url} ({len(res_bytes)} bytes)")
                return res_bytes
        except HTTPError as exc:
            debug_log(2, f"HTTP GET Failure: {url} (HTTP {exc.code})")
            raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
        except URLError as exc:
            debug_log(2, f"HTTP GET Failure: {url} (URLError: {exc.reason})")
            raise RuntimeError(f"network error for {url}: {exc.reason}") from exc

    @staticmethod
    def _candidate_from_ydl_info(info: dict | None, fallback_url: str) -> ChannelCandidate | None:
        if not info:
            return None
        channel_id = info.get("channel_id") or info.get("uploader_id") or info.get("id")
        if not channel_id or not CHANNEL_ID_RE.match(channel_id):
            for entry in info.get("entries") or []:
                if not entry:
                    continue
                channel_id = entry.get("channel_id") or entry.get("uploader_id")
                if channel_id and CHANNEL_ID_RE.match(channel_id):
                    break
        if not channel_id or not CHANNEL_ID_RE.match(channel_id):
            return None

        title = info.get("channel") or info.get("uploader") or info.get("title") or channel_id
        url = info.get("channel_url") or info.get("uploader_url") or info.get("webpage_url") or fallback_url
        handle = YouTubeClient._handle_from_url(url)
        return ChannelCandidate(channel_id=channel_id, title=title, handle=handle, url=url)

    @staticmethod
    def _handle_from_url(url: str) -> str | None:
        if not url:
            return None
        parsed = urlparse(url if "://" in url else "https://" + url)
        parts = [p for p in parsed.path.split("/") if p]
        for part in parts:
            if part.startswith("@"):
                return part
        return None

    @staticmethod
    def _normalize_channel_url(spec: str) -> str:
        spec = spec.strip()
        if spec.startswith("http://") or spec.startswith("https://"):
            return spec
        if spec.startswith("@"):
            return f"https://www.youtube.com/{spec}"
        if spec.startswith("youtube.com/") or spec.startswith("www.youtube.com/"):
            return "https://" + spec
        raise ValueError("not a handle, URL, or channel ID")
