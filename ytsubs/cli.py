from __future__ import annotations

import cmd
import shlex
import sys
from typing import Optional

from . import __version__
from .core.app import App
from .core.paths import ensure_project_dirs
from .core.setup import SetupWizard


HELP_DETAILS = {
    "sub": {
        "summary": "Manage channel subscriptions, categories, and OPML files.",
        "usage": "sub list|add|search|rm|category list|category add|category rm|import FILE|export [FILE]",
        "details": (
            "  sub list                   - List all subscribed channels.\n"
            "  sub search <query>         - Search YouTube channels matching query.\n"
            "  sub add <handle|url|id|N>  - Add a subscription by handle (@name), URL, channel ID,\n"
            "                               or search result index number (run `sub search` first).\n"
            "  sub rm <handle|name|id>    - Remove subscription matching the handle, name, or channel ID.\n"
            "  sub category list          - Show active channels and their category tags.\n"
            "  sub category add <ch> <c>  - Label channel with a category tag (e.g. sub cat @handle Tech).\n"
            "  sub category rm <ch> <c>   - Remove category tag from channel.\n"
            "  sub import <file_path>     - Import subscription channels from an OPML file.\n"
            "  sub export [file_path]     - Export subscription channels to an OPML file (default: data/ytsubs_subscriptions.opml)."
        ),
        "examples": [
            "sub list",
            "sub search linustechtips",
            "sub add 1",
            "sub category add @3blue1brown Education",
            "sub import data/youtube_subs.opml",
            "sub export data/backups/my_channels.opml"
        ]
    },
    "new": {
        "summary": "Show new unwatched videos or configure default duration.",
        "usage": "new [DAYSd] | new default [DAYSd]",
        "details": (
            "  - new [DAYSd]              - Displays new, unwatched videos from your subscriptions\n"
            "                               published within the last N days (defaults to configured default).\n"
            "  - new default              - Show current default duration configuration.\n"
            "  - new default <DAYSd>      - Set default duration configuration (e.g. 3d, 14d, 30d)."
        ),
        "examples": [
            "new",
            "new 3d",
            "new default",
            "new default 14d"
        ]
    },
    "latest": {
        "summary": "Show latest videos.",
        "usage": "latest COUNT|DAYSd [CHANNEL]",
        "details": (
            "  Shows the latest videos (watched or unwatched) across subscriptions or for a specific channel.\n"
            "  If COUNT is specified, shows that many videos. If DAYSd is specified, shows videos from last N days.\n"
            "  CHANNEL can be @handle, channel name, or channel ID."
        ),
        "examples": [
            "latest 10",
            "latest 7d",
            "latest 5 @3blue1brown"
        ]
    },
    "watch": {
        "summary": "Mark videos as watched.",
        "usage": "watch NUMBER [NUMBER...] | VIDEO_ID_OR_URL [...] | DATE+ | all",
        "details": (
            "  Marks specific videos as watched so they do not show up in the `new` command list.\n"
            "  - Pass numbers matching the list indices of the last command output (e.g. 1 3 4).\n"
            "  - Pass full YouTube video URLs or 11-character video IDs.\n"
            "  - Use DATE+ (e.g. 2026-06-26+) to instantly mark everything published before that date as watched.\n"
            "  - Use 'all' to mark all videos in the last listed command as watched."
        ),
        "examples": [
            "watch 1 2",
            "watch dQw4w9WgXcQ",
            "watch 2026-06-26+",
            "watch all"
        ]
    },
    "w": {
        "summary": "Alias for watch.",
        "usage": "w NUMBER [NUMBER...] | VIDEO_ID_OR_URL [...] | DATE+ | all",
        "details": "  Accepts identical arguments as the `watch` command.",
        "examples": [
            "w 1 2",
            "w all",
            "w 2026-06-26+"
        ]
    },
    "download": {
        "summary": "Download videos for offline viewing using yt-dlp.",
        "usage": "download TARGET... | setup | cfg [help|KEY VALUE]",
        "details": (
            "  Download videos with embedded metadata and chapters.\n"
            "  - download <index|url|id>       - Download a listed video, URL, or video ID.\n"
            "  - download setup                - Run guided download configuration.\n"
            "  - download cfg directory <path> - Choose where downloaded media is stored.\n"
            "  - download cfg quality <q>      - Set quality such as best, 1080p, or 720p.\n"
            "  - download cfg container <c>    - Set output container: mkv, mp4, or webm.\n"
            "  - download cfg sponsorblock     - Configure SponsorBlock actions."
        ),
        "examples": [
            "download setup",
            "download 1",
            "download cfg directory downloads/courses",
        ],
    },
    "dl": {
        "summary": "Alias for download.",
        "usage": "dl TARGET...",
        "details": "  Accepts identical download targets as the `download` command.",
        "examples": [
            "dl 1",
            "dl 2 3",
        ],
    },
    "refresh": {
        "summary": "Refresh subscriptions feed.",
        "usage": "refresh",
        "details": "  Downloads and updates the feed cache with the latest uploads from all subscribed channels.",
        "examples": [
            "refresh"
        ]
    },
    "addon": {
        "summary": "Manage app addons.",
        "usage": "addon list|enable NAME|disable NAME|set NAME KEY VALUE|config NAME",
        "details": (
            "  addon list                      - List all installed addons and their enable status.\n"
            "  addon enable <name>             - Enable an addon.\n"
            "  addon disable <name>            - Disable an addon.\n"
            "  addon set <name> <key> <value>  - Update configuration option for an addon.\n"
            "  addon config <name>             - Display current configuration values for an addon."
        ),
        "examples": [
            "addon list",
            "addon enable your-addon",
            "addon config your-addon"
        ]
    },
    "config": {
        "summary": "Export a portable backup of subscriptions and settings.",
        "usage": "config export [FILE]",
        "details": (
            "  Exports subscriptions, categories, built-in download preferences, and installed addon settings.\n"
            "  - config export            - Save to data/ytsubs_configuration.json.\n"
            "  - config export <file>     - Save to a chosen JSON file.\n"
            "  Import an exported file through `setup`, where protected addon settings can show required warnings."
        ),
        "examples": [
            "config export",
            "config export data/my_ytsubs_backup.json",
        ],
    },
    "setup": {
        "summary": "Run the guided first-time configuration again.",
        "usage": "setup",
        "details": (
            "  Starts the setup wizard after you confirm by typing `ok`.\n"
            "  The wizard can restore a `config export` file, or configure subscriptions, downloading,\n"
            "  and each installed addon's own setup flow manually."
        ),
        "examples": [
            "setup"
        ]
    },
    "profile": {
        "summary": "Manage isolated user profiles, backups, and database restores.",
        "usage": "profile list|switch NAME|create NAME|current|backup [NAME]|restore NAME|backups",
        "details": (
            "  Allows running separate subscription database profiles and managing backups.\n"
            "  - profile list             - List all database profiles.\n"
            "  - profile current          - Print current active profile.\n"
            "  - profile switch <name>    - Switch database profile to named one (creates if not exists).\n"
            "  - profile backup [name]    - Back up the current profile database.\n"
            "  - profile restore <name>   - Restore the current profile database from a backup.\n"
            "  - profile backups          - List available backups for the current profile."
        ),
        "examples": [
            "profile list",
            "profile current",
            "profile switch gaming",
            "profile backup pre-upgrade",
            "profile backups",
            "profile restore pre-upgrade"
        ]
    },
    "purge": {
        "summary": "Clean old videos and watched logs from the database.",
        "usage": "purge [DAYSd]",
        "details": (
            "  Purges videos and watched log entries older than the specified duration.\n"
            "  - Pass a duration token like 30d, 60d, or 90d (defaults to 60d).\n"
            "  - Helps manage disk space and keep the feed search/filtering performant."
        ),
        "examples": [
            "purge",
            "purge 30d",
            "purge 90d"
        ]
    },
    "debug": {
        "summary": "Configure application-wide debugging levels.",
        "usage": "debug [on|off|0|1|2]",
        "details": (
            "  Enables or configures the verbosity level of debug statements printed to the console.\n"
            "  - debug on / 1  - Info level debugging (shows major backend actions & fallbacks).\n"
            "  - debug 2       - Verbose level debugging (shows individual cache hits, check status, command arguments).\n"
            "  - debug off / 0 - Disable all debugging output (default)."
        ),
        "examples": [
            "debug",
            "debug on",
            "debug 2",
            "debug off"
        ]
    }
}


