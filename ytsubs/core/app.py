from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import sqlite3

from .addons import AddonManager
from .commands import CommandRegistry
from .configuration import ConfigurationTransfer
from .download import DownloadService
from .metadata import VideoMetadataService
from .models import Video, VideoListContext, fmt_date, fmt_duration, parse_datetime, utcnow
from .paths import db_path, normalize_profile_name
from .store import Store
from .util import CHANNEL_ID_RE, extract_video_id, parse_days_token, debug_log, set_debug_level
from .youtube import YouTubeClient


class App:
    def __init__(self, profile: str | None = None) -> None:
        from .paths import get_active_profile
        self.profile = normalize_profile_name(profile if profile is not None else get_active_profile())
        self.store = Store(db_path(self.profile))
        self.yt = YouTubeClient()
        self.metadata = VideoMetadataService(self.store, self.yt)
        self.last_videos: list[Video] = []
        self.download = DownloadService(self.store)
        self.addons = AddonManager(self.store)
        self.configuration = ConfigurationTransfer(self)
        self.registry = self.addons.registry

        try:
            debug_val = self.store.get_config("core", "debug", "0")
            set_debug_level(int(debug_val))
        except Exception:
            set_debug_level(0)

        self._register_core_commands(self.registry)

    def _set_store(self, store: Store) -> None:
        self.store = store
        self.metadata.store = store
        self.download.store = store
        self.addons.store = store
        for addon in self.addons.addons.values():
            addon.store = store

    def _register_core_commands(self, registry: CommandRegistry) -> None:
        registry.command("sub", self.sub, "sub list|add|search|rm|category list|category add|category rm", access_controlled=True)
        registry.command("profile", self.profile_command, "profile list|switch NAME|create NAME|current")
        registry.command("new", self.new, "new [DAYSd] | new default [DAYSd]", access_controlled=lambda args: not (args and args[0].lower() == "default"))
        registry.command("latest", self.latest, "latest COUNT|DAYSd [CHANNEL]", access_controlled=True)
        registry.command("watch", self.watch, "watch NUMBER [NUMBER...] | VIDEO_ID_OR_URL [...] | DATE+ | all", access_controlled=True)
        registry.command("w", self.watch, "w NUMBER [NUMBER...] | VIDEO_ID_OR_URL [...] | DATE+ | all", access_controlled=True)
        registry.command("refresh", lambda args: self.refresh(), "refresh", access_controlled=True)
        self.download.register_commands(registry)
        registry.command("addon", self.addon_command, "addon list|enable NAME|disable NAME|set NAME KEY VALUE|config NAME")
        registry.command("config", self.config_command, "config export [FILE]")
        registry.command("setup", self.setup_command, "setup", access_controlled=True)
        registry.command("purge", self.purge, "purge [DAYSd]")
        registry.command("debug", self.debug_command, "debug [on|off|0|1|2]")

        # Aliases / Shortcuts
        registry.command("s", self.sub, "s list|add|search|rm|category list|category add|category rm", access_controlled=True)
        registry.command("n", self.new, "n [DAYSd] | n default [DAYSd]", access_controlled=lambda args: not (args and args[0].lower() == "default"))
        registry.command("l", self.latest, "l COUNT|DAYSd [CHANNEL]", access_controlled=True)
        registry.command("r", lambda args: self.refresh(), "r", access_controlled=True)
        registry.command("p", self.profile_command, "p list|switch NAME|create NAME|current")

    def debug_command(self, args: list[str]) -> None:
        if not args:
            lvl = self.store.get_config("core", "debug", "0")
            print(f"Debug mode is currently: {self._debug_label(lvl)}")
            return

        val = args[0].lower().strip()
        if val == "on":
            lvl = "1"
        elif val == "off":
            lvl = "0"
        elif val in {"0", "1", "2"}:
            lvl = val
        else:
            print("Usage: debug [on|off|0|1|2]")
            return

        self.store.set_config("core", "debug", lvl)
        set_debug_level(int(lvl))
        print(f"Debug mode set to: {self._debug_label(lvl)}")

    def _debug_label(self, lvl: str) -> str:
        if lvl == "0":
            return "off (0)"
        elif lvl == "1":
            return "info (1)"
        elif lvl == "2":
            return "verbose (2)"
        return f"unknown ({lvl})"

    def dispatch(self, command: str, args: list[str]) -> None:
        spec = self.registry.commands.get(command.lower())
        if not spec:
            print("Unknown command. Type `help`.")
            return
        if not self.addons.command_allowed(command, args, spec.requires_access(args)):
            return
        spec.handler(args)

    # Addon management
    def addon_command(self, args: list[str]) -> None:
        action = args[0].lower() if args else "list"
        rest = args[1:]
        if action in {"list", "ls"}:
            print("Addons:")
            for name, addon in sorted(self.addons.addons.items()):
                enabled = addon.enabled
                print(f"- {name}: {'enabled' if enabled else 'disabled'} - {addon.description}")
        elif action in {"enable", "on"}:
            if not rest:
                print("Usage: addon enable NAME")
                return
            name = rest[0]
            if name not in self.addons.addons:
                print(f"No addon named {name!r}.")
                return
            self.addons.addons[name].enable()
        elif action in {"disable", "off"}:
            if not rest:
                print("Usage: addon disable NAME")
                return
            name = rest[0]
            if name not in self.addons.addons:
                print(f"No addon named {name!r}.")
                return
            self.addons.addons[name].disable()
        elif action == "set":
            if len(rest) < 3:
                print("Usage: addon set NAME KEY VALUE")
                return
            name, key = rest[0], rest[1]
            value = " ".join(rest[2:])
            if name not in self.addons.addons:
                print(f"No addon named {name!r}.")
                return
            self.addons.addons[name].set_config(key, value)
        elif action == "config":
            if not rest:
                print("Usage: addon config NAME")
                return
            name = rest[0]
            if name not in self.addons.addons:
                print(f"No addon named {name!r}.")
                return
            self.addons.addons[name].print_config()
        else:
            print("Usage: addon list|enable NAME|disable NAME|set NAME KEY VALUE|config NAME")

    def setup_command(self, args: list[str]) -> None:
        if args:
            print("Usage: setup")
            return
        from .setup import SetupWizard

        SetupWizard(self).run(require_confirmation=True)

    def config_command(self, args: list[str]) -> None:
        if not args or args[0].lower().strip() != "export":
            print("Usage: config export [FILE]")
            return
        path = " ".join(args[1:]).strip() if len(args) > 1 else None
        self.configuration.export_file(path)

    # Subscription commands
    def sub(self, args: list[str]) -> None:
        action = args[0].lower() if args else "list"
        rest = args[1:]
        if action in {"list", "ls"}:
            self.sub_list()
        elif action == "add":
            self.sub_add(" ".join(rest).strip())
        elif action in {"rm", "remove", "del", "delete"}:
            self.sub_remove(" ".join(rest).strip())
        elif action in {"search", "find"}:
            self.sub_search(" ".join(rest).strip())
        elif action in {"cat", "category", "categories"}:
            self.sub_category(rest)
        elif action == "import":
            if not rest:
                print("Usage: sub import <file_path>")
                return
            self.sub_import(" ".join(rest).strip())
        elif action == "export":
            path = " ".join(rest).strip() if rest else None
            self.sub_export(path)
        else:
            print("Unknown sub command. Use: sub list | sub add | sub rm | sub search | sub category | sub import | sub export")

    def sub_category(self, args: list[str]) -> None:
        debug_log(1, f"sub_category invoked with args: {args}")
        if not args:
            print("Usage: sub category list | add <channel> [channel2...] <category> | rm <channel> [channel2...] <category>")
            return
        action = args[0].lower()
        rest = args[1:]

        if action in {"list", "ls"}:
            rows = self.store.list_channel_categories()
            if not rows:
                print("No channel categories defined.")
                return
            by_cat = {}
            for row in rows:
                cat = row["category"]
                label = row["handle"] or row["display_name"] or row["channel_id"]
                by_cat.setdefault(cat, []).append(label)
            print("Channel categories:")
            for cat, channels in sorted(by_cat.items()):
                print(f"  {cat}:")
                for chan in channels:
                    print(f"    - {chan}")

        elif action == "add":
            if len(rest) < 2:
                print("Usage: sub category add <channel> [channel2...] <category>")
                return
            
            channels = []
            category_parts = []
            for i, arg in enumerate(rest):
                if i == len(rest) - 1:
                    category_parts.append(arg)
                    break
                row = self.store.find_subscription(arg)
                if row:
                    debug_log(2, f"Category add: resolved arg {arg!r} to subscription {row['display_name']}")
                    channels.append(row)
                else:
                    debug_log(2, f"Category add: arg {arg!r} not resolved to channel, treating remainder as category")
                    category_parts.extend(rest[i:])
                    break
                    
            category = " ".join(category_parts).strip()
            if not channels:
                print("No matching subscriptions found for the given targets.")
                return
            if not category:
                print("Category name cannot be empty.")
                return
                
            for row in channels:
                debug_log(1, f"Adding category '{category}' to channel ID: {row['channel_id']}")
                self.store.add_channel_category(row["channel_id"], category)
                print(f"Added category '{category}' to subscription '{row['display_name']}'.")

        elif action in {"rm", "remove", "del", "delete"}:
            if len(rest) < 2:
                print("Usage: sub category rm <channel> [channel2...] <category>")
                return
            
            channels = []
            category_parts = []
            for i, arg in enumerate(rest):
                if i == len(rest) - 1:
                    category_parts.append(arg)
                    break
                row = self.store.find_subscription(arg)
                if row:
                    debug_log(2, f"Category rm: resolved arg {arg!r} to subscription {row['display_name']}")
                    channels.append(row)
                else:
                    debug_log(2, f"Category rm: arg {arg!r} not resolved to channel, treating remainder as category")
                    category_parts.extend(rest[i:])
                    break
                    
            category = " ".join(category_parts).strip()
            if not channels:
                print("No matching subscriptions found for the given targets.")
                return
            if not category:
                print("Category name cannot be empty.")
                return
                
            for row in channels:
                debug_log(1, f"Removing category '{category}' from channel ID: {row['channel_id']}")
                removed = self.store.remove_channel_category(row["channel_id"], category)
                if removed:
                    print(f"Removed category '{category}' from subscription '{row['display_name']}'.")
                else:
                    print(f"Subscription '{row['display_name']}' is not in category '{category}'.")
        else:
            print("Usage: sub category list | add <channel> [channel2...] <category> | rm <channel> [channel2...] <category>")

    def profile_command(self, args: list[str]) -> None:
        from .paths import set_active_profile, DATA_DIR, db_path

        action = args[0].lower() if args else "list"
        rest = args[1:]

        if action in {"list", "ls"}:
            db_files = sorted(DATA_DIR.glob("ytsubs*.sqlite3"))
            profiles = []
            for f in db_files:
                stem = f.stem
                if stem == "ytsubs":
                    profiles.append("default")
                elif stem.startswith("ytsubs_"):
                    profiles.append(stem[len("ytsubs_"):])
            print("Profiles:")
            for p in profiles:
                active_marker = " * " if p == self.profile else "   "
                print(f"{active_marker}{p}")

        elif action == "current":
            print(f"Current profile: {self.profile}")

        elif action in {"switch", "use", "create"}:
            if not rest:
                print("Usage: profile switch|create NAME")
                return
            try:
                new_profile = normalize_profile_name(rest[0])
            except ValueError as exc:
                print(f"Invalid profile name: {exc}")
                return
            debug_log(1, f"Switching to profile: {new_profile}")
            self.store.conn.close()
            set_active_profile(new_profile)
            self.profile = new_profile
            self._set_store(Store(db_path(new_profile)))
            print(f"Switched to profile '{new_profile}'.")

        elif action == "backup":
            from datetime import datetime
            import shutil
            
            backup_dir = DATA_DIR / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            suffix = rest[0].strip() if rest else datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = "".join(c for c in suffix if c.isalnum() or c in ("-", "_"))
            if not suffix:
                suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
                
            backup_file = backup_dir / f"{self.profile}_{suffix}.sqlite3"
            
            self.store.conn.close()
            try:
                shutil.copy2(db_path(self.profile), backup_file)
                print(f"Backup created successfully: data/backups/{backup_file.name}")
            except Exception as e:
                print(f"Error creating backup: {e}")
            finally:
                self._set_store(Store(db_path(self.profile)))

        elif action == "restore":
            if not rest:
                print("Usage: profile restore NAME_OR_TIMESTAMP")
                print("Tip: Run 'profile backups' to see available backups.")
                return
            
            import shutil
            backup_name = rest[0].strip()
            backup_dir = DATA_DIR / "backups"
            
            backup_file = backup_dir / f"{self.profile}_{backup_name}.sqlite3"
            if not backup_file.exists():
                candidates = list(backup_dir.glob(f"*{backup_name}*.sqlite3"))
                candidates = [c for c in candidates if c.name.startswith(f"{self.profile}_")]
                if len(candidates) == 1:
                    backup_file = candidates[0]
                elif len(candidates) > 1:
                    print("Ambiguous name, found multiple backups:")
                    for c in candidates:
                        print(f"  {c.name.replace(f'{self.profile}_', '').replace('.sqlite3', '')}")
                    return
                else:
                    print(f"Backup not found for profile '{self.profile}' containing {backup_name!r}.")
                    return
            
            print(f"Restoring profile '{self.profile}' from backup: {backup_file.name}")
            self.store.conn.close()
            try:
                current_db = db_path(self.profile)
                if current_db.exists():
                    shutil.copy2(current_db, current_db.with_suffix(".sqlite3.pre_restore"))
                shutil.copy2(backup_file, current_db)
                print("Restore completed successfully.")
            except Exception as e:
                print(f"Error restoring backup: {e}")
            finally:
                self._set_store(Store(db_path(self.profile)))

        elif action in {"backups", "list-backups"}:
            from datetime import datetime
            backup_dir = DATA_DIR / "backups"
            if not backup_dir.exists():
                print("No backups found.")
                return
            
            files = sorted(backup_dir.glob(f"{self.profile}_*.sqlite3"), key=lambda f: f.stat().st_mtime, reverse=True)
            if not files:
                print(f"No backups found for profile '{self.profile}'.")
                return
                
            print(f"Backups for profile '{self.profile}':")
            for f in files:
                name = f.name.replace(f"{self.profile}_", "").replace(".sqlite3", "")
                size_kb = f.stat().st_size / 1024
                mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                print(f"  - {name} ({mtime}, {size_kb:.1f} KB)")
        else:
            print("Usage: profile list | switch NAME | create NAME | current | backup [NAME] | restore NAME | backups")

    def sub_list(self) -> None:
        rows = self.store.list_subscriptions()
        if not rows:
            print("No subscriptions yet.")
            return
        print("Current subscriptions:")
        for row in rows:
            display_name = row["display_name"]
            handle = row["handle"]
            channel_id = row["channel_id"]
            if display_name and handle and display_name != handle:
                label = f"{display_name} ({handle})"
            elif handle:
                label = handle
            elif display_name:
                label = display_name
            else:
                label = channel_id
            print(label)

    def sub_import(self, file_path: str) -> None:
        from pathlib import Path
        import xml.etree.ElementTree as ET
        from .models import ChannelCandidate
        
        path = Path(file_path).resolve()
        if not path.exists():
            print(f"Error: File not found at {file_path}")
            return
            
        print(f"Importing subscriptions from {path.name}...")
        try:
            tree = ET.parse(path)
            root = tree.getroot()
        except Exception as e:
            print(f"Error parsing OPML XML: {e}")
            return
            
        outlines = root.findall(".//outline")
        imported_count = 0
        skipped_count = 0
        
        for outline in outlines:
            attrib = outline.attrib
            xml_url = attrib.get("xmlUrl") or attrib.get("xmlurl")
            html_url = attrib.get("htmlUrl") or attrib.get("htmlurl")
            title = attrib.get("title") or attrib.get("text") or "Unknown Channel"
            
            channel_id = None
            url_to_parse = xml_url or html_url
            if url_to_parse:
                from .util import extract_channel_id
                channel_id = extract_channel_id(url_to_parse)
                
            if not channel_id:
                continue
                
            existing = self.store.find_subscription(channel_id)
            if existing:
                skipped_count += 1
                continue
                
            candidate = ChannelCandidate(
                channel_id=channel_id,
                title=title,
                handle=None,
                url=html_url or f"https://www.youtube.com/channel/{channel_id}"
            )
            success = self.store.add_subscription(candidate)
            if success:
                imported_count += 1
                
        print(f"Import complete: {imported_count} subscriptions imported, {skipped_count} skipped (already subscribed).")

    def sub_export(self, file_path: str | None = None) -> None:
        from pathlib import Path
        import xml.etree.ElementTree as ET
        from xml.dom import minidom
        from .paths import DATA_DIR
        
        if not file_path:
            path = DATA_DIR / "ytsubs_subscriptions.opml"
        else:
            path = Path(file_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        
        subs = self.store.list_subscriptions()
        if not subs:
            print("No subscriptions to export.")
            return
            
        print(f"Exporting {len(subs)} subscriptions to {path}...")
        
        opml = ET.Element("opml", version="1.0")
        head = ET.SubElement(opml, "head")
        title_el = ET.SubElement(head, "title")
        title_el.text = "ytsubs-cli Subscriptions"
        
        body = ET.SubElement(opml, "body")
        outer_outline = ET.SubElement(body, "outline", text="YouTube Subscriptions", title="YouTube Subscriptions")
        
        for sub in subs:
            channel_id = sub["channel_id"]
            display_name = sub["display_name"]
            url = sub["url"] or f"https://www.youtube.com/channel/{channel_id}"
            xml_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            
            ET.SubElement(
                outer_outline,
                "outline",
                text=display_name,
                title=display_name,
                type="rss",
                xmlUrl=xml_url,
                htmlUrl=url
            )
            
        raw_xml = ET.tostring(opml, encoding="utf-8")
        parsed = minidom.parseString(raw_xml)
        pretty_xml = parsed.toprettyxml(indent="  ", encoding="utf-8")
        
        try:
            path.write_bytes(pretty_xml)
            print(f"Export complete: saved to {path}")
        except Exception as e:
            print(f"Error writing file: {e}")

    def sub_add(self, spec: str) -> None:
        debug_log(1, f"sub_add invoked with spec: {spec!r}")
        if not spec:
            print("Usage: sub add @Handle | URL | CHANNEL_ID | NUMBER")
            return

        if spec.isdigit():
            num = int(spec)
            debug_log(2, f"Looking up cached search result position: {num}")
            candidate = self.store.get_channel_search_result(num)
            if candidate is None:
                debug_log(1, f"No cached search result for position: {num}")
                print("No saved search result with that number. Run `sub search TERMS` first.")
                return
            debug_log(2, f"Found cached candidate: {candidate.title} ({candidate.channel_id})")
            created = self.store.add_subscription(candidate)
            if created:
                print(f"Sub added successfully!: {candidate.title} ({candidate.handle or candidate.channel_id})")
            else:
                print("Sub already exists.")
            return

        try:
            candidate = self.yt.resolve_channel(spec)
        except Exception as exc:
            debug_log(1, f"Failed to resolve channel direct: {exc}")
            if not spec.startswith("@") and "://" not in spec and not CHANNEL_ID_RE.match(spec):
                debug_log(1, f"Input is not formatted as ID/Handle/URL; triggering channel search for: {spec!r}")
                print(f"Could not directly resolve {spec!r}. Search results:")
                self.sub_search(spec)
                print("Run `sub add NUMBER` to add one of these results.")
                return
            print(f"Could not add subscription: {exc}")
            return

        debug_log(2, f"Saving subscription to store: {candidate.channel_id}")
        created = self.store.add_subscription(candidate)
        if created:
            print(f"Sub added successfully!: {candidate.title} ({candidate.handle or candidate.channel_id})")
        else:
            print("Sub already exists.")

    def sub_remove(self, spec: str) -> None:
        debug_log(1, f"sub_remove invoked with spec: {spec!r}")
        if not spec:
            print("Usage: sub rm @Handle-or-name-or-channel-id")
            return
        debug_log(2, f"Finding subscription matching {spec!r}")
        row = self.store.find_subscription(spec)
        if not row:
            debug_log(1, f"Subscription not found for spec: {spec!r}")
            print("No matching subscription.")
            return
        debug_log(2, f"Removing subscription from store: {row['channel_id']}")
        self.store.remove_subscription(row["channel_id"])
        print("Sub removed successfully.")

    def sub_search(self, query: str) -> None:
        if not query:
            print("Usage: sub search search terms")
            return
        try:
            results = self.yt.search_channels(query)
        except Exception as exc:
            print(f"Search failed: {exc}")
            return
        self.store.save_channel_search_results(results)
        if not results:
            print("No channel candidates found.")
            return
        for i, candidate in enumerate(results, 1):
            handle = f" {candidate.handle}" if candidate.handle else ""
            print(f"{i}. {candidate.title}{handle} {candidate.channel_id}")

    # Video commands
    def _fetch_subscription_feeds(
        self, rows: list[sqlite3.Row], *, silent: bool = False
    ) -> list[tuple[str, list[Video] | None, Exception | None]]:
        def fetch_worker(row) -> tuple[str, list[Video] | None, Exception | None]:
            debug_log(2, f"Start fetch worker for {row['display_name']} ({row['channel_id']})")
            try:
                videos = self.yt.fetch_channel_feed(row["channel_id"])
                debug_log(
                    2,
                    f"Finish fetch worker for {row['display_name']}: "
                    f"success ({len(videos) if videos else 0} videos)",
                )
                return row["display_name"], videos, None
            except Exception as exc:
                debug_log(1, f"Error in fetch worker for {row['display_name']}: {exc}")
                return row["display_name"], None, exc

        max_workers = min(10, len(rows))
        suffix = " (silent)" if silent else ""
        debug_log(1, f"Refreshing {len(rows)} feeds{suffix} in parallel with {max_workers} thread workers...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(fetch_worker, rows))

    def refresh(self, channel_id: str | None = None) -> None:
        debug_log(1, f"refresh invoked (channel_id={channel_id!r})")
        rows = self.store.list_subscriptions()
        if channel_id:
            rows = [row for row in rows if row["channel_id"] == channel_id]
        if not rows:
            debug_log(1, "No subscriptions to refresh.")
            print("No subscriptions yet.")
            return

        total = 0
        failures: list[str] = []
        results = self._fetch_subscription_feeds(rows)

        for display_name, videos, exc in results:
            if exc is not None:
                failures.append(f"{display_name}: {exc}")
            elif videos is not None:
                debug_log(2, f"Upserting {len(videos)} videos from {display_name} into database")
                total += self.store.upsert_videos(videos)

        if failures:
            print("Some feeds failed:")
            for failure in failures:
                print(f"- {failure}")
        print(f"Refreshed {len(rows)} subscriptions; cached {total} feed entries.")
        if not channel_id and not failures:
            self.store.set_config("core", "last_refresh_time", utcnow().isoformat())

    def refresh_silent(self, channel_id: str | None = None, force: bool = False) -> None:
        debug_log(1, f"refresh_silent invoked (channel_id={channel_id!r}, force={force})")
        if not force and not channel_id:
            last_refresh_str = self.store.get_config("core", "last_refresh_time")
            if last_refresh_str:
                try:
                    last_refresh = parse_datetime(last_refresh_str)
                    elapsed = utcnow() - last_refresh
                    debug_log(2, f"Time since last refresh: {elapsed.total_seconds():.1f}s")
                    if elapsed < timedelta(minutes=10):
                        debug_log(1, "Skipping refresh_silent (last refresh was less than 10 minutes ago)")
                        return
                except Exception as exc:
                    debug_log(2, f"Could not parse last refresh time config: {exc}")
                    pass

        rows = self.store.list_subscriptions()
        if channel_id:
            rows = [row for row in rows if row["channel_id"] == channel_id]
        if not rows:
            debug_log(1, "No subscriptions to refresh.")
            return

        results = self._fetch_subscription_feeds(rows, silent=True)

        failures = False
        for display_name, videos, exc in results:
            if exc is None and videos is not None:
                debug_log(2, f"Upserting {len(videos)} videos from {display_name} into database")
                self.store.upsert_videos(videos)
            else:
                failures = True

        if not channel_id and not failures:
            self.store.set_config("core", "last_refresh_time", utcnow().isoformat())

    def new(self, args: list[str]) -> None:
        debug_log(1, f"new command invoked with args: {args}")
        default_days_str = self.store.get_config("core", "new_days", "7")
        default_days = int(default_days_str) if (default_days_str and default_days_str.isdigit()) else 7

        days = default_days
        category = None
        if args:
            first = args[0].lower()
            if first == "default":
                if len(args) > 1:
                    new_default_str = args[1]
                    parsed_days = parse_days_token(new_default_str)
                    if parsed_days is None:
                        print("Usage: new default [DAYSd], example: new default 3d")
                        return
                    self.store.set_config("core", "new_days", str(parsed_days))
                    print(f"Default new duration set to {new_default_str}.")
                else:
                    print(f"Current default new duration is {default_days}d.")
                return

            parsed_days = parse_days_token(args[0])
            if parsed_days is not None:
                days = parsed_days
                if len(args) > 1:
                    category = " ".join(args[1:])
            else:
                category = " ".join(args)

        debug_log(2, f"Executing new command: days={days}, category={category!r}")
        if category:
            heading = f"New videos from category '{category}':"
        else:
            heading = "New videos from your subscriptions:"
        ctx = VideoListContext(purpose="new", heading=heading)

        if not self.addons.before_fetch(ctx):
            print("Video list request cancelled.")
            return

        self.refresh_silent()
        debug_log(2, "Fetching latest unwatched videos from store")
        videos = self.store.latest_videos(days=days, unwatched_only=True, category=category)
        debug_log(2, f"Fetched {len(videos)} raw videos from store")
        if not videos:
            if category:
                print(f"No new unwatched videos in category '{category}' in the last {days} days.")
            elif days == 7:
                print("No new unwatched videos in the last week.")
            else:
                print(f"No new unwatched videos in the last {days} days.")
            self.last_videos = []
            self.download.cache_video_list([])
            debug_log(2, "Invoking addons after_video_list hook for empty results")
            self.addons.after_video_list(ctx, [])
            return
        self._print_video_list(ctx, videos, empty_message="No new unwatched videos after filters.")

    def latest(self, args: list[str]) -> None:
        debug_log(1, f"latest command invoked with args: {args}")
        if not args:
            print("Usage: latest COUNT | DAYSd | COUNT CHANNEL_OR_CATEGORY")
            return

        limit: int | None = None
        days: int | None = None
        channel_spec: str | None = None

        first = args[0].lower()
        parsed_days = parse_days_token(first)
        if parsed_days is not None:
            days = parsed_days
            if len(args) > 1:
                channel_spec = " ".join(args[1:])
        elif first.isdigit():
            limit = int(first)
            if limit <= 0:
                print("COUNT must be positive.")
                return
            if len(args) > 1:
                channel_spec = " ".join(args[1:])
        else:
            print("Usage: latest COUNT | DAYSd | COUNT CHANNEL_OR_CATEGORY")
            return

        channel_id = None
        channel_label = None
        category = None
        if channel_spec:
            debug_log(2, f"Resolving channel/category spec: {channel_spec!r}")
            row = self.store.find_subscription(channel_spec)
            if row:
                channel_id = row["channel_id"]
                channel_label = row["handle"] or row["display_name"]
                debug_log(2, f"Resolved spec to channel ID: {channel_id} ({channel_label})")
            else:
                cats = {r["category"].lower() for r in self.store.list_channel_categories()}
                if channel_spec.lower() in cats:
                    category = channel_spec
                    debug_log(2, f"Resolved spec to category: {category}")
                else:
                    debug_log(1, f"No matching channel or category found for: {channel_spec!r}")
                    print(f"No matching subscription or category for {channel_spec!r}.")
                    return

        debug_log(2, f"Executing latest: limit={limit}, days={days}, channel_id={channel_id}, category={category!r}")
        if channel_id and limit is not None:
            heading = f"The {limit} latest videos from {channel_label} are:"
        elif channel_id and days is not None:
            heading = f"The latest videos from {channel_label} in the past {days} days are:"
        elif category and limit is not None:
            heading = f"The {limit} latest videos from category '{category}' are:"
        elif category and days is not None:
            heading = f"The latest videos from category '{category}' in the past {days} days are:"
        elif limit is not None:
            heading = f"The {limit} latest videos from your subscriptions are:"
        else:
            heading = f"The latest videos from your subscriptions in the past {days} days are:"

        ctx = VideoListContext(purpose="latest", heading=heading)

        if not self.addons.before_fetch(ctx):
            print("Video list request cancelled.")
            return

        self.refresh_silent(channel_id=channel_id)
        debug_log(2, "Fetching latest videos from store")
        videos = self.store.latest_videos(limit=limit, days=days, channel_id=channel_id, category=category)
        debug_log(2, f"Fetched {len(videos)} raw videos from store")
        if not videos:
            print("No videos found.")
            self.last_videos = []
            self.download.cache_video_list([])
            debug_log(2, "Invoking addons after_video_list hook for empty results")
            self.addons.after_video_list(ctx, [])
            return
        self._print_video_list(ctx, videos, empty_message="No videos found after filters.")

    def _print_video_list(self, ctx: VideoListContext, videos: list[Video], *, empty_message: str) -> None:
        debug_log(2, f"Applying addon filters to {len(videos)} videos")
        filtered = self.addons.apply_filters(ctx, videos)
        debug_log(2, f"Filtered videos count: {len(filtered)}")
        if not filtered:
            self.last_videos = []
            print(empty_message)
            self.download.cache_video_list([])
            debug_log(2, "Invoking addons after_video_list hook for empty filtered results")
            self.addons.after_video_list(ctx, [])
            return

        filtered = self.metadata.with_durations(filtered)
        debug_log(2, "Invoking addons before_video_list hook")
        if not self.addons.before_video_list(ctx, filtered):
            print("Video list request cancelled.")
            return

        self.last_videos = filtered

        # Cache last videos list for cross-process CLI watch calls
        debug_log(2, f"Caching {len(filtered)} list positions in database for watch shortcuts")
        self.store.delete_cache_prefix("core", "last_video:")
        for position, video in enumerate(filtered, 1):
            self.store.set_cache("core", f"last_video:{position}", video.video_id)

        print(ctx.heading)
        for i, video in enumerate(filtered, 1):
            title = self.addons.render_title(ctx, video, video.title).replace("\n", " ").strip()
            print(
                f'{i}. {video.channel_name} ({fmt_date(video.published_at)}): '
                f'"{title}" {fmt_duration(video.duration_seconds)} {video.share_url}'
            )
        self.download.cache_video_list(filtered)
        debug_log(2, "Invoking addons after_video_list hook")
        self.addons.after_video_list(ctx, filtered)

    def watch(self, args: list[str]) -> None:
        debug_log(1, f"watch command invoked with args: {args}")
        if not args:
            print("Usage: watch NUMBER [NUMBER...] | VIDEO_ID_OR_URL [...] | DATE+ | all")
            return

        import re
        from datetime import datetime, timezone

        # If last_videos is empty (e.g. separate process run), load from cache
        if not self.last_videos:
            debug_log(2, "last_videos cache empty in memory; loading list from database cache")
            position = 1
            while True:
                vid = self.store.get_cache("core", f"last_video:{position}")
                if not vid:
                    break
                video = self.store.get_video(vid)
                if video:
                    self.last_videos.append(video)
                position += 1
            debug_log(2, f"Loaded {len(self.last_videos)} videos from database position cache")

        # Check if they want to mark all videos from the last list as watched
        if len(args) == 1 and args[0].lower() == "all":
            if not self.last_videos:
                print("No listed videos to mark as watched.")
                return
            video_ids = [v.video_id for v in self.last_videos]
            debug_log(1, f"Marking all {len(video_ids)} listed videos as watched")
            self.store.mark_watched(video_ids)
            print(f"Marked all {len(video_ids)} listed videos as watched.")
            return

        # Check for DATE+ format (e.g. 2026-06-26+)
        date_cutoff_match = None
        for arg in args:
            if re.match(r"^\d{4}-\d{2}-\d{2}\+$", arg):
                date_cutoff_match = arg[:-1]
                break

        if date_cutoff_match:
            try:
                dt = datetime.strptime(date_cutoff_match, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                print(f"Invalid date format: {date_cutoff_match}. Expected YYYY-MM-DD+")
                return
            debug_log(1, f"Marking all videos published before {date_cutoff_match} as watched")
            count = self.store.mark_watched_before(dt)
            print(f"Marked {count} videos published before {date_cutoff_match} as watched.")
            return

        # Fallback to standard NUMBER / ID / URL parsing
        video_ids = []
        bad = []
        for arg in args:
            if arg.isdigit():
                idx = int(arg) - 1
                if 0 <= idx < len(self.last_videos):
                    video_ids.append(self.last_videos[idx].video_id)
                    debug_log(2, f"Resolved index {arg} to video ID: {self.last_videos[idx].video_id}")
                else:
                    debug_log(1, f"Out of range index in watch targets: {arg}")
                    bad.append(arg)
            else:
                video_id = extract_video_id(arg)
                if video_id:
                    video_ids.append(video_id)
                    debug_log(2, f"Resolved input {arg!r} to video ID: {video_id}")
                else:
                    debug_log(1, f"Could not parse watch input target: {arg!r}")
                    bad.append(arg)

        if bad:
            print("Could not resolve these watch targets: " + ", ".join(bad))
        if not video_ids:
            return
        debug_log(1, f"Marking {len(video_ids)} videos as watched in database")
        inserted = self.store.mark_watched(dict.fromkeys(video_ids).keys())
        if len(video_ids) == 1:
            print("Video added to watched" if inserted else "Video was already watched")
        else:
            joined = ", ".join(args)
            print(f"Videos {joined} added to watched")

    def purge(self, args: list[str]) -> None:
        debug_log(1, f"purge command invoked with args: {args}")
        days = 60
        if args:
            parsed_days = parse_days_token(args[0])
            if parsed_days is None:
                print("Usage: purge [DAYSd], example: purge 30d")
                return
            days = parsed_days

        debug_log(2, f"Executing database purge older than {days} days")
        v_count, w_count = self.store.purge_old_data(days)
        print(f"Purge complete. Removed {v_count} old video entries and {w_count} watched records older than {days} days.")
