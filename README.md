# ytsubs-cli

A local, terminal-first YouTube subscription tracker with profile support, channel categories, and an addon system.

The app keeps its own local subscription profiles, fetches public YouTube channel RSS feeds, lists new/latest videos with exact hours and minutes, tracks watched status, and lets addons modify behavior without changing the core command layer.

This application is distributed to run from its source checkout or Docker image, rather than as a Python package. Application state stays in this project directory by default; set `YTSUBS_PROJECT_ROOT` when launching `python -m ytsubs` directly to choose a different portable state root.


## Features

- **Profiles**: Run isolated, multiple subscription environments (e.g. `gaming`, `work`, `default`) with separate databases.
- **Categories**: Label subscriptions into custom tags (e.g. `Tech`, `Gaming`) and filter feeds by category.
- **No browser or API keys**: Fetches public feeds and runs completely locally.
- **Micro-caching**: Resolves and caches video durations, Shorts status, and position indices locally for faster rendering.
- **Configurable new duration**: Custom settings to change the definition of how old "new" videos can be.
- **Addon system**: Command extensions and hook overrides.
- **Built-in addons**:
  - `focus-delay`: delay video list display for focused watching.
  - `title-filter` / `filter`: regex filter titles and toggle YouTube Shorts filtering.
  - `dearrow`: replace clickbait titles with DeArrow community titles.
  - `download`: download videos with metadata, SponsorBlock support, and quality selectors.


## Requirements

* Docker (Recommended)
* Or Linux/macOS with Python 3.10+ and `ffmpeg` (for Non-Docker setup)

---

## Quickstart (Easiest via Docker)

Running with Docker is the recommended setup. It works out-of-the-box on **Windows, macOS, and Linux**, handling Python and `ffmpeg` dependencies automatically.

### 1. Build the Docker Image
```bash
./scripts/setup_docker.sh
```

### 2. Start the Interactive Shell
```bash
./scripts/run_docker.sh
```
*Your database, cache, configurations, add-ons, and video downloads automatically persist inside local `./data/`, `./.cache/`, `./.config/`, `./mods/`, and `./downloads/` folders. The container runs without root privileges and uses your host user ownership for these mounted directories.*

### 3. Run a Command Directly (Non-Interactive)
```bash
./scripts/run_docker.sh latest 5
./scripts/run_docker.sh --profile gaming new
```

---

## Alternative Setup (Non-Docker, Linux/macOS)

If you prefer to run the application natively on Unix:

```bash
# Setup virtual environment and dependencies
./scripts/setup_linux.sh

# Run interactive shell
./scripts/run_linux.sh

# Run commands directly
./scripts/run_linux.sh latest 5
```

## Usage Tutorial

This tutorial demonstrates the main workflows in `ytsubs-cli`.

### 1. Managing Profiles
Profiles allow you to maintain completely separate subscription environments. Profile names accept letters, numbers, `-`, and `_`, up to 64 characters.
```text
# Check your current profile (default is "default")
> profile current
Current profile: default

# List all profiles
> profile list
 * default

# Create and switch to a new "gaming" profile
> profile switch gaming
Switched to profile 'gaming'.

# Verify the list is now empty and active
> profile list
   default
 * gaming
```

### 2. Managing Subscriptions
Add channels using handles, feed URLs, channel IDs, or via built-in search.
```text
# Search YouTube for a channel
> sub search dude perfect
1. Dude Perfect @dudeperfect UC2Y5...
2. Dude Perfect Plus @dudeperfectplus UC21...

# Add by search index number
> sub add 1
Sub added successfully!

# Add directly by handle
> sub add @3blue1brown
Sub added successfully!

# List subscriptions (rendered cleanly with display names and handles)
> sub list
Current subscriptions:
Dude Perfect (@dudeperfect)
3Blue1Brown (@3blue1brown)
```

