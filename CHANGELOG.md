# Changelog

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
