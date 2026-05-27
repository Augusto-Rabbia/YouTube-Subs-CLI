from __future__ import annotations

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from ytsubs.core.addons import AddonRegistry, BaseAddon, SetupPrompts
from ytsubs.core.models import Video, VideoListContext
from ytsubs.core.util import debug_log


class TitleFilterAddon(BaseAddon):
    name = "title-filter"
    description = "Filter out videos by original title regex matching or filter out YouTube Shorts."
    default_enabled = True
    help_details = {
        "title-filter": {
            "summary": "Filter videos by title regex or Shorts.",
            "usage": "title-filter setup|on|off|cfg [help|KEY VALUE]",
            "details": (
                "  - title-filter setup      - Run this addon's guided setup.\n"
                "  - filter add <regex>      - Add a title exclusion pattern.\n"
                "  - filter list             - Show patterns and Shorts filtering status.\n"
                "  - filter cfg filter_shorts <on|off> - Toggle hiding Shorts."
            ),
            "examples": ["title-filter setup", "filter add (?i)reaction|unboxing", "filter cfg filter_shorts on"],
        },
        "filter": {
            "summary": "Filter videos by title regex or Shorts.",
            "usage": "filter add REGEX | rm NUMBER | clear | list | on | off | setup | cfg [help|KEY VALUE]",
            "details": (
                "  - filter setup            - Run the title-filter setup.\n"
                "  - filter add <regex>      - Add a title exclusion pattern.\n"
                "  - filter list             - Show patterns and Shorts filtering status.\n"
                "  - filter cfg filter_shorts <on|off> - Toggle hiding Shorts."
            ),
            "examples": ["filter setup", "filter add (?i)reaction|unboxing", "filter cfg filter_shorts on"],
        },
    }

    def register_commands(self, registry: AddonRegistry) -> None:
        registry.command(
            "filter",
            self.command,
            "filter add REGEX|rm NUMBER|clear|list|on|off|setup|cfg [help|KEY VALUE]",
            addon_name=self.name
        )
        registry.command(
            self.name,
            self.command,
            "title-filter setup|on|off|cfg [help|KEY VALUE]",
            addon_name=self.name,
        )

    def command(self, args: list[str]) -> None:
        if not args:
            enabled = self.store.is_addon_enabled(self.name, self.default_enabled)
            shorts_status = self.store.get_config(self.name, "filter_shorts", "off")
            print(f"Filter Addon: {'enabled' if enabled else 'disabled'}, filter_shorts={shorts_status}")
            return

        action = args[0].lower().strip()
        rest = args[1:]

        if action in {"on", "enable"}:
            self.enable()
        elif action in {"off", "disable"}:
            self.disable()
        elif action == "setup":
            self.run_setup_command(rest)
        elif action == "add":
            pattern = " ".join(rest).strip()
            if not pattern:
                print("Usage: filter add REGEX")
                return
            try:
                import re
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                print(f"Invalid regex: {exc}")
                return
            self.add_title_filter(pattern)
            self.store.set_addon_enabled(self.name, True)
            print("Filter added.")
        elif action in {"list", "ls"}:
            rows = self.list_title_filters()
            shorts_status = self.store.get_config(self.name, "filter_shorts", "off")
            print(f"Shorts filtering: {shorts_status}")
            if not rows:
                print("No title regex filters.")
                return
            print("Title regex filters:")
            for i, row in enumerate(rows, 1):
                status = "on" if row["enabled"] else "off"
                print(f"{i}. [{status}] {row['pattern']}")
        elif action in {"rm", "remove", "del", "delete"}:
            if not rest or not rest[0].isdigit():
                print("Usage: filter rm NUMBER")
                return
            removed = self.remove_title_filter_by_position(int(rest[0]))
            print("Filter removed." if removed else "No filter with that number.")
        elif action == "clear":
            count = self.clear_title_filters()
            print(f"Removed {count} filters.")
        elif action == "cfg":
            if len(args) == 1:
                shorts_status = self.store.get_config(self.name, "filter_shorts", "off")
                print("Filter Configuration:")
                print(f"  filter_shorts = {shorts_status}")
                return
            sub = args[1].lower().strip()
            if sub == "help":
                print("Filter Configuration Help:")
                print("  filter_shorts: on | off (default: off) - toggle hiding YouTube Shorts from feeds")
                return
            if len(args) < 3:
                print("Usage: filter cfg [help|KEY VALUE]")
                return
            val = args[2].lower().strip()
            if sub == "filter_shorts":
                if val not in {"on", "off"}:
                    print("Error: filter_shorts must be 'on' or 'off'")
                    return
                self.store.set_config(self.name, "filter_shorts", val)
                print(f"Set title-filter.filter_shorts = {val}")
            else:
                print(f"Unknown configuration key: {sub}")
        else:
            print("Usage: filter add REGEX|rm NUMBER|clear|list|on|off|setup|cfg [help|KEY VALUE]")

    def setup(self, ui: SetupPrompts) -> None:
        if not self.setup_enabled(ui):
            return
        shorts = self.store.get_config(self.name, "filter_shorts", "off") == "on"
        enabled = ui.ask_yes_no("  Hide YouTube Shorts from video lists?", shorts)
        self.store.set_config(self.name, "filter_shorts", "on" if enabled else "off")
        if not ui.ask_yes_no("  Add title words or regex patterns to hide now?", False):
            return
        ui.print("  Enter one pattern per line; press Enter when finished.")
        while True:
            pattern = ui.input("  Hidden-title pattern: ").strip()
            if not pattern:
                return
            self.command(["add", pattern])

    def print_config(self) -> None:
        self.command(["cfg"])

    def set_config(self, key: str, value: str) -> None:
        self.command(["cfg", key, value])

    def add_title_filter(self, pattern: str) -> int:
        patterns = self.title_filters()
        patterns.append(pattern)
        self.store.set_config(self.name, "patterns", json.dumps(patterns))
        return len(patterns)

    def list_title_filters(self) -> list:
        return [{"pattern": pattern, "enabled": True} for pattern in self.title_filters()]

    def remove_title_filter_by_position(self, position: int) -> bool:
        patterns = self.title_filters()
        if position < 1 or position > len(patterns):
            return False
        patterns.pop(position - 1)
        self.store.set_config(self.name, "patterns", json.dumps(patterns))
        return True

    def clear_title_filters(self) -> int:
        patterns = self.title_filters()
        self.store.set_config(self.name, "patterns", "[]")
        return len(patterns)

    def title_filters(self) -> list[str]:
        raw = self.store.get_config(self.name, "patterns", "[]") or "[]"
        try:
            patterns = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(patterns, list):
            return []
        return [pattern for pattern in patterns if isinstance(pattern, str)]

    def _check_if_short_http(self, video_id: str) -> bool | None:
        url = f"https://www.youtube.com/shorts/{video_id}"
        debug_log(2, f"title-filter: HEAD request to check Short status for {video_id}")
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                is_short = "/shorts/" in resp.url
                debug_log(2, f"title-filter: HEAD response for {video_id} is_shorts={is_short} (resolved url: {resp.url})")
                return is_short
        except Exception as exc:
            debug_log(2, f"title-filter: HEAD request error for {video_id}: {exc}")
            return None

    def _filter_shorts_logic(self, videos: list[Video]) -> list[Video]:
        debug_log(2, f"title-filter: _filter_shorts_logic called on {len(videos)} videos")
        uncached_video_ids: list[str] = []
        is_short_map: dict[str, bool] = {}

        for video in videos:
            if "/shorts/" in video.url:
                is_short_map[video.video_id] = True
                debug_log(2, f"title-filter: video {video.video_id} url contains /shorts/")
                continue
            cache_key = f"is_short:{video.video_id}"
            cached = self.store.get_cache(self.name, cache_key)
            if cached is not None:
                is_short_map[video.video_id] = (cached == "1")
                debug_log(2, f"title-filter: cached shorts status for {video.video_id} is {cached == '1'}")
            else:
                uncached_video_ids.append(video.video_id)

        if uncached_video_ids:
            debug_log(1, f"title-filter: checking shorts status for {len(uncached_video_ids)} uncached videos in parallel")
            max_workers = min(10, len(uncached_video_ids))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_id = {
                    executor.submit(self._check_if_short_http, vid): vid
                    for vid in uncached_video_ids
                }
                for future in future_to_id:
                    vid = future_to_id[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        debug_log(2, f"title-filter: check thread failed for {vid}: {exc}")
                        result = None
                    
                    if result is not None:
                        is_short_map[vid] = result
                        self.store.set_cache(self.name, f"is_short:{vid}", "1" if result else "0")
                    else:
                        is_short_map[vid] = False

        filtered = [video for video in videos if not is_short_map.get(video.video_id, False)]
        removed_count = len(videos) - len(filtered)
        if removed_count > 0:
            debug_log(1, f"title-filter: filtered out {removed_count} Shorts videos")
        return filtered

    def filter_videos(self, ctx: VideoListContext, videos: list[Video]) -> list[Video]:
        debug_log(2, f"title-filter: filter_videos checking {len(videos)} videos")
        rows = [row for row in self.list_title_filters() if row["enabled"]]
        if rows:
            debug_log(2, f"title-filter: applying {len(rows)} regex filters")
            compiled: list[re.Pattern[str]] = []
            for row in rows:
                try:
                    compiled.append(re.compile(row["pattern"], re.IGNORECASE))
                except re.error as exc:
                    debug_log(1, f"title-filter: invalid regex {row['pattern']!r}: {exc}")
                    continue
            if compiled:
                original_len = len(videos)
                videos = [video for video in videos if not any(rx.search(video.title) for rx in compiled)]
                removed_count = original_len - len(videos)
                if removed_count > 0:
                    debug_log(1, f"title-filter: filtered out {removed_count} videos matching title regex patterns")

        filter_shorts = self.store.get_config(self.name, "filter_shorts", "off") == "on"
        debug_log(2, f"title-filter: shorts filtering status: {filter_shorts}")
        if filter_shorts:
            videos = self._filter_shorts_logic(videos)

        return videos


def create_addon(store):
    return TitleFilterAddon(store)
