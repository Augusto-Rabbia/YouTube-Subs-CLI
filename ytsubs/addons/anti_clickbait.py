from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ytsubs import __version__
from ytsubs.core.addons import AddonRegistry, BaseAddon, SetupPrompts
from ytsubs.core.models import Video, VideoListContext
from ytsubs.core.util import debug_log

API_BASE = "https://sponsor.ajay.app"
USER_AGENT = f"ytsubs-cli/{__version__} AntiClickbaitAddon"
VALID_MODES = {"original", "replaced", "both"}
VALID_CASINGS = {"as-is", "shift-caps"}
TITLE_WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)


class AntiClickbaitAddon(BaseAddon):
    name = "anti-clickbait"
    storage_namespace = "dearrow"
    description = "Replace clickbait titles using DeArrow API community alternatives and optional Shift Caps formatting."
    default_enabled = False
    help_details = {
        "anti-clickbait": {
            "summary": "Replace clickbait titles with cleaner community titles.",
            "usage": "anti-clickbait on | off | setup | cfg [help|KEY VALUE]",
            "details": (
                "  Uses the DeArrow API for community title data. Consider supporting the DeArrow project.\n"
                "  - anti-clickbait setup           - Run the addon's guided setup.\n"
                "  - anti-clickbait on/off          - Toggle the addon.\n"
                "  - anti-clickbait cfg mode <mode> - Set original, replaced, or both title display.\n"
                "  - anti-clickbait cfg casing <c>  - Set as-is or shift-caps capitalization."
            ),
            "examples": [
                "anti-clickbait setup",
                "anti-clickbait cfg mode both",
                "anti-clickbait cfg casing shift-caps",
            ],
        },
    }

    def register_commands(self, registry: AddonRegistry) -> None:
        registry.command(
            self.name,
            self.command,
            "anti-clickbait on|off|setup|cfg [help|KEY VALUE]",
            addon_name=self.name,
        )

    @property
    def enabled(self) -> bool:
        return self.store.is_addon_enabled(self.storage_namespace, self.default_enabled)

    def enable(self) -> None:
        self.store.set_addon_enabled(self.storage_namespace, True)
        print("Addon anti-clickbait enabled.")

    def disable(self) -> None:
        self.store.set_addon_enabled(self.storage_namespace, False)
        print("Addon anti-clickbait disabled.")

    def command(self, args: list[str]) -> None:
        if not args:
            print(
                f"Anti-Clickbait: {'enabled' if self.enabled else 'disabled'}, "
                f"mode={self.mode()}, casing={self.casing()}"
            )
            return

        action = args[0].lower().strip()
        if action in {"on", "enable"}:
            self.enable()
        elif action in {"off", "disable"}:
            self.disable()
        elif action == "setup":
            self.run_setup_command(args[1:])
        elif action == "cfg":
            if len(args) == 1:
                print("Anti-Clickbait Configuration:")
                print(f"  mode = {self.mode()}")
                print(f"  casing = {self.casing()}")
                return
            sub = args[1].lower().strip()
            if sub == "help":
                print("Anti-Clickbait Configuration Help:")
                print("  mode: original | replaced | both (default: replaced) - rendering mode for clickbait titles")
                print("  casing: as-is | shift-caps (default: as-is) - optionally capitalize each title word")
                return
            if len(args) < 3:
                print("Usage: anti-clickbait cfg [help|KEY VALUE]")
                return
            val = args[2].lower().strip()
            if sub == "mode":
                if val not in VALID_MODES:
                    print("Error: mode must be one of: original, replaced, both")
                    return
                self.store.set_config(self.storage_namespace, "mode", val)
                print(f"Set anti-clickbait.mode = {val}")
            elif sub == "casing":
                if val not in VALID_CASINGS:
                    print("Error: casing must be one of: as-is, shift-caps")
                    return
                self.store.set_config(self.storage_namespace, "casing", val)
                print(f"Set anti-clickbait.casing = {val}")
            else:
                print(f"Unknown configuration key: {sub}")
        else:
            print("Usage: anti-clickbait on|off|setup|cfg [help|KEY VALUE]")

    def setup(self, ui: SetupPrompts) -> None:
        ui.print("  Anti-Clickbait retrieves community titles using the DeArrow API.")
        ui.print("  If you benefit from this feature, consider supporting the DeArrow project.")
        if not self.setup_enabled(ui):
            return
        mode = ui.ask_choice(
            f"  Title display mode [{self.mode()}] (replaced/both/original): ",
            VALID_MODES,
            self.mode(),
        )
        self.store.set_config(self.storage_namespace, "mode", mode)
        casing = ui.ask_choice(
            f"  Title capitalization [{self.casing()}] (as-is/shift-caps): ",
            VALID_CASINGS,
            self.casing(),
        )
        self.store.set_config(self.storage_namespace, "casing", casing)

    def print_config(self) -> None:
        self.command(["cfg"])

    def set_config(self, key: str, value: str) -> None:
        self.command(["cfg", key, value])

    def mode(self) -> str:
        mode = (self.store.get_config(self.storage_namespace, "mode", "replaced") or "replaced").lower()
        if mode not in VALID_MODES:
            return "replaced"
        return mode

    def casing(self) -> str:
        casing = (self.store.get_config(self.storage_namespace, "casing", "as-is") or "as-is").lower()
        if casing not in VALID_CASINGS:
            return "as-is"
        return casing

    def format_title(self, title: str) -> str:
        if self.casing() == "shift-caps":
            return shift_caps_title(title)
        return title

    def render_title(self, ctx: VideoListContext, video: Video, current_title: str) -> str:
        mode = self.mode()
        debug_log(2, f"anti-clickbait: render_title called for {video.video_id} (mode={mode}, casing={self.casing()})")
        if mode == "original":
            return self.format_title(current_title)
        replacement = self.get_replacement_title(video.video_id)
        if not replacement or replacement == video.title:
            debug_log(2, f"anti-clickbait: no replacement found or identical for {video.video_id}")
            return self.format_title(current_title)
        if mode == "both":
            debug_log(2, f"anti-clickbait: replacing title for {video.video_id} with both formats")
            return f"{self.format_title(replacement)} [original: {self.format_title(video.title)}]"
        debug_log(2, f"anti-clickbait: replaced title for {video.video_id}")
        return self.format_title(replacement)

    def get_replacement_title(self, video_id: str) -> str | None:
        cache_key = f"title:{video_id}"
        cached = self.store.get_cache(self.storage_namespace, cache_key)
        if cached is not None:
            debug_log(2, f"anti-clickbait cache hit for {video_id}: {cached!r}")
            return cached or None
        debug_log(2, f"anti-clickbait cache miss for {video_id}")
        try:
            title = self.fetch_replacement_title(video_id)
        except Exception as exc:
            debug_log(1, f"anti-clickbait: failed to fetch replacement title for {video_id}: {exc}")
            title = None
        self.store.set_cache(self.storage_namespace, cache_key, title or "")
        return title

    def fetch_replacement_title(self, video_id: str) -> str | None:
        query = urlencode({"videoID": video_id, "service": "YouTube"})
        url = f"{API_BASE}/api/branding?{query}"
        debug_log(1, f"anti-clickbait: fetching DeArrow branding data for video {video_id}")
        debug_log(2, f"anti-clickbait HTTP request: {url}")
        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=10) as response:
                res_bytes = response.read()
                debug_log(2, f"anti-clickbait HTTP success: {url} ({len(res_bytes)} bytes)")
                data = json.loads(res_bytes.decode("utf-8"))
        except HTTPError as exc:
            debug_log(2, f"anti-clickbait HTTP error code: {exc.code}")
            if exc.code == 404:
                return None
            raise
        except URLError as exc:
            debug_log(2, f"anti-clickbait network error: {exc.reason}")
            raise

        titles = data.get("titles") or []
        for item in titles:
            if item.get("original"):
                continue
            if item.get("locked") is True or int(item.get("votes") or 0) >= 0:
                title = str(item.get("title") or "").replace(">", "").strip()
                if title:
                    debug_log(1, f"anti-clickbait: found replacement title for {video_id}: {title!r}")
                    return title
        debug_log(2, f"anti-clickbait: no non-original/voted replacement titles found for {video_id}")
        return None


def shift_caps_title(title: str) -> str:
    return TITLE_WORD_RE.sub(lambda match: match.group(0).capitalize(), title)


def create_addon(store):
    return AntiClickbaitAddon(store)
