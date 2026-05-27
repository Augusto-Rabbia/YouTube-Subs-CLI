from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .commands import CommandRegistry
from .models import Video
from .paths import CACHE_DIR, PROJECT_ROOT
from .prompts import SetupPrompts
from .store import Store
from .util import debug_log, extract_video_id, get_debug_level


VALID_CONTAINERS = {"mkv", "mp4", "webm"}
DEFAULT_QUALITY = "1080p"
DEFAULT_CONTAINER = "mkv"
NON_DOWNLOAD_ACTIONS = {"on", "enable", "off", "disable", "setup", "cfg", "help", "-h", "--help"}


@dataclass(frozen=True)
class DownloadConfig:
    directory: Path
    quality: str
    container: str
    auto_watch: bool
    sb_actions: dict[str, str]


class DownloadService:
    namespace = "download"

    def __init__(self, store: Store) -> None:
        self.store = store

    def register_commands(self, registry: CommandRegistry) -> None:
        registry.command(
            "download",
            self.command,
            "download TARGET...|setup|cfg [help|KEY VALUE]",
            access_controlled=self.is_access_controlled_action,
        )
        registry.command(
            "dl",
            self.command,
            "dl TARGET...  # alias for download",
            access_controlled=self.is_access_controlled_action,
        )

    def is_access_controlled_action(self, args: list[str]) -> bool:
        return bool(args) and args[0].lower() not in NON_DOWNLOAD_ACTIONS

    def command(self, args: list[str]) -> None:
        if not args:
            self.print_usage()
            return

        action = args[0].lower().strip()
        rest = args[1:]

        if action in {"on", "enable", "off", "disable"}:
            print(
                "Downloading is built into ytsubs and has no addon toggle. "
                "Focus access restrictions still apply to video downloads."
            )
        elif action == "setup":
            self.run_setup_command(rest)
        elif action == "cfg":
            self.command_cfg(rest)
        elif action in {"help", "-h", "--help"}:
            self.print_usage()
        else:
            self.download_targets(args)

    def print_usage(self) -> None:
        print(
            "Usage:\n"
            "  download NUMBER [NUMBER...]\n"
            "  download VIDEO_ID_OR_URL [VIDEO_ID_OR_URL...]\n"
            "  download setup\n"
            "  download cfg [help|KEY VALUE]\n"
            "  dl NUMBER [NUMBER...]"
        )

    def run_setup_command(self, args: list[str]) -> None:
        if args:
            print("Usage: download setup")
            return
        ui = SetupPrompts()
        try:
            self.setup(ui)
            ui.finish()
        except (KeyboardInterrupt, EOFError):
            print("\nDownload setup cancelled.")

    def setup(self, ui: SetupPrompts) -> None:
        config = self.config()
        ui.print("  In Docker, keep this under `downloads/` so files persist on the host.")
        directory = ui.input(f"  Download directory [{config.directory}]: ").strip()
        if directory:
            self.set_directory(directory)
            config = self.config()
        quality = ui.ask_validated(
            f"  Maximum quality [{config.quality}]: ",
            config.quality,
            valid_quality,
            "Enter `best` or a resolution such as 480p, 720p, or 1080p.",
        ).lower()
        self.store.set_config(self.namespace, "quality", quality)
        container = ui.ask_choice(
            f"  Video container [{config.container}] (mkv/mp4/webm): ",
            VALID_CONTAINERS,
            config.container,
        )
        self.store.set_config(self.namespace, "container", container)
        auto_watch = ui.ask_yes_no("  Mark successful downloads as watched?", config.auto_watch)
        self.store.set_config(self.namespace, "auto_watch", "on" if auto_watch else "off")
        if ui.ask_yes_no("  Configure SponsorBlock removal/chapter actions now?", False):
            self.sponsorblock_wizard(ui)

    def export_config_snapshot(self) -> dict[str, object]:
        config = self.config()
        return {
            "directory": self.store.get_config(self.namespace, "directory", "downloads") or "downloads",
            "quality": config.quality,
            "container": config.container,
            "auto_watch": config.auto_watch,
            "sponsorblock": dict(config.sb_actions),
        }

    def import_config_snapshot(self, payload: object, ui: SetupPrompts) -> None:
        if not isinstance(payload, dict):
            ui.print("  Skipped invalid download settings section.")
            return
        directory = payload.get("directory")
        if isinstance(directory, str) and directory.strip():
            path = resolve_download_directory(directory.strip())
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                ui.print(f"  Could not restore download directory {path}: {exc}")
            else:
                self.store.set_config(self.namespace, "directory", directory.strip())
        quality = payload.get("quality")
        if isinstance(quality, str) and valid_quality(quality.lower()):
            self.store.set_config(self.namespace, "quality", quality.lower())
        container = payload.get("container")
        if isinstance(container, str) and container.lower() in VALID_CONTAINERS:
            self.store.set_config(self.namespace, "container", container.lower())
        auto_watch = payload.get("auto_watch")
        if isinstance(auto_watch, bool):
            self.store.set_config(self.namespace, "auto_watch", "on" if auto_watch else "off")
        actions = payload.get("sponsorblock")
        if isinstance(actions, dict):
            for category, action in actions.items():
                if isinstance(category, str) and isinstance(action, str) and action in {"cut", "mark", "off"}:
                    self.store.set_config(self.namespace, f"sb_action:{category}", action)
        ui.print("  Imported download settings.")

    def command_cfg(self, args: list[str]) -> None:
        if not args:
            config = self.config()
            print("Download Configuration:")
            print(f"  directory = {config.directory}")
            print(f"  quality = {config.quality}")
            print(f"  container = {config.container}")
            print(f"  auto_watch = {'on' if config.auto_watch else 'off'}")
            print("  SponsorBlock category actions:")
            for cat in [
                "sponsor",
                "intro",
                "outro",
                "interaction",
                "selfpromo",
                "preview",
                "filler",
                "music_offtopic",
            ]:
                action = config.sb_actions.get(cat, "off")
                print(f"    {cat} = {action}")
            return

        key = args[0].lower().strip()
        if key == "help":
            print("Download Configuration Help:")
            print("  directory: output folder (default: downloads; relative paths use the application root)")
            print("  quality: best | 144p | 240p | 360p | 480p | 720p | 1080p | 1440p | 2160p (default: 1080p)")
            print("  container: mkv | mp4 | webm (default: mkv) - target file format")
            print("  auto_watch: on | off (default: on) - mark downloaded videos as watched automatically")
            print("  sponsorblock: (run 'download cfg sponsorblock' to launch interactive setup wizard)")
            return

        if key == "sponsorblock":
            self.sponsorblock_wizard()
            return

        if len(args) < 2:
            print("Usage: download cfg [help|KEY VALUE]")
            return

        value = " ".join(args[1:]).strip()
        val = value.lower()
        if key == "directory":
            self.set_directory(value)
        elif key == "quality":
            if not valid_quality(val):
                print("Error: quality must be 'best' or a height like 480p, 720p, 1080p, etc.")
                return
            self.store.set_config(self.namespace, "quality", val)
            print(f"Set download.quality = {val}")
        elif key == "container":
            if val not in VALID_CONTAINERS:
                print("Error: container must be one of: mkv, mp4, webm")
                return
            self.store.set_config(self.namespace, "container", val)
            print(f"Set download.container = {val}")
        elif key in {"auto_watch", "autowatch"}:
            if val not in {"on", "off"}:
                print("Error: auto_watch must be 'on' or 'off'")
                return
            self.store.set_config(self.namespace, "auto_watch", val)
            print(f"Set download.auto_watch = {val}")
        else:
            print(f"Unknown configuration key: {key}")

    def set_directory(self, value: str) -> bool:
        value = value.strip()
        if not value:
            print("Error: directory cannot be empty")
            return False
        path = resolve_download_directory(value)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"Error: could not create download directory {path}: {exc}")
            return False
        self.store.set_config(self.namespace, "directory", value)
        print(f"Set download.directory = {path}")
        return True

    def sponsorblock_wizard(self, ui: SetupPrompts | None = None) -> None:
        ui = ui or SetupPrompts()
        ui.print("SponsorBlock Category Setup Wizard")
        ui.print("For each category, choose: cut (remove), mark (add chapters), or off (do nothing).")
        ui.print("Press Enter to keep the current value.")
        ui.print("-" * 65)

        categories = {
            "sponsor": "Sponsor segments",
            "intro": "Intro/Beginning animation",
            "outro": "Outro/End credits",
            "interaction": "Interaction reminders (subscribe/like)",
            "selfpromo": "Self-promotion/Unpaid promotions",
            "preview": "Preview/Recap of the video",
            "filler": "Filler tangent/Joke/Off-topic",
            "music_offtopic": "Non-music section in music video",
        }

        config = self.config()
        for cat, desc in categories.items():
            current = config.sb_actions.get(cat, "off")
            while True:
                try:
                    val = ui.input(f"  {cat} ({desc}) [current: {current}] [cut/mark/off]: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    ui.print("\nWizard cancelled.")
                    return
                if not val:
                    val = current
                if val in {"cut", "mark", "off"}:
                    self.store.set_config(self.namespace, f"sb_action:{cat}", val)
                    break
                ui.print("  Invalid choice. Please enter 'cut', 'mark', or 'off'.")

        ui.print("-" * 65)
        ui.print("SponsorBlock configuration updated successfully.")

    def config(self) -> DownloadConfig:
        directory_value = self.store.get_config(self.namespace, "directory")
        directory = resolve_download_directory(directory_value or "downloads")
        quality = (self.store.get_config(self.namespace, "quality", DEFAULT_QUALITY) or DEFAULT_QUALITY).lower()
        if not valid_quality(quality):
            quality = DEFAULT_QUALITY

        container = (
            self.store.get_config(self.namespace, "container", DEFAULT_CONTAINER) or DEFAULT_CONTAINER
        ).lower()
        if container not in VALID_CONTAINERS:
            container = DEFAULT_CONTAINER

        autowatch = (self.store.get_config(self.namespace, "auto_watch", "on") or "on").lower()
        auto_watch_bool = autowatch == "on"

        sb_cats = ["sponsor", "intro", "outro", "interaction", "selfpromo", "preview", "filler", "music_offtopic"]
        sb_actions = {}
        for cat in sb_cats:
            action = (self.store.get_config(self.namespace, f"sb_action:{cat}", "off") or "off").lower()
            if action not in {"cut", "mark", "off"}:
                action = "off"
            sb_actions[cat] = action

        return DownloadConfig(
            directory=directory,
            quality=quality,
            container=container,
            auto_watch=auto_watch_bool,
            sb_actions=sb_actions,
        )

    def cache_video_list(self, videos: list[Video]) -> None:
        self.store.delete_cache_prefix(self.namespace, "last_video:")
        for position, video in enumerate(videos, 1):
            self.store.set_cache(self.namespace, f"last_video:{position}", video.video_id)

    def download_targets(self, targets: list[str]) -> None:
        debug_log(1, f"download: download_targets called with targets: {targets}")
        resolved: list[str] = []
        bad: list[str] = []

        for target in targets:
            if target.isdigit():
                pos = int(target)
                debug_log(2, f"download: resolving position {pos}")
                video = self._last_video_by_position(pos)
                if video:
                    resolved.append(video.url)
                    debug_log(2, f"download: resolved position {pos} to url {video.url}")
                else:
                    bad.append(target)
                continue

            video_id = extract_video_id(target)
            if video_id:
                resolved.append(f"https://www.youtube.com/watch?v={video_id}")
                debug_log(2, f"download: resolved input {target} to video ID {video_id}")
            elif target.startswith("http://") or target.startswith("https://"):
                resolved.append(target)
                debug_log(2, f"download: target is direct URL: {target}")
            else:
                bad.append(target)

        if bad:
            print("Could not resolve these download targets: " + ", ".join(bad))
        if not resolved:
            return

        missing = runtime_dependency_errors()
        if missing:
            for line in missing:
                print(line)
            return

        config = self.config()
        try:
            config.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"Could not create download directory {config.directory}: {exc}")
            return
        debug_log(
            2,
            f"download config: directory={config.directory}, quality={config.quality}, auto_watch={config.auto_watch}",
        )
        is_debug = get_debug_level() > 0
        for url in dict.fromkeys(resolved):
            command = build_yt_dlp_command(url, config, quiet=not is_debug)
            debug_log(1, f"download: executing yt-dlp subprocess for {url}")
            debug_log(2, f"download subprocess command: {shlex.join(command)}")
            if is_debug:
                print("Running:")
                print("  " + shlex.join(command))
            else:
                title = None
                video_id = extract_video_id(url)
                if video_id:
                    video = self.store.get_video(video_id)
                    if video:
                        title = video.title
                if title:
                    print(f'Downloading "{title}"...')
                else:
                    print(f"Downloading {url}...")

            completed = subprocess.run(command, cwd=str(config.directory.parent))
            debug_log(2, f"download: subprocess finished with exit code {completed.returncode}")
            if completed.returncode == 0:
                print("Download complete.")
                if config.auto_watch:
                    video_id = extract_video_id(url)
                    if video_id:
                        debug_log(1, f"download: auto_watch enabled, marking {video_id} as watched")
                        self.store.mark_watched([video_id])
                        print(f"Marked video {video_id} as watched.")
            else:
                print(f"Download failed with exit code {completed.returncode}.")

    def _last_video_by_position(self, position: int) -> Video | None:
        raw = self.store.get_cache(self.namespace, f"last_video:{position}")
        if not raw:
            return None
        return self.store.get_video(raw)


