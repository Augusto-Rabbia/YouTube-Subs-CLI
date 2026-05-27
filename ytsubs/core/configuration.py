from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ytsubs import __version__

from .models import ChannelCandidate
from .paths import DATA_DIR
from .prompts import SetupPrompts
from .util import CHANNEL_ID_RE, set_debug_level

if TYPE_CHECKING:
    from .app import App


CONFIG_FORMAT = "ytsubs-configuration"
CONFIG_FORMAT_VERSION = 1
DEFAULT_CONFIG_EXPORT = "ytsubs_configuration.json"


@dataclass(frozen=True)
class ImportResult:
    subscriptions_added: int
    subscriptions_existing: int
    subscriptions_skipped: int


class ConfigurationTransfer:
    """Portable configuration transfer, delegating addon internals to addon hooks."""

    def __init__(self, app: App) -> None:
        self.app = app

    def export_file(self, file_path: str | None = None) -> bool:
        path = Path(file_path).expanduser().resolve() if file_path else DATA_DIR / DEFAULT_CONFIG_EXPORT
        payload = self.export_payload()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"Error writing configuration file: {exc}")
            return False
        print(f"Configuration export complete: saved to {path}")
        return True

    def export_payload(self) -> dict[str, object]:
        core: dict[str, str] = {}
        for key in ("new_days", "debug"):
            value = self.app.store.get_config("core", key)
            if value is not None:
                core[key] = value
        subscriptions = []
        for row in self.app.store.list_subscriptions():
            subscriptions.append(
                {
                    "channel_id": row["channel_id"],
                    "display_name": row["display_name"],
                    "handle": row["handle"],
                    "url": row["url"],
                    "categories": self.app.store.get_channel_categories(row["channel_id"]),
                }
            )
        return {
            "format": CONFIG_FORMAT,
            "format_version": CONFIG_FORMAT_VERSION,
            "app_version": __version__,
            "subscriptions": subscriptions,
            "core": core,
            "download": self.app.download.export_config_snapshot(),
            "addons": self.app.addons.export_config_snapshot(),
        }

    def import_file(self, file_path: str, ui: SetupPrompts) -> ImportResult | None:
        path = Path(file_path).expanduser().resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            ui.print(f"Configuration file not found: {path}")
            return None
        except (OSError, json.JSONDecodeError) as exc:
            ui.print(f"Could not read configuration file: {exc}")
            return None
        if not isinstance(payload, dict) or payload.get("format") != CONFIG_FORMAT:
            ui.print("Not a ytsubs configuration export file.")
            return None
        if payload.get("format_version") != CONFIG_FORMAT_VERSION:
            ui.print("Unsupported ytsubs configuration export version.")
            return None
        return self.import_payload(payload, ui)

    def import_payload(self, payload: dict[str, object], ui: SetupPrompts) -> ImportResult:
        result = self._import_subscriptions(payload.get("subscriptions"), ui)
        self._import_core(payload.get("core"), ui)
        self.app.download.import_config_snapshot(payload.get("download"), ui)
        self.app.addons.import_config_snapshot(payload.get("addons"), ui)
        return result

    def _import_core(self, payload: object, ui: SetupPrompts) -> None:
        if not isinstance(payload, dict):
            return
        days = payload.get("new_days")
        if isinstance(days, str) and days.isdigit() and int(days) > 0:
            self.app.store.set_config("core", "new_days", days)
        debug = payload.get("debug")
        if isinstance(debug, str) and debug in {"0", "1", "2"}:
            self.app.store.set_config("core", "debug", debug)
            set_debug_level(int(debug))
        ui.print("  Imported application preferences.")

    def _import_subscriptions(self, payload: object, ui: SetupPrompts) -> ImportResult:
        added = 0
        existing = 0
        skipped = 0
        if not isinstance(payload, list):
            ui.print("  Skipped invalid subscriptions section.")
            return ImportResult(added, existing, skipped)
        for item in payload:
            if not isinstance(item, dict):
                skipped += 1
                continue
            channel_id = item.get("channel_id")
            title = item.get("display_name")
            if not isinstance(channel_id, str) or not CHANNEL_ID_RE.fullmatch(channel_id):
                skipped += 1
                continue
            if not isinstance(title, str) or not title.strip():
                title = channel_id
            handle = item.get("handle") if isinstance(item.get("handle"), str) else None
            url = item.get("url") if isinstance(item.get("url"), str) else None
            candidate = ChannelCandidate(channel_id, title, handle, url)
            if self.app.store.add_subscription(candidate):
                added += 1
            else:
                existing += 1
            categories = item.get("categories", [])
            if isinstance(categories, list):
                for category in categories:
                    if isinstance(category, str) and category.strip():
                        self.app.store.add_channel_category(channel_id, category.strip())
        ui.print(f"  Imported subscriptions: {added} added, {existing} already present, {skipped} skipped.")
        return ImportResult(added, existing, skipped)
