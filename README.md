# YTSubs-cli

**Follow YouTube on your terms.**

`YTSubs-cli` is a calm, local-first subscription inbox for people who want the channels they chose without the homepage, recommendations, Shorts rabbit holes, or algorithmic pressure. Open a terminal, see what your subscriptions published, mark what you have handled, and leave.

It gives you a deliberate way to use YouTube:

- View new or recent uploads as a clean, readable list.
- Organize channels into separate profiles and meaningful categories.
- Filter distractions such as unwanted titles or Shorts.
- Download videos for offline viewing with metadata and SponsorBlock options.
- Set focus hours that make browsing available only when you decided it should be.
- Keep your subscription workflow local, lightweight, and under your control.

## Why ytsubs-cli?

- **An inbox, not a feed**: `new` and `latest` show subscribed uploads directly, with timestamps, duration, and watched tracking.
- **Your own organization**: Profiles separate contexts such as study and entertainment; categories let you query only what matters right now.
- **Attention controls built in**: `focus` supports delays, daily access windows, and an optional invincible mode for commitments you cannot immediately undo.
- **Less clickbait and noise**: Filter titles and Shorts, or use Anti-Clickbait with DeArrow API community titles and optional Shift Caps formatting. Consider supporting the DeArrow project if you use it.
- **Take videos with you**: Download selected items with embedded metadata, chapters, quality controls, and optional SponsorBlock processing.
- **Private by default**: It works locally from public YouTube data and does not require browser sign-in or an API key.

The result is still YouTube, but shaped into a finite queue you can intentionally check and close.

## Requirements

* Docker (Recommended)
* Or Linux/macOS with Python 3.10+ and `ffmpeg` (for Non-Docker setup)

---

## Quickstart (Docker)

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

## Alternative Setup (Linux/macOS)

If you prefer to run the application natively on Unix:

```bash
# Setup virtual environment and dependencies
./scripts/setup_linux.sh

# Run interactive shell
./scripts/run_linux.sh

# Run commands directly
./scripts/run_linux.sh latest 5
```

## Guided Setup

On first launch, YTSubs starts an interactive setup wizard. It asks for your comma-separated channel list first, then resolves those channels in the background while you configure downloads and choose addons. After configuration questions, it tells you when a channel name produced multiple matches and lets you select each subscription explicitly.

The wizard can configure:

- subscriptions entered as `@handles`, channel IDs, URLs, or plain-text channel names;
- downloads, including destination folder, video container, quality, watched tracking, and SponsorBlock actions;
- Shorts/title filtering and Anti-Clickbait title display;
- focus delays, weekly access schedules, and optional invincible mode.

Run `setup` later to revisit the wizard; because it can alter existing settings, rerunning it requires typing `ok` first.

Downloading is built into the application and can be reconfigured independently with `download setup`. Each optional addon owns its guided configuration and can be configured independently with `title-filter setup`, `anti-clickbait setup`, or `focus setup`.

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

# Export subscriptions to the default persisted file
> sub export
```

The default OPML export is saved under `./data/ytsubs_subscriptions.opml` on the host. In Docker command output this mounted file is shown as `/app/data/ytsubs_subscriptions.opml`.

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

Downloads can be stored in a directory you choose:
```text
> download cfg directory downloads/courses
> download cfg container mp4
> download cfg quality 1080p
```

In Docker, keep configured download destinations under `downloads/` so they are available in the mounted host folder.

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

### 6. Focus Schedules
The `focus` addon can delay video lists and restrict commands that show videos or operate on subscriptions. Times use the machine's local time. A day without a configured schedule is unrestricted.
```text
# Turn on focus behavior and cancel a requested list when a key is pressed during its delay
> focus on
> focus cfg seconds 45

# Monday through Thursday: permit access only from 16:00-18:00 and 20:00-21:00
> focus schedule set mon-thu allow 16:00-18:00,20:00-21:00

# Optional alternative: block a specific window instead of declaring allowed windows
> focus schedule set fri block 09:00-17:00

# Remove restrictions from Friday through Sunday
> focus schedule clear fri-sun
```

Protected actions are `sub`, `setup`, `new`, `latest`, `watch`, `refresh`, and `download`/`dl`. Configuration and help commands remain available.

**Invincible mode**: Be in control of your own life. When on, your focus settings will be impulse-safe: Any changes will take effect only at 05:00 local time on the following day. Configure the intended schedule before confirming invincible mode.

## Addons

You can create and install any number of addons to suit your own needs. You are in control. 

*Warning*: External addons are Python code executed inside this process. Only install addons you trust.

## Documentation

For details on extending the app or fine-tuning its configurations, see the following documentation:
* [Addon Development Guide](docs/ADDONS.md) - Learn how to write your own pipeline hooks, filter routines, or new commands.
* [App Architecture Details](docs/ARCHITECTURE.md) - Understand how the core orchestrator, SQLite database store, and feed checkers interact.
* [Downloader Configuration Guide](docs/DOWNLOADS.md) - Deep dive on configuring `yt-dlp` download paths, SponsorBlock cut/mark modes, container formats, and quality settings.

## License

MIT. See [`LICENSE`](LICENSE).