def valid_quality(value: str) -> bool:
    if value == "best":
        return True
    if not value.endswith("p"):
        return False
    number = value[:-1]
    return number.isdigit() and 144 <= int(number) <= 4320


def format_selector(quality: str) -> str:
    if quality == "best":
        return "bv*+ba/b"
    height = int(quality[:-1])
    return f"bv*[height<={height}]+ba/b[height<={height}]/best[height<={height}]"


def resolve_download_directory(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def build_yt_dlp_command(url: str, config: DownloadConfig, quiet: bool = False) -> list[str]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--paths",
        f"home:{config.directory}",
        "--ignore-config",
        "--cache-dir",
        str(CACHE_DIR / "yt-dlp"),
        "--format",
        format_selector(config.quality),
        "--merge-output-format",
        config.container,
        "--embed-metadata",
        "--embed-chapters",
        "--no-playlist",
        "--restrict-filenames",
        "--output",
        "%(uploader|Unknown)s/%(upload_date|unknown)s_%(title).180B_[%(id)s].%(ext)s",
    ]

    if quiet:
        command.extend(["--quiet", "--no-warnings"])

    cuts = [cat for cat, act in config.sb_actions.items() if act == "cut"]
    marks = [cat for cat, act in config.sb_actions.items() if act == "mark"]

    if cuts:
        command.extend(["--sponsorblock-remove", ",".join(cuts)])
    if marks:
        command.extend(
            [
                "--sponsorblock-mark",
                ",".join(marks),
                "--sponsorblock-chapter-title",
                "[SponsorBlock]: %(category_names)l",
            ]
        )

    command.append(url)
    return command


def runtime_dependency_errors() -> list[str]:
    errors: list[str] = []
    if shutil.which("ffmpeg") is None:
        errors.append("ffmpeg is required for metadata embedding, chapter embedding, merging, and SponsorBlock cuts.")
        errors.append("Install it with your system package manager, then rerun setup if needed.")
    return errors
