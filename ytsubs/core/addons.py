from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable, Protocol

from .models import Video, VideoListContext
from .paths import CACHE_DIR, CONFIG_DIR, DATA_DIR, MODS_DIR
from .store import Store

CommandHandler = Callable[[list[str]], None]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    handler: CommandHandler
    help: str
    addon_name: str | None = None


class AddonRegistry:
    def __init__(self) -> None:
        self.commands: dict[str, CommandSpec] = {}

    def command(self, name: str, handler: CommandHandler, help: str, addon_name: str | None = None) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("command name cannot be empty")
        if key in self.commands:
            raise ValueError(f"command {key!r} already registered")
        self.commands[key] = CommandSpec(key, handler, help, addon_name)


class Addon(Protocol):
    name: str
    description: str
    default_enabled: bool

    def register_commands(self, registry: AddonRegistry) -> None:
        ...

    def before_video_list(self, ctx: VideoListContext, videos: list[Video]) -> bool | None:
        ...

    def filter_videos(self, ctx: VideoListContext, videos: list[Video]) -> list[Video]:
        ...

    def render_title(self, ctx: VideoListContext, video: Video, current_title: str) -> str:
        ...

    def after_video_list(self, ctx: VideoListContext, videos: list[Video]) -> None:
        ...


class BaseAddon:
    name = "base"
    description = "Base addon"
    default_enabled = False

    def __init__(self, store: Store):
        self.store = store

    @property
    def enabled(self) -> bool:
        return self.store.is_addon_enabled(self.name, self.default_enabled)

    def require_enabled(self, command_name: str | None = None) -> bool:
        if self.enabled:
            return True
        command_name = command_name or self.name
        print(f"Addon {self.name} is disabled. Run `{command_name} on` to enable it.")
        return False

    @property
    def data_dir(self) -> Path:
        path = DATA_DIR / "addons" / self.name
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def cache_dir(self) -> Path:
        path = CACHE_DIR / "addons" / self.name
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def config_dir(self) -> Path:
        path = CONFIG_DIR / "addons" / self.name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def open_addon_db(self):
        import sqlite3
        db_path = self.data_dir / "storage.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def register_commands(self, registry: AddonRegistry) -> None:
        return None

    def before_video_list(self, ctx: VideoListContext, videos: list[Video]) -> bool | None:
        return True

    def filter_videos(self, ctx: VideoListContext, videos: list[Video]) -> list[Video]:
        return videos

    def render_title(self, ctx: VideoListContext, video: Video, current_title: str) -> str:
        return current_title

    def after_video_list(self, ctx: VideoListContext, videos: list[Video]) -> None:
        return None


class AddonManager:
    BUILTIN_MODULES = (
        "ytsubs.addons.focus",
        "ytsubs.addons.title_filter",
        "ytsubs.addons.dearrow",
        "ytsubs.addons.download",
    )

    def __init__(self, store: Store):
        self.store = store
        self.registry = AddonRegistry()
        self.addons: dict[str, BaseAddon] = {}
        self.load_all()

    def load_all(self) -> None:
        for module_name in self.BUILTIN_MODULES:
            self._load_module(importlib.import_module(module_name))
        self._load_external_mods(MODS_DIR)
        for addon in self.addons.values():
            addon.register_commands(self.registry)

    def _load_external_mods(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            module_name = f"ytsubs_external_mod_{path.stem}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                print(f"Skipping mod {path.name}: cannot load module")
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
                self._load_module(module)
            except Exception as exc:
                print(f"Skipping mod {path.name}: {exc}")

    def _load_module(self, module: ModuleType) -> None:
        factory = getattr(module, "create_addon", None)
        if not callable(factory):
            return
        addon = factory(self.store)
        if not getattr(addon, "name", None):
            raise ValueError(f"addon from {module.__name__} has no name")
        if addon.name in self.addons:
            raise ValueError(f"duplicate addon name: {addon.name}")
        self.addons[addon.name] = addon

    def is_enabled(self, addon: BaseAddon) -> bool:
        return addon.enabled

    def apply_filters(self, ctx: VideoListContext, videos: list[Video]) -> list[Video]:
        result = videos
        for addon in self.addons.values():
            if self.is_enabled(addon):
                result = addon.filter_videos(ctx, result)
        return result

    def before_video_list(self, ctx: VideoListContext, videos: list[Video]) -> bool:
        for addon in self.addons.values():
            if self.is_enabled(addon):
                if addon.before_video_list(ctx, videos) is False:
                    return False
        return True

    def render_title(self, ctx: VideoListContext, video: Video, title: str) -> str:
        result = title
        for addon in self.addons.values():
            if self.is_enabled(addon):
                result = addon.render_title(ctx, video, result)
        return result

    def after_video_list(self, ctx: VideoListContext, videos: list[Video]) -> None:
        for addon in self.addons.values():
            if self.is_enabled(addon):
                hook = getattr(addon, "after_video_list", None)
                if callable(hook):
                    hook(ctx, videos)
