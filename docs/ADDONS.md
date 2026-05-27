# Addon Development Guide

Addons allow you to extend the application's CLI commands and hook into the video listing rendering pipelines.

External mods are loaded only from the configured application mods directory. This is `./mods/` for the repository/Docker setup, or `<YTSUBS_PROJECT_ROOT>/mods/` when an alternate portable root is configured.

## Addon Contract

An addon is a single Python module located inside `./ytsubs/addons/` (shipped addon) or `./mods/` (user-installed addon). Both directories are discovered automatically; adding a new addon requires adding only its `.py` file. The module must export a `create_addon` entrypoint:

```python
def create_addon(store):
    return YourAddon(store)
```

The returned object must inherit from `BaseAddon`.

```python
from ytsubs.core.addons import BaseAddon, SetupPrompts

class YourAddon(BaseAddon):
    name = "your-addon"
    description = "A brief summary of what this addon does."
    default_enabled = False

    def setup(self, ui: SetupPrompts) -> None:
        if not self.setup_enabled(ui):
            return
        value = ui.input("  Option value [default]: ").strip() or "default"
        self.store.set_config(self.name, "option1", value)
```

The global application setup enumerates installed addons through `name` and `description` and calls `addon.setup(ui)`. It does not require an addon-specific core change. `BaseAddon.setup` already supplies a simple enable/disable prompt; override it only when the addon has additional questions.

The manager also guarantees a `<name> setup` command. If the addon does not register a command named after itself, that setup entrypoint is provided automatically. If it does register its own named command, the manager reserves its `setup` action for `addon.setup(ui)` and passes the remaining actions to the addon handler.

## Portable Configuration Hooks

Application-level `config export` does not inspect addon configuration. It calls hidden addon hooks to obtain and later restore each addon's opaque snapshot:

```python
def export_config_snapshot(self) -> dict[str, object]:
    return {"enabled": self.enabled, "config": {"option1": "value"}}

def import_config_snapshot(self, payload: object, ui: SetupPrompts) -> None:
    # Validate and restore this addon's own data.
    ...
```

`BaseAddon` implements these hooks for standard addons that use their own namespaced `addon_state` and `addon_config` values. Override them when an addon stores data in private files, a private database, another persistence namespace, or has import-time safety requirements. The core exporter treats addon snapshots as opaque data and does not know any addon-specific keys.

## Command Standard Configuration Pattern

To keep command interfaces clean and consistent for the user, all addons should follow the standardized configuration pattern:
`[command] on|off|setup|cfg [help|KEY VALUE]`

Here is how you can implement this in your `command` handler:

```python
def register_commands(self, registry):
    registry.command("your-addon", self.command, "your-addon on|off|setup|cfg [help|KEY VALUE]", addon_name=self.name)

def command(self, args):
    if not args:
        # Print status
        enabled = self.store.is_addon_enabled(self.name, self.default_enabled)
        print(f"YourAddon: {'enabled' if enabled else 'disabled'}")
        return

    action = args[0].lower().strip()
    if action in {"on", "enable"}:
        self.enable()
    elif action in {"off", "disable"}:
        self.disable()
    elif action == "setup":
        self.run_setup_command(args[1:])
    elif action == "cfg":
        # Handle configuration viewing or settings
        if len(args) == 1:
            print("YourAddon Config:")
            print(f"  option1 = {self.store.get_config(self.name, 'option1', 'default')}")
            return
        # Parse KEY VALUE configuration updates
        ...
```

For commands that perform the add-on's functional action while also supporting configuration commands, gate the action with the shared enablement helper:

```python
if not self.require_enabled("yourcommand"):
    return
```

Configuration and `on` commands can remain available while an add-on is disabled; active behavior should not run until it is enabled.

---

## Help And Access Metadata

Detailed CLI help belongs with the addon:

```python
help_details = {
    "your-addon": {
        "summary": "Describe this addon.",
        "usage": "your-addon on|off|setup|cfg [help|KEY VALUE]",
        "details": "  - your-addon setup - Run guided setup.",
        "examples": ["your-addon setup"],
    },
}
```

