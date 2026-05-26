# Architecture Details

This document outlines the core architecture, data flows, and design patterns used in the `ytsubs-cli` application.

## Design Goals

- **Small Core**: Keep the CLI and storage layer simple; delegate advanced behaviors (downloads, custom clickbait filtering) to addons.
- **Uniform Mod System**: Built-in addons and external mods share the same factory contract and hook pipelines.
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
-> Run before list hooks (focus countdowns)
-> Run title renderer hooks (DeArrow clickbait replacement)
-> Print list output
-> Run after list hooks (updates cached indices for watch/download shortcuts)
```

---

## Component Boundaries

### 1. `ytsubs.cli`
Owns terminal shell loop, command tokenization using `shlex`, interactive commands via Python's standard `cmd.Cmd`, dynamic help documentation summaries, version reporting, and profile bootstrapping. It is decoupled from network fetching, databases, and addon loading.

### 2. `ytsubs.core.app`
Orchestrates commands (sub, profiles, category management, new/latest, watch, purge) and manages the database connection lifecycle. It coordinates the `Store`, the `YouTubeClient` fetcher, the metadata enrichment service, and the `AddonManager`.

### 3. `ytsubs.core.store`
Manages the SQLite database operations, schema migrations, configurations, and cache writes.
**Tables**:
* `subscriptions`: Track channel IDs, handles, titles, and added dates.
* `videos`: Cache fetched video uploads.
* `watched`: Log watched video IDs and watch timestamps.
* `channel_categories`: Maps channel IDs to user-defined categories (cascades on subscription deletions).
* `video_metadata`: Caches duration metadata independently from RSS feed records.
* `title_filters`: Store regex title exclusion rules.
* `addon_state`: Track enabled/disabled status of addons.
* `addon_config`: Save persistent key-value configuration values.
* `addon_cache`: Cache transient keys (e.g. Shorts HEAD statuses, DeArrow metadata, numbered list cache position mappings).
* `channel_search_results`: Cache temporary channel searches.

### 4. `ytsubs.core.youtube`
Manages network connections and parsing of YouTube details:
* Queries YouTube's XML RSS feed URLs using fast built-in `urllib` HTTP GET requests.
* **Parallel processing**: Launches channel fetches concurrently using a `ThreadPoolExecutor` (capping at 10 worker threads) to speed up loading times.
* **Failover Fallback**: If the standard RSS feed returns HTTP errors (e.g. `404` or `500`), the client falls back to running `yt-dlp` flat extraction on the channel's web page, extracting strictly the top 30 videos (`playlist_items: "1-30"`) to maintain high speeds.
* Resolves metadata absent from RSS, such as video duration, on demand for the metadata service.

### 5. `ytsubs.core.metadata`
Enriches videos that will be printed with metadata unavailable from RSS, currently duration. Values are persisted in `video_metadata`, so `yt-dlp` lookups are generally paid only once per video; unresolved durations are retried after a short cooldown.

### 6. `ytsubs.core.addons`
Loads Python extension files from the configured mods directory and handles the invocation order (built-ins first, then external mods alphabetically).

---

## Storage Directory Layout

Repository scripts and the Docker setup explicitly use a portable project-root layout:
```text
./data/                       # SQLite databases (e.g. ytsubs.sqlite3)
./downloads/                  # downloaded media files (used by download addon)
./mods/                       # custom external addons
./.venv/                      # Python virtualenv (for native runs)
./.cache/                     # yt-dlp cache and temp folder
./.config/                    # active profile preferences
```

Direct source execution can select an alternative portable root:
```text
YTSUBS_PROJECT_ROOT=/some/path python -m ytsubs
```
The same `data/`, `downloads/`, `mods/`, `.cache/`, and `.config/` layout is then created below that root. Profile names are validated before a database path is created, and all modules obtain runtime locations through `ytsubs.core.paths`.
