from __future__ import annotations

import select
import sys
import termios
import tty

from ytsubs.core.addons import AddonRegistry, BaseAddon
from ytsubs.core.models import Video, VideoListContext
from ytsubs.core.util import debug_log


class FocusDelayAddon(BaseAddon):
    name = "focus-delay"
    description = "Delay video lists until the timer expires, or show immediately when any key is pressed."
    default_enabled = False

    def register_commands(self, registry: AddonRegistry) -> None:
        registry.command("focus", self.command, "focus on|off|cfg [help|KEY VALUE]", addon_name=self.name)

    def command(self, args: list[str]) -> None:
        if not args:
            enabled = self.store.is_addon_enabled(self.name, self.default_enabled)
            seconds = self.seconds()
            print(f"Focus delay: {'enabled' if enabled else 'disabled'}, {seconds}s")
            return

        action = args[0].lower().strip()
        if action in {"on", "enable"}:
            self.store.set_addon_enabled(self.name, True)
            print("Focus delay enabled.")
        elif action in {"off", "disable"}:
            self.store.set_addon_enabled(self.name, False)
            print("Focus delay disabled.")
        elif action == "cfg":
            if len(args) == 1:
                print("Focus Delay Configuration:")
                print(f"  seconds = {self.seconds()}")
                return
            sub = args[1].lower().strip()
            if sub == "help":
                print("Focus Delay Configuration Help:")
                print("  seconds: number of seconds to delay video list display (default: 45)")
                return
            if len(args) < 3:
                print("Usage: focus cfg [help|KEY VALUE]")
                return
            val = args[2].strip()
            if sub == "seconds":
                if not val.isdigit() or int(val) < 0:
                    print("Error: seconds must be a non-negative integer")
                    return
                self.store.set_config(self.name, "seconds", str(int(val)))
                print(f"Set focus-delay.seconds = {int(val)}")
            else:
                print(f"Unknown configuration key: {sub}")
        else:
            print("Usage: focus on|off|cfg [help|KEY VALUE]")

    def seconds(self) -> int:
        raw = self.store.get_config(self.name, "seconds", "45") or "45"
        try:
            return max(0, int(raw))
        except ValueError:
            return 45

    def before_video_list(self, ctx: VideoListContext, videos: list[Video]) -> None:
        seconds = self.seconds()
        debug_log(2, f"focus-delay: before_video_list called (seconds={seconds})")
        if seconds <= 0 or not videos:
            debug_log(2, "focus-delay: skipping focus delay (seconds <= 0 or no videos)")
            return
        if not sys.stdin.isatty():
            debug_log(2, "focus-delay: sys.stdin is not a tty; skipping countdown")
            return
        debug_log(1, f"focus-delay: starting countdown delay of {seconds} seconds")
        wait_for_key_or_timeout(seconds)


def wait_for_key_or_timeout(seconds: int) -> None:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        for remaining in range(seconds, 0, -1):
            print(f"\rFocus delay: {remaining}s. Press any key to show now. ", end="", flush=True)
            ready, _, _ = select.select([sys.stdin], [], [], 1)
            if ready:
                sys.stdin.read(1)
                break
        print("\r" + " " * 72 + "\r", end="", flush=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def create_addon(store):
    return FocusDelayAddon(store)