If a command performs an action that should be blocked by access-policy addons such as `focus`, declare it during registration. Settings commands stay available:

```python
def register_commands(self, registry):
    registry.command(
        "your-addon",
        self.command,
        "your-addon ITEM|setup|cfg [KEY VALUE]",
        addon_name=self.name,
        access_controlled=lambda args: bool(args) and args[0] not in {"setup", "cfg", "on", "off"},
    )
```

An addon that implements an access policy overrides `command_allowed(command, args, access_controlled)`. It should use the supplied classification rather than knowing other addons' command names.

---

## Video-List Hooks

Addons can inject logic at different points of the video display pipeline:

### 1. Filter Videos (`filter_videos`)
Filter out or reorder videos before they are displayed.
```python
def filter_videos(self, ctx, videos):
    # Hide videos that contain clickbait terms
    return [v for v in videos if "unboxing" not in v.title.lower()]
```

### 2. Before Video List (`before_video_list`)
Runs immediately before the video list is outputted to the terminal (e.g. countdown timers, delays). Return `False` to cancel rendering; returning `None` or `True` lets the list proceed.
```python
def before_video_list(self, ctx, videos):
    if not confirm_display(videos):
        return False
    print(f"Listing {len(videos)} videos:")
    return True
```

### 3. Title Renderer (`render_title`)
Modifies the displayed title string without changing the original title stored in the database (e.g. clickbait translation).
```python
def render_title(self, ctx, video, current_title):
    return current_title.upper()
```

### 4. After Video List (`after_video_list`)
Runs after the list has completed rendering. Excellent for mapping list positions to video IDs in a cache.
```python
def after_video_list(self, ctx, videos):
    self.store.delete_cache_prefix(self.name, "last_video:")
    for position, video in enumerate(videos, 1):
        self.store.set_cache(self.name, f"last_video:{position}", video.video_id)
```

---

## Storage & Persistence

Addons have access to both shared and private storage utilities:

### 1. Namespaced Shared Tables (Configs & Caches)
To store simple settings or caches without altering the main database schema, use the namespaced core APIs:
```python
# Permanent settings (addon_config table)
self.store.set_config(self.name, "option1", "value")
self.store.get_config(self.name, "option1", default="default")

# Temporary caches (addon_cache table)
self.store.set_cache(self.name, "cache_key", "value")
self.store.get_cache(self.name, "cache_key")
```

### 2. Isolated Sandboxed Directories
For complex files, downloads, or custom logs, `BaseAddon` exposes three private directory properties:
* `self.data_dir`: Persistent add-on data below the configured app data directory.
* `.cache_dir`: Temporary add-on data below the configured cache directory.
* `.config_dir`: Add-on settings below the configured app config directory.

*Note: The app automatically ensures these directories exist on disk before returning their paths.*

### 3. Isolated SQLite Database
If your addon requires complex relational tables, **do not execute DDL commands (like `ALTER TABLE`) on the core database.** Instead, initialize your own private database engine inside your sandbox folder:
```python
# Returns a pre-configured sqlite3.Connection (WAL journal, foreign keys enabled)
# pointing to <configured-data-dir>/addons/<addon_name>/storage.sqlite3
conn = self.open_addon_db()
with conn:
    conn.execute("CREATE TABLE IF NOT EXISTS history (...)")
```

---

## Installing Custom Addons

1. Place your Python addon file in the configured mods directory. No import list, CLI help registration outside that file, or setup-wizard change is needed. For the standard repository/Docker setup:
   ```text
   ./mods/custom_filter.py
   ```
   With `YTSUBS_PROJECT_ROOT`, place it under that root's `mods/` directory.
2. If running locally from this repository, restart the application:
   ```bash
   ./scripts/run_linux.sh
   ```
3. If running via Docker, restart your container. Volume mapping automatically loads mods from the host `./mods/` folder.
   ```bash
   docker compose run --rm ytsubs
   ```

---

## Security Warning

Addons are executed directly as Python code in the core process. Only install addons from sources you trust.