### 3. Subscription Categories & Filtering
Categories let you group channels and filter feed outputs.
```text
# Tag 3Blue1Brown as "Math"
> sub category add @3blue1brown Math
Added category 'Math' to subscription '3Blue1Brown'.

# Tag Dude Perfect as "Sports"
> sub category add @dudeperfect Sports
Added category 'Sports' to subscription 'Dude Perfect'.

# List category mappings
> sub category list
Channel categories:
  Math:
    - 3Blue1Brown (@3blue1brown)
  Sports:
    - Dude Perfect (@dudeperfect)

# View new unwatched videos in "Math" category
> new Math
New videos from category 'Math':
1. 3Blue1Brown (2026-05-25 15:00): "Thinking visual about calculus" 15m30s https://youtu.be/...

# View 5 latest videos in "Sports" category
> latest 5 Sports
```

### 4. Advanced Feeding & Toggles
```text
# Change default "new" search window from 7 days to 14 days
> new default 14d
Default new duration set to 14d.

# Filter out YouTube Shorts from feed outputs (uses parallel HTTP resolution and caching)
> filter cfg filter_shorts on
Set title-filter.filter_shorts = on

# View new feed (automatically filters out shorts and uses the 14-day default)
> new
```

### 5. Marking Videos as Watched
Track read status to keep your feed clean.
```text
# Mark list numbers 1 and 2 as watched
> watch 1 2

# Mark all currently listed videos as watched at once
> watch all

# Instantly consider everything published before June 26, 2026 as watched
> watch 2026-06-26+
Marked 68 videos published before 2026-06-26 as watched.
```

## Core commands

```text
sub list
sub add @Handle | URL | CHANNEL_ID | NUMBER
sub search search terms
sub rm @Handle-or-name-or-channel-id
sub category list | add <channel> <category> | rm <channel> <category>
sub import FILE | sub export [FILE]
profile list | switch NAME | create NAME | current | backup [NAME] | restore NAME | backups
new [DAYSd] | new default [DAYSd]
latest COUNT | latest DAYSd | latest COUNT CHANNEL_OR_CATEGORY
watch NUMBER [NUMBER...] | VIDEO_ID_OR_URL [...] | DATE+ | all
w NUMBER [NUMBER...] | VIDEO_ID_OR_URL [...] | DATE+ | all
refresh
addon list | enable NAME | disable NAME | set NAME KEY VALUE | config NAME
purge [DAYSd]
debug [on|off|0|1|2]
quit
```

Global options: `--profile NAME`, `--help`, and `--version`.

## Repository layout

```text
ytsubs/
  cli.py                  interactive shell and one-shot command runner
  core/
    app.py                application command orchestration
    addons.py             addon registry, loader, and hook pipeline
    metadata.py           cached video metadata enrichment
    models.py             domain dataclasses
    paths.py              portable and user-scoped runtime paths
    store.py              SQLite persistence
    youtube.py            YouTube RSS and yt-dlp integration
    util.py               parsing helpers
  addons/
    dearrow.py
    download.py
    focus_delay.py
    title_filter.py       title regexes & YouTube shorts filtering
mods/
  example_addon.py.disabled
docs/
  ADDONS.md
  ARCHITECTURE.md
  DOWNLOADS.md
```

## Security model

External addons are Python code executed inside this process. Only install addons you trust.

## Documentation

For details on extending the app or fine-tuning its configurations, see the following documentation:
* [Addon Development Guide](docs/ADDONS.md) - Learn how to write your own pipeline hooks, filter routines, or new commands.
* [App Architecture Details](docs/ARCHITECTURE.md) - Understand how the core orchestrator, SQLite database store, and feed checkers interact.
* [Downloader Configuration Guide](docs/DOWNLOADS.md) - Deep dive on configuring `yt-dlp` download paths, SponsorBlock cut/mark modes, container formats, and quality settings.

## License

MIT. See [`LICENSE`](LICENSE).
