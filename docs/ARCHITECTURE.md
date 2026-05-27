# Architecture Details

This document outlines the core architecture, data flows, and design patterns used in the `ytsubs-cli` application.

## Design Goals

- **Purposeful Core**: Keep essential subscription and offline-viewing workflows integrated; delegate optional display and attention behaviors to addons.
- **Uniform Mod System**: Built-in addons and external mods share setup, command metadata, access-control, and rendering hook contracts.
- **Local Isolation**: Script and Docker executions keep state inside the project directory; `YTSUBS_PROJECT_ROOT` selects another portable storage root when needed.
- **Speed**: Run feed fetches in parallel and leverage micro-caches to avoid redundant API or network requests.

---

## Runtime Data Pipeline

```text
CLI command (cli.py)
-> App command dispatcher (app.py)
-> Parallel YouTube RSS feed fetches (youtube.py) (uses threads & 10m cache rate-limits)
-> Store query & video caching (store.py)
-> Apply addon filters (title regex, Shorts checks)
-> Resolve and cache missing durations for displayed videos (metadata.py / youtube.py)
-> Run before list hooks (focus countdowns can cancel rendering)
-> Run title renderer hooks (Anti-Clickbait replacement via the DeArrow API and optional Shift Caps formatting)
-> Print list output
-> Cache displayed indices for core watch/download shortcuts
-> Run after list hooks for addon-owned behavior
```

---

## Component Boundaries

### 1. `ytsubs.cli`
Owns terminal shell loop, command tokenization using `shlex`, interactive commands via Python's standard `cmd.Cmd`, first-run setup entry, dynamic help rendering, version reporting, and profile bootstrapping. Addon-specific help is provided by addons rather than encoded in the shell.

### 2. `ytsubs.core.app`
Orchestrates commands (sub, profiles, category management, new/latest, watch, purge) and manages the database connection lifecycle. It coordinates the `Store`, the `YouTubeClient` fetcher, the metadata enrichment service, and the `AddonManager`.

### 3. `ytsubs.core.download`
Owns built-in offline viewing: `download`/`dl` commands, destination and format settings, SponsorBlock options, and displayed-list index mapping for download shortcuts. It uses the persistent `download` configuration namespace without participating in addon discovery or enablement.

### 4. `ytsubs.core.configuration`
Writes and restores portable JSON configuration exports containing subscriptions, categories, core preferences, and built-in download preferences. Addon sections remain opaque: this service delegates them to `AddonManager`, which invokes each addon's own snapshot hooks.

### 5. `ytsubs.core.store`
Manages the SQLite database operations, schema migrations, configurations, and cache writes.
**Tables**:
* `subscriptions`: Track channel IDs, handles, titles, and added dates.
* `videos`: Cache fetched video uploads.
* `watched`: Log watched video IDs and watch timestamps.
* `channel_categories`: Maps channel IDs to user-defined categories (cascades on subscription deletions).
* `video_metadata`: Caches duration metadata independently from RSS feed records.
* `addon_state`: Track enabled/disabled status of addons.
* `addon_config`: Save persistent key-value configuration values.
* `addon_cache`: Cache transient keys (e.g. Shorts HEAD statuses, Anti-Clickbait/DeArrow-source metadata, numbered list cache position mappings).
* `channel_search_results`: Cache temporary channel searches.

### 6. `ytsubs.core.youtube`
Manages network connections and parsing of YouTube details:
* Queries YouTube's XML RSS feed URLs using fast built-in `urllib` HTTP GET requests.
* **Parallel processing**: Launches channel fetches concurrently using a `ThreadPoolExecutor` (capping at 10 worker threads) to speed up loading times.
* **Failover Fallback**: If the standard RSS feed returns HTTP errors (e.g. `404` or `500`), the client falls back to running `yt-dlp` flat extraction on the channel's web page, extracting strictly the top 30 videos (`playlist_items: "1-30"`) to maintain high speeds.
* Resolves metadata absent from RSS, such as video duration, on demand for the metadata service.

### 7. `ytsubs.core.metadata`
Enriches videos that will be printed with metadata unavailable from RSS, currently duration. Values are persisted in `video_metadata`, so `yt-dlp` lookups are generally paid only once per video; unresolved durations are retried after a short cooldown.

### 8. `ytsubs.core.addons`
Discovers Python addon files from the shipped addon package and configured mods directory, then handles their invocation order. `BaseAddon` supplies generic enable/disable, configuration, setup, command-access, help metadata, and isolated storage extension points. Commands declare whether an action consumes restricted content access; policy addons such as `focus` enforce that declaration without depending on other addon command names.

### 9. `ytsubs.core.setup`
Runs only the application-level first-launch and `setup` workflow. It first offers to restore a portable configuration export. For manual configuration, channel resolution starts immediately after channel entry and continues concurrently while core download preferences are configured and each discovered addon is presented using its `name` and `description` and invoked through `addon.setup(...)`. When setup questions have finished, ambiguous channel-name results are presented for explicit user selection.

---

## Storage Directory Layout

Repository scripts and the Docker setup explicitly use a portable project-root layout:
```text
./data/                       # SQLite databases and default OPML exports
./downloads/                  # default media output, created by the built-in downloader when used
./mods/                       # custom external addons
./.venv/                      # Python virtualenv (for native runs)
./.cache/                     # yt-dlp cache and temp folder
./.config/                    # active profile preferences
```

Direct source execution can select an alternative portable root:
```text
YTSUBS_PROJECT_ROOT=/some/path python -m ytsubs
```
The same `data/`, `mods/`, `.cache/`, and `.config/` layout is then created below that root; the built-in downloader creates its `downloads/` default output there when it is configured or used. Profile names are validated before a database path is created, and all modules obtain shared runtime locations through `ytsubs.core.paths`.