class Shell(cmd.Cmd):
    intro = "Welcome to YTSubs-CLI! Type `help` for commands. Type `quit` to exit."
    prompt = "> "

    def __init__(self, app: App):
        super().__init__()
        self.app = app

    def default(self, line: str) -> None:
        self.run_line(line)

    def emptyline(self) -> None:
        return None

    def help_details(self, command: str) -> dict[str, object] | None:
        info = HELP_DETAILS.get(command)
        if info is not None:
            return info
        spec = self.app.registry.commands.get(command)
        if spec is None or spec.addon_name is None:
            return None
        addon = self.app.addons.addons.get(spec.addon_name)
        if addon is None:
            return None
        return addon.help_details.get(command)

    def do_help(self, arg: str) -> None:  # noqa: D401 - cmd signature
        arg = arg.strip().lower()
        if arg:
            shortcut_map = {
                "s": "sub",
                "n": "new",
                "l": "latest",
                "r": "refresh",
                "p": "profile",
                "w": "watch",
                "dl": "download",
            }
            if arg in shortcut_map:
                arg = shortcut_map[arg]

            info = self.help_details(arg)
            if info is not None:
                print(f"Command: {arg}")
                print(f"Summary: {info['summary']}")
                print(f"Usage:   {info['usage']}")
                if info.get("details"):
                    print("\nDetails:")
                    print(info["details"])
                if info.get("examples"):
                    print("\nExamples:")
                    for ex in info["examples"]:
                        print(f"  > {ex}")
            else:
                spec = self.app.registry.commands.get(arg)
                if spec:
                    print(f"Command: {arg}")
                    print(f"Usage:   {spec.help}")
                else:
                    print(f"Unknown command: '{arg}'. Type `help` to list commands.")
            return

        print("YTSubs-CLI commands:")
        print("Core Commands:")
        core_list = [
            ("s", "sub"),
            ("n", "new"),
            ("l", "latest"),
            ("w", "watch"),
            ("dl", "download"),
            ("r", "refresh"),
            (None, "addon"),
            (None, "config"),
            (None, "setup"),
            ("p", "profile"),
            (None, "purge"),
            (None, "debug"),
            (None, "quit"),
        ]
        for alias, cmd_name in core_list:
            label_raw = f"{alias}, {cmd_name}" if alias else cmd_name
            padded = f"{label_raw:<12}"
            bold_padded = f"\033[1m{padded}\033[0m"

            summary = HELP_DETAILS.get(cmd_name, {}).get("summary", "")
            usage = HELP_DETAILS.get(cmd_name, {}).get("usage", cmd_name)
            print(f"  {bold_padded} - {summary} (Usage: {usage})")

        addons = self.app.addons.installed()
        if addons:
            print("\nAddon Commands:")
            for addon in addons:
                specs = [
                    spec
                    for spec in self.app.registry.commands.values()
                    if spec.addon_name == addon.name
                ]
                names = sorted((spec.name for spec in specs), key=lambda x: (len(x), x))
                label_raw = ", ".join(names)
                padded = f"{label_raw:<12}"
                bold_padded = f"\033[1m{padded}\033[0m"
                info = addon.help_details.get(addon.name, {})
                spec = self.app.registry.commands.get(addon.name) or specs[0]
                usage = info.get("usage", spec.help)
                print(f"  {bold_padded} - {addon.description} (Usage: {usage})")

        print("\nTip: Type `help <command>` (e.g. `help watch`, `help filter`) for details and examples.")
        print("Options: --profile NAME, --help, --version")

    def do_quit(self, arg: str) -> bool:
        return True

    def do_exit(self, arg: str) -> bool:
        return True

    def do_EOF(self, arg: str) -> bool:
        print()
        return True

    def run_line(self, line: str) -> None:
        try:
            args = shlex.split(line)
        except ValueError as exc:
            print(f"Parse error: {exc}")
            return
        if not args:
            return
        command = args[0].lower()
        rest = args[1:]
        try:
            if command in {"quit", "exit"}:
                raise SystemExit(0)
            if command == "help":
                self.do_help(" ".join(rest))
                return
            self.app.dispatch(command, rest)
        except KeyboardInterrupt:
            print("Interrupted.")
        except Exception as exc:
            print(f"Error: {exc}")


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv in (["--version"], ["-V"]):
        print(f"YTSubs-CLI {__version__}")
        return 0

    ensure_project_dirs()

    profile = None
    if argv:
        if len(argv) >= 2 and argv[0] == "--profile":
            profile = argv[1]
            argv = argv[2:]
        elif argv[0].startswith("--profile="):
            profile = argv[0].split("=", 1)[1]
            argv = argv[1:]

    if argv and argv[0] in {"--help", "-h"}:
        argv = ["help", *argv[1:]]

    try:
        app = App(profile=profile)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    first_command = argv[0].lower() if argv else None
    if first_command not in {"help", "setup"} and not SetupWizard(app).is_complete():
        if not app.addons.command_allowed("setup", [], True):
            return 1
        if not sys.stdin.isatty():
            print("Initial setup is required. Run `setup` from an interactive terminal.", file=sys.stderr)
            return 2
        if not SetupWizard(app).run():
            return 1

    shell = Shell(app)

    if not argv or argv[0] == "run":
        try:
            shell.cmdloop()
        except KeyboardInterrupt:
            print()
        return 0

    shell.run_line(" ".join(shlex.quote(part) for part in argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
