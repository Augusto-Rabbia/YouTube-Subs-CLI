from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Protocol

from .commands import AddonRegistry, CommandRegistry, CommandSpec
from .models import Video, VideoListContext
from .paths import CACHE_DIR, CONFIG_DIR, DATA_DIR, MODS_DIR
from .prompts import SetupPrompts
from .store import Store


class Addon(Protocol):
    name: str
    description: str
    default_enabled: bool
    help_details: dict[str, dict[str, object]]

    def register_commands(self, registry: CommandRegistry) -> None:
        ...

    def setup(self, ui: SetupPrompts) -> None:
        ...

    def enable(self) -> None:
        ...

    def disable(self) -> None:
        ...

    def print_config(self) -> None:
        ...

    def set_config(self, key: str, value: str) -> None:
        ...

    def export_config_snapshot(self) -> dict[str, object]:
        ...

    def import_config_snapshot(self, payload: object, ui: SetupPrompts) -> None:
        ...

    def command_allowed(self, command: str, args: list[str], access_controlled: bool) -> bool:
        ...

    def before_video_list(self, ctx: VideoListContext, videos: list[Video]) -> bool | None:
        ...

    def before_fetch(self, ctx: VideoListContext) -> bool | None:
        ...

    def filter_videos(self, ctx: VideoListContext, videos: list[Video]) -> list[Video]:
        ...

    def render_title(self, ctx: VideoListContext, video: Video, current_title: str) -> str:
        ...

    def after_video_list(self, ctx: VideoListContext, videos: list[Video]) -> None:
        ...


class BaseAddon:
    name = "base"
    storage_namespace: str | None = None
    description = "Base addon"
    default_enabled = False
    help_details: dict[str, dict[str, object]] = {}

    def __init__(self, store: Store):
        self.store = store

    @property
    def persistence_namespace(self) -> str:
        return self.storage_namespace or self.name

    @property
    def enabled(self) -> bool:
        return self.store.is_addon_enabled(self.persistence_namespace, self.default_enabled)

    def require_enabled(self, command_name: str | None = None) -> bool:
        if self.enabled:
            return True
        command_name = command_name or self.name
        print(f"Addon {self.name} is disabled. Run `{command_name} on` to enable it.")
        return False

    def enable(self) -> None:
        self.store.set_addon_enabled(self.persistence_namespace, True)
        print(f"Addon {self.name} enabled.")

    def disable(self) -> None:
        self.store.set_addon_enabled(self.persistence_namespace, False)
        print(f"Addon {self.name} disabled.")

    def setup(self, ui: SetupPrompts) -> None:
        self.setup_enabled(ui)

    def setup_enabled(self, ui: SetupPrompts) -> bool:
        selected = ui.ask_yes_no(f"Enable `{self.name}`?", self.enabled)
        if selected and not self.enabled:
            self.enable()
        elif not selected and self.enabled:
            self.disable()
        return selected

    def run_setup_command(self, args: list[str]) -> None:
        if args:
            print(f"Usage: {self.name} setup")
            return
        ui = SetupPrompts()
        try:
            self.setup(ui)
            ui.finish()
        except (KeyboardInterrupt, EOFError):
            print("\nAddon setup cancelled.")

    def setup_entrypoint(self, args: list[str]) -> None:
        if not args or args[0].lower().strip() != "setup":
            print(f"Usage: {self.name} setup")
            return
        self.run_setup_command(args[1:])

    def print_config(self) -> None:
        rows = list(
            self.store.conn.execute(
                "SELECT key, value FROM addon_config WHERE addon_name = ? ORDER BY key",
                (self.persistence_namespace,),
            )
        )
        if not rows:
            print(f"No config stored for {self.name}.")
            return
        print(f"Config for {self.name}:")
        for row in rows:
            print(f"{row['key']} = {row['value']}")

    def set_config(self, key: str, value: str) -> None:
        self.store.set_config(self.persistence_namespace, key, value)
        print(f"Set {self.name}.{key} = {value}")

    def export_config_snapshot(self) -> dict[str, object]:
        rows = self.store.conn.execute(
            "SELECT key, value FROM addon_config WHERE addon_name = ? ORDER BY key",
            (self.persistence_namespace,),
        ).fetchall()
        return {
            "enabled": self.enabled,
            "config": {row["key"]: row["value"] for row in rows},
        }

    def import_config_snapshot(self, payload: object, ui: SetupPrompts) -> None:
        if not isinstance(payload, dict):
            ui.print(f"  Skipped invalid settings for addon {self.name!r}.")
            return
        enabled = payload.get("enabled")
        if isinstance(enabled, bool):
            self.store.set_addon_enabled(self.persistence_namespace, enabled)
        config = payload.get("config", {})
        if isinstance(config, dict):
            for key, value in config.items():
                if isinstance(key, str) and isinstance(value, str):
                    self.store.set_config(self.persistence_namespace, key, value)
        ui.print(f"  Imported settings for addon {self.name}.")

    def command_allowed(self, command: str, args: list[str], access_controlled: bool) -> bool:
        return True

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

    def register_commands(self, registry: CommandRegistry) -> None:
        return None

    def before_video_list(self, ctx: VideoListContext, videos: list[Video]) -> bool | None:
        return True

    def before_fetch(self, ctx: VideoListContext) -> bool | None:
        return True

    def filter_videos(self, ctx: VideoListContext, videos: list[Video]) -> list[Video]:
        return videos

    def render_title(self, ctx: VideoListContext, video: Video, current_title: str) -> str:
        return current_title

    def after_video_list(self, ctx: VideoListContext, videos: list[Video]) -> None:
        return None


