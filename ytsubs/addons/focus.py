from __future__ import annotations

from datetime import datetime, time, timedelta
import json
import re
import select
import shlex
import sys
import termios
import tty

from ytsubs.core.addons import AddonRegistry, BaseAddon, SetupPrompts
from ytsubs.core.models import Video, VideoListContext
from ytsubs.core.util import debug_log


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_ALIASES = {
    "mon": "mon",
    "monday": "mon",
    "tue": "tue",
    "tues": "tue",
    "tuesday": "tue",
    "wed": "wed",
    "wednesday": "wed",
    "thu": "thu",
    "thur": "thu",
    "thurs": "thu",
    "thursday": "thu",
    "fri": "fri",
    "friday": "fri",
    "sat": "sat",
    "saturday": "sat",
    "sun": "sun",
    "sunday": "sun",
}
DAY_LABELS = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class FocusAddon(BaseAddon):
    name = "focus"
    description = "Delay or restrict video and subscription access using focus schedules."
    default_enabled = False
    help_details = {
        "focus": {
            "summary": "Delay or schedule access to subscription and video actions.",
            "usage": "focus on|off|setup|cfg [help|seconds N]|schedule ...|invincible on|off",
            "details": (
                "  - focus setup              - Run the focus addon's guided setup.\n"
                "  - focus cfg seconds <n>    - Delay video lists; any key cancels the request.\n"
                "  - focus schedule list      - Display active local-time access rules.\n"
                "  - focus schedule set <days> allow|block <ranges> - Set access hours.\n"
                "  - focus invincible on      - Enable protected mode after a warning.\n"
                "  - focus invincible off     - Schedule shutdown for next-day 05:00."
            ),
            "examples": ["focus setup", "focus schedule set mon-thu allow 16:00-18:00,20:00-21:00"],
        },
    }

    def register_commands(self, registry: AddonRegistry) -> None:
        registry.command(
            "focus",
            self.command,
            "focus on|off|setup|cfg [help|seconds N]|schedule ...|invincible on|off",
            addon_name=self.name,
        )

    def command(self, args: list[str]) -> None:
        self.apply_pending()
        self.enforce_invincible()
        if not args:
            self.print_status()
            return

        action = args[0].lower().strip()
        rest = args[1:]
        if action in {"on", "enable"}:
            self.enable()
        elif action in {"off", "disable"}:
            self.disable()
        elif action == "setup":
            self.run_setup_command(rest)
        elif action == "cfg":
            self.command_cfg(rest)
        elif action in {"schedule", "hours"}:
            self.command_schedule(rest)
        elif action in {"invincible", "lock"}:
            self.command_invincible(rest)
        elif action in {"help", "-h", "--help"}:
            self.print_help()
        else:
            print("Usage: focus on|off|setup|cfg [help|seconds N]|schedule ...|invincible on|off")

    def print_status(self) -> None:
        enabled = self.store.is_addon_enabled(self.name, self.default_enabled)
        invincible = self.invincible_enabled()
        print(
            f"Focus addon: {'enabled' if enabled else 'disabled'}, "
            f"delay = {self.seconds()}s, invincible = {'on' if invincible else 'off'}"
        )
        if not enabled and self.schedule():
            print("  Schedule is saved but is not enforced while the focus addon is disabled.")
        self.print_schedule()
        self.print_pending()

    def print_help(self) -> None:
        print("Focus Addon Commands:")
        print("  focus on | off")
        print("  focus setup")
        print("  focus cfg seconds N")
        print("  focus schedule list")
        print("  focus schedule set DAYS allow|block HH:MM-HH:MM[,HH:MM-HH:MM...]")
        print("  focus schedule clear DAYS|all")
        print("  focus invincible on | off")
        print("DAYS accepts mon, monday, mon-thu, mon,wed,fri, weekdays, weekends, or all.")
        print("Use local 24-hour times. `allow` permits protected commands only in those windows;")
        print("`block` permits them except in those windows. Unconfigured days are unrestricted.")

    def enable(self) -> None:
        self.store.set_addon_enabled(self.name, True)
        print("Focus addon enabled.")

    def disable(self) -> None:
        if self.invincible_enabled():
            effective_at = self.queue_shutdown()
            print("Invincible mode prevents disabling the focus addon immediately.")
            print(f"Focus addon and invincible mode are scheduled to turn off at {effective_at} local time.")
            return
        self.store.set_addon_enabled(self.name, False)
        print("Focus addon disabled.")

    def setup(self, ui: SetupPrompts) -> None:
        if not self.setup_enabled(ui):
            return
        seconds = ui.ask_validated(
            f"  Delay before showing a video list in seconds [{self.seconds()}]: ",
            str(self.seconds()),
            lambda value: value.isdigit() and int(value) >= 0,
            "Enter a non-negative whole number.",
        )
        self.command_cfg(["seconds", seconds])
        if ui.ask_yes_no("  Configure scheduled allowed/blocked hours now?", False):
            if self.schedule() and ui.ask_yes_no("  Clear the existing schedule first?", False):
                self.command_schedule(["clear", "all"])
            ui.print("  Enter rules such as: mon-thu allow 16:00-18:00,20:00-21:00")
            ui.print("  Use `allow` for usable windows or `block` for restricted windows; blank finishes.")
            while True:
                rule = ui.input("  Focus rule: ").strip()
                if not rule:
                    break
                try:
                    parts = shlex.split(rule)
                except ValueError as exc:
                    ui.print(f"  Invalid rule: {exc}")
                    continue
                self.command_schedule(["set", *parts])
        if not self.invincible_enabled() and ui.ask_yes_no(
            "  Enable invincible mode after reviewing its lock-in warning?", False
        ):
            ui.defer(lambda: self.command_invincible(["on"]))

    def print_config(self) -> None:
        self.print_status()

    def set_config(self, key: str, value: str) -> None:
        self.command_cfg([key, value])

    def command_cfg(self, args: list[str]) -> None:
        if not args:
            self.print_status()
            return
        key = args[0].lower().strip()
        if key == "help":
            print("Focus Configuration Help:")
            print("  seconds: seconds to delay video list display before it is shown (default: 45)")
            print("  During a delay, pressing any key cancels the list request; it does not bypass the timer.")
            print("  Schedule changes made during invincible mode take effect the next day at 05:00 local time.")
            return
        if len(args) < 2:
            print("Usage: focus cfg [help|seconds N]")
            return
        value = args[1].strip()
        if key != "seconds":
            print(f"Unknown configuration key: {key}")
            return
        if not value.isdigit() or int(value) < 0:
            print("Error: seconds must be a non-negative integer")
            return
        seconds = str(int(value))
        if self.invincible_enabled():
            effective_at = self.queue_change("seconds", seconds)
            print(f"Invincible mode is active. Delay change queued for {effective_at} local time.")
            return
        self.store.set_config(self.name, "seconds", seconds)
        print(f"Set focus.seconds = {seconds}")

    def seconds(self) -> int:
        raw = self.store.get_config(self.name, "seconds", "45") or "45"
        try:
            return max(0, int(raw))
        except ValueError:
            return 45

    def command_schedule(self, args: list[str]) -> None:
        if not args or args[0].lower() in {"list", "show"}:
            self.print_schedule()
            self.print_pending(only="schedule")
            return

        action = args[0].lower().strip()
        if action == "help":
            self.print_help()
            return
        if action == "clear":
            if len(args) != 2:
                print("Usage: focus schedule clear DAYS|all")
                return
            try:
                days = parse_days(args[1])
            except ValueError as exc:
                print(f"Error: {exc}")
                return
            schedule = self.schedule_for_update()
            for day in days:
                schedule.pop(day, None)
            self.update_schedule(schedule)
            return
        if action != "set" or len(args) < 4:
            print("Usage: focus schedule set DAYS allow|block HH:MM-HH:MM[,HH:MM-HH:MM...]")
            return

        try:
            days = parse_days(args[1])
            mode = args[2].lower().strip()
            if mode not in {"allow", "block"}:
                raise ValueError("schedule mode must be `allow` or `block`")
            ranges = parse_ranges("".join(args[3:]))
        except ValueError as exc:
            print(f"Error: {exc}")
            return

        schedule = self.schedule_for_update()
        policy = {"mode": mode, "ranges": ranges}
        for day in days:
            schedule[day] = policy
        self.update_schedule(schedule)

    def update_schedule(self, schedule: dict[str, dict[str, object]]) -> None:
        if self.invincible_enabled():
            effective_at = self.queue_change("schedule", schedule)
            print(f"Invincible mode is active. Schedule change queued for {effective_at} local time.")
            return
        self.write_schedule(schedule)
        print("Focus schedule updated.")
        self.print_schedule()

    def schedule(self) -> dict[str, dict[str, object]]:
        raw = self.store.get_config(self.name, "schedule", "{}") or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return self.normalized_schedule(parsed)

    def schedule_for_update(self) -> dict[str, dict[str, object]]:
        if self.invincible_enabled():
            pending = self.pending().get("schedule")
            if pending is not None:
                return self.normalized_schedule(pending["value"])
        return self.schedule()

    def normalized_schedule(self, parsed: object) -> dict[str, dict[str, object]]:
        if not isinstance(parsed, dict):
            return {}
        result: dict[str, dict[str, object]] = {}
        for day in WEEKDAYS:
            policy = parsed.get(day)
            if not isinstance(policy, dict) or policy.get("mode") not in {"allow", "block"}:
                continue
            raw_ranges = policy.get("ranges")
            if not isinstance(raw_ranges, list):
                continue
            try:
                ranges = parse_ranges(",".join(str(item) for item in raw_ranges))
            except ValueError:
                continue
            result[day] = {"mode": policy["mode"], "ranges": ranges}
        return result

    def write_schedule(self, schedule: dict[str, dict[str, object]]) -> None:
        ordered = {day: schedule[day] for day in WEEKDAYS if day in schedule}
        self.store.set_config(self.name, "schedule", json.dumps(ordered, separators=(",", ":")))

    def print_schedule(self) -> None:
        schedule = self.schedule()
        print("Focus schedule (local time):")
        if not schedule:
            print("  No scheduled restrictions.")
            return
        for day in WEEKDAYS:
            policy = schedule.get(day)
            if policy is None:
                print(f"  {DAY_LABELS[day]:<9} unrestricted")
                continue
            ranges = ", ".join(str(value) for value in policy["ranges"])
            print(f"  {DAY_LABELS[day]:<9} {policy['mode']} {ranges}")

    def command_invincible(self, args: list[str]) -> None:
        if not args:
            state = "on" if self.invincible_enabled() else "off"
            print(f"Invincible mode: {state}")
            self.print_pending()
            return
        action = args[0].lower().strip()
        if action in {"on", "enable"}:
            self.enable_invincible(args[1:])
        elif action in {"off", "disable"}:
            self.disable_invincible()
        else:
            print("Usage: focus invincible on|off")

    def enable_invincible(self, confirmation: list[str]) -> None:
        if self.invincible_enabled():
            if self.cancel_shutdown():
                print("Pending focus/invincible shutdown cancelled. Invincible mode remains enabled.")
            else:
                print("Invincible mode is already enabled.")
            return

        print("WARNING: Invincible mode is a deliberate lock on focus controls.")
        print("- It enables the focus addon immediately and protects it from immediate disabling.")
        print("- Protected commands are blocked according to the currently active focus schedule.")
        print("- Changes to schedules or the delay timer will not apply until the next day at 05:00 local time.")
        print("- Turning off invincible mode or the focus addon is also delayed until then.")
        print("- During blocked hours, sub/new/latest/watch/refresh/download actions are unavailable.")
        print("You may be unable to regain YouTube/subscription access until the scheduled release time.")
        confirmed = " ".join(confirmation).lower().strip() == "confirm"
        if not confirmed and sys.stdin.isatty():
            try:
                confirmed = input("Type ENABLE INVINCIBLE to accept these restrictions: ").strip() == "ENABLE INVINCIBLE"
            except (KeyboardInterrupt, EOFError):
                print("\nInvincible mode was not enabled.")
                return
        if not confirmed:
            print("Invincible mode was not enabled. Run `focus invincible on confirm` to confirm explicitly.")
            return

        self.store.set_addon_enabled(self.name, True)
        self.store.set_config(self.name, "invincible", "on")
        self.cancel_shutdown()
        print("Invincible mode enabled. The focus addon is enabled and protected immediately.")

    def disable_invincible(self) -> None:
        if not self.invincible_enabled():
            print("Invincible mode is already disabled.")
            return
        effective_at = self.queue_shutdown()
        print("Invincible mode cannot be turned off immediately.")
        print(f"Focus addon and invincible mode are scheduled to turn off at {effective_at} local time.")

    def invincible_enabled(self) -> bool:
        return (self.store.get_config(self.name, "invincible", "off") or "off").lower() == "on"

    def enforce_invincible(self) -> None:
        if self.invincible_enabled() and not self.enabled:
            self.store.set_addon_enabled(self.name, True)
            debug_log(1, "focus: restored focus addon enablement required by invincible mode")

    def next_release_at(self, now: datetime | None = None) -> datetime:
        local_now = now or datetime.now()
        return datetime.combine(local_now.date() + timedelta(days=1), time(hour=5))

    def pending(self) -> dict[str, dict[str, object]]:
        raw = self.store.get_config(self.name, "pending", "{}") or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        pending: dict[str, dict[str, object]] = {}
        for key in ("schedule", "seconds", "enabled", "invincible"):
            change = parsed.get(key)
            if not isinstance(change, dict) or "value" not in change or not isinstance(change.get("effective_at"), str):
                continue
            pending[key] = change
        return pending

    def write_pending(self, pending: dict[str, dict[str, object]]) -> None:
        self.store.set_config(self.name, "pending", json.dumps(pending, separators=(",", ":"), sort_keys=True))

    def queue_change(self, key: str, value: object) -> str:
        pending = self.pending()
        prior = pending.get(key)
        if prior and prior.get("value") == value:
            return str(prior["effective_at"])
        effective_at = self.next_release_at().strftime("%Y-%m-%d 05:00")
        pending[key] = {"value": value, "effective_at": effective_at}
        self.write_pending(pending)
        return effective_at

    def queue_shutdown(self) -> str:
        effective_at = self.queue_change("invincible", "off")
        pending = self.pending()
        pending["enabled"] = {"value": False, "effective_at": effective_at}
        self.write_pending(pending)
        return effective_at

    def cancel_shutdown(self) -> bool:
        pending = self.pending()
        removed = False
        for key in ("enabled", "invincible"):
            if key in pending:
                pending.pop(key)
                removed = True
        if removed:
            self.write_pending(pending)
        return removed

    def print_pending(self, *, only: str | None = None) -> None:
        pending = self.pending()
        entries = [(key, change) for key, change in pending.items() if only is None or key == only]
        if not entries:
            return
        print("Pending invincible-mode changes:")
        for key, change in sorted(entries):
            value = change["value"]
            if key == "schedule":
                value = "updated schedule"
            elif key == "enabled":
                value = "on" if value else "off"
            print(f"  {key} = {value} (effective {change['effective_at']} local time)")

    def apply_pending(self, now: datetime | None = None) -> None:
        pending = self.pending()
        if not pending:
            return
        local_now = now or datetime.now()
        matured: dict[str, dict[str, object]] = {}
        for key, change in pending.items():
            try:
                effective_at = datetime.strptime(str(change["effective_at"]), "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if local_now >= effective_at:
                matured[key] = change
        if not matured:
            return

        if "schedule" in matured and isinstance(matured["schedule"]["value"], dict):
            self.write_schedule(matured["schedule"]["value"])
        if "seconds" in matured:
            self.store.set_config(self.name, "seconds", str(matured["seconds"]["value"]))
        if "invincible" in matured:
            self.store.set_config(self.name, "invincible", str(matured["invincible"]["value"]))
        if "enabled" in matured:
            self.store.set_addon_enabled(self.name, bool(matured["enabled"]["value"]))
        for key in matured:
            pending.pop(key, None)
        self.write_pending(pending)
        debug_log(1, "focus: applied pending invincible-mode changes")

    def command_allowed(
        self,
        command: str,
        args: list[str],
        access_controlled: bool,
        now: datetime | None = None,
    ) -> bool:
        self.apply_pending(now)
        self.enforce_invincible()
        if not self.enabled or not access_controlled:
            return True
        local_now = now or datetime.now()
        policy = self.schedule().get(WEEKDAYS[local_now.weekday()])
        if policy is None:
            return True
        minutes = local_now.hour * 60 + local_now.minute
        in_window = any(in_range(minutes, str(value)) for value in policy["ranges"])
        allowed = in_window if policy["mode"] == "allow" else not in_window
        if allowed:
            return True
        mode_text = "outside allowed hours" if policy["mode"] == "allow" else "during blocked hours"
        print(
            f"Focus schedule blocked `{command}`: it is {mode_text} on "
            f"{DAY_LABELS[WEEKDAYS[local_now.weekday()]]} at {local_now.strftime('%H:%M')} local time."
        )
        print("Run `focus schedule list` to view the active schedule.")
        return False

    def before_video_list(self, ctx: VideoListContext, videos: list[Video]) -> bool:
        self.apply_pending()
        seconds = self.seconds()
        debug_log(2, f"focus: before_video_list called (seconds={seconds})")
        if seconds <= 0 or not videos:
            debug_log(2, "focus: skipping focus delay (seconds <= 0 or no videos)")
            return True
        if not sys.stdin.isatty():
            debug_log(2, "focus: sys.stdin is not a tty; skipping countdown")
            return True
        debug_log(1, f"focus: starting countdown delay of {seconds} seconds")
        return wait_for_key_or_timeout(seconds)


def parse_days(raw: str) -> list[str]:
    value = raw.lower().strip()
    if value == "all":
        return list(WEEKDAYS)
    if value in {"weekdays", "weekday"}:
        return list(WEEKDAYS[:5])
    if value in {"weekends", "weekend"}:
        return list(WEEKDAYS[5:])
    selected: list[str] = []
    for part in value.split(","):
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            start = DAY_ALIASES.get(start_raw)
            end = DAY_ALIASES.get(end_raw)
            if start is None or end is None:
                raise ValueError(f"invalid day range: {part}")
            index = WEEKDAYS.index(start)
            while True:
                day = WEEKDAYS[index]
                if day not in selected:
                    selected.append(day)
                if day == end:
                    break
                index = (index + 1) % len(WEEKDAYS)
        else:
            day = DAY_ALIASES.get(part)
            if day is None:
                raise ValueError(f"invalid day: {part}")
            if day not in selected:
                selected.append(day)
    if not selected:
        raise ValueError("at least one day is required")
    return selected


def parse_ranges(raw: str) -> list[str]:
    if not raw:
        raise ValueError("at least one time range is required")
    ranges: list[tuple[int, int]] = []
    for value in raw.split(","):
        if "-" not in value:
            raise ValueError(f"invalid time range: {value}")
        start_raw, end_raw = value.split("-", 1)
        start = parse_time(start_raw, end=False)
        end = parse_time(end_raw, end=True)
        if start >= end:
            raise ValueError("overnight ranges are not supported; split them across adjacent days")
        ranges.append((start, end))
    ranges.sort()
    for index in range(1, len(ranges)):
        if ranges[index][0] < ranges[index - 1][1]:
            raise ValueError("time ranges cannot overlap")
    return [f"{format_minutes(start)}-{format_minutes(end)}" for start, end in ranges]


def parse_time(value: str, *, end: bool) -> int:
    if end and value == "24:00":
        return 24 * 60
    if not TIME_RE.fullmatch(value):
        raise ValueError(f"invalid time: {value}; expected HH:MM in 24-hour time")
    hour, minute = (int(part) for part in value.split(":", 1))
    return hour * 60 + minute


def format_minutes(value: int) -> str:
    if value == 24 * 60:
        return "24:00"
    hour, minute = divmod(value, 60)
    return f"{hour:02d}:{minute:02d}"


def in_range(minutes: int, value: str) -> bool:
    start_raw, end_raw = value.split("-", 1)
    return parse_time(start_raw, end=False) <= minutes < parse_time(end_raw, end=True)


def wait_for_key_or_timeout(seconds: int) -> bool:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        for remaining in range(seconds, 0, -1):
            print(f"\rFocus delay: {remaining}s. Press any key to cancel this request. ", end="", flush=True)
            ready, _, _ = select.select([sys.stdin], [], [], 1)
            if ready:
                sys.stdin.read(1)
                print("\r" + " " * 78 + "\r", end="", flush=True)
                return False
        print("\r" + " " * 78 + "\r", end="", flush=True)
        return True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def create_addon(store):
    return FocusAddon(store)
