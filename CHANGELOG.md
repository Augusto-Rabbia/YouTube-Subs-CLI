# Changelog

## Unreleased

- Renamed `focus-delay` to `focus` and expanded it with cancel-on-key delays, per-day allow/block schedules, and an invincible mode that defers protected changes until the following day at 05:00 local time.
- Saved default subscription OPML exports under the persisted `data/` directory so Docker users can export without writing to `/app`.
- Added a first-launch and rerunnable `setup` wizard that resolves requested subscriptions while configuring addons.
- Added configurable download output folders and stopped generating `*.info.json` sidecar files for downloads.
- Refactored setup, help metadata, access control, discovery, and addon-specific storage around addon-owned interfaces; adding an addon now requires only its `.py` file.
- Promoted downloading from an addon into built-in app functionality with integrated commands, setup, help, and list-index handling.
- Added optional `shift-caps` title capitalization to the DeArrow addon.

## 0.4.0 - 2026-05-26

- Restricted profile identifiers to safe database filename components.
- Confined application state to a configured portable root and removed package-distribution assumptions.
- Stopped treating fallback feed entries without trustworthy dates as newly published videos.
- Enforced disabled state for download actions.
- Changed the Docker setup to run the CLI without root privileges.
- Added cached duration display and compact `youtu.be` video-list links.
- Added standard version reporting and corrected refresh/duration retry bookkeeping.
- Switched native and Docker launch paths to run source directly through `python -m ytsubs`.

## 0.3.0

- Added `download` addon.
- Added SponsorBlock mark/cut modes through `yt-dlp`.
- Added embedded metadata and chapter support for downloads.
- Added configurable download quality.
- Added project-local `./downloads/` directory.
- Added `after_video_list` addon hook.
- Added GitHub-oriented documentation.

## 0.2.0

- Added addon manager.
- Added built-in focus delay, title filter, and DeArrow addons.
- Added external `./mods/*.py` loading.

## 0.1.0

- Initial local subscription CLI.