class AddonManager:
    BUILTIN_PACKAGE = "ytsubs.addons"

    def __init__(self, store: Store):
        self.store = store
        self.registry = CommandRegistry()
        self.addons: dict[str, BaseAddon] = {}
        self.load_all()

    def load_all(self) -> None:
        self._load_builtin_addons()
        self._load_external_mods(MODS_DIR)
        for addon in self.addons.values():
            addon.register_commands(self.registry)
            self._ensure_setup_entrypoint(addon)

    def _load_builtin_addons(self) -> None:
        package = importlib.import_module(self.BUILTIN_PACKAGE)
        modules = sorted(
            info.name
            for info in pkgutil.iter_modules(package.__path__, package.__name__ + ".")
            if not info.name.rsplit(".", 1)[-1].startswith("_")
        )
        for module_name in modules:
            self._load_module(importlib.import_module(module_name))

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

    def _ensure_setup_entrypoint(self, addon: BaseAddon) -> None:
        spec = self.registry.commands.get(addon.name)
        if spec is None:
            self.registry.command(
                addon.name,
                addon.setup_entrypoint,
                f"{addon.name} setup",
                addon_name=addon.name,
            )
            return

        original_handler = spec.handler

        def handler(args: list[str]) -> None:
            if args and args[0].lower().strip() == "setup":
                addon.run_setup_command(args[1:])
                return
            original_handler(args)

        help_text = spec.help if "setup" in spec.help else f"{spec.help} | {addon.name} setup"
        self.registry.commands[addon.name] = CommandSpec(
            spec.name,
            handler,
            help_text,
            spec.addon_name or addon.name,
            spec.access_controlled,
        )

    def is_enabled(self, addon: BaseAddon) -> bool:
        return addon.enabled

    def installed(self) -> list[BaseAddon]:
        return sorted(self.addons.values(), key=lambda addon: addon.name)

    def export_config_snapshot(self) -> dict[str, object]:
        return {addon.name: addon.export_config_snapshot() for addon in self.installed()}

    def import_config_snapshot(self, payload: object, ui: SetupPrompts) -> None:
        if not isinstance(payload, dict):
            ui.print("Skipped invalid addon settings section.")
            return
        for name, data in payload.items():
            if not isinstance(name, str):
                continue
            addon = self.addons.get(name)
            if addon is None:
                ui.print(f"  Skipped settings for unavailable addon {name!r}.")
                continue
            addon.import_config_snapshot(data, ui)

    def command_allowed(self, command: str, args: list[str], access_controlled: bool) -> bool:
        for addon in self.addons.values():
            if not addon.command_allowed(command, args, access_controlled):
                return False
        return True

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

    def before_fetch(self, ctx: VideoListContext) -> bool:
        for addon in self.addons.values():
            if self.is_enabled(addon):
                hook = getattr(addon, "before_fetch", None)
                if callable(hook):
                    if hook(ctx) is False:
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
