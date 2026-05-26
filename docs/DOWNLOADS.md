# Download Addon

The download addon wraps `yt-dlp` as a subprocess to handle downloading. It provides persistent storage and custom integration with SponsorBlock chaptering and removal.

## Core Commands

* **`download TARGET...`** (or alias **`dl TARGET...`**)
  Downloads one or more videos. Target can be:
  - List index numbers (e.g. `download 1 3 4`) from the last printed list.
  - Video IDs (e.g. `download dQw4w9WgXcQ`).
  - Full YouTube watch URLs.
* **`download on | off`**
  Enables or disables the download addon.
* **`download cfg`**
  Displays the current download settings and per-category SponsorBlock actions.
* **`download cfg help`**
  Displays help details for all configuration options.

---

## Configuration Settings

You can view or update settings using the `cfg` command:

### 1. Quality
Sets the maximum height limit selector for video downloads.
* **Command**: `download cfg quality [1080p | 720p | 480p | 1440p | 2160p | best]`
* **Default**: `1080p`
* **Format Mapping**:
  - `1080p` maps to `bv*[height<=1080]+ba/b[height<=1080]/best[height<=1080]`
  - `best` maps to `bv*+ba/b` (no height restriction)

### 2. Container format
Specifies the target file container.
* **Command**: `download cfg container [mkv | mp4 | webm]`
* **Default**: `mkv` (recommended because it reliably embeds chapters and metadata)

### 3. Auto Watch
Automatically marks successfully downloaded videos as watched in the database so they no longer appear in your `new` listings.
* **Command**: `download cfg auto_watch [on | off]`
* **Default**: `on`

---

## SponsorBlock Customization

SponsorBlock allows you to automatically skip or label sections of videos (like sponsor segments, intros, or interaction reminders).

Instead of a single global mode, you can configure **separate actions for each category**:
* **`cut`**: Completely removes/deletes the segment from the downloaded video.
* **`mark`**: Keeps the segment but adds it as a chapter marker (e.g. `[SponsorBlock]: Sponsor`).
* **`off`**: Does nothing (ignores the segment).

### Interactive Category Setup Wizard
To make configuration as simple as possible, launch the interactive wizard:
```text
download cfg sponsorblock
```
This wizard prompts you category-by-category to configure actions:
* `sponsor` (Sponsor segments)
* `intro` (Intro/Beginning animation)
* `outro` (Outro/End credits)
* `interaction` (Interaction reminders like subscribe/like)
* `selfpromo` (Self-promotion/Unpaid promotions)
* `preview` (Preview/Recap of the video)
* `filler` (Filler tangent/Joke/Off-topic)
* `music_offtopic` (Non-music section in music video)

---

## Output and Cache Storage

Downloads are saved under the configured downloads directory. Repository scripts and Docker use `./downloads/`; direct launches with `YTSUBS_PROJECT_ROOT` use that root's `downloads/` directory. The output layout is:
```text
<downloads>/<uploader>/<upload_date>_<title>_[<video_id>].<ext>
```
To maintain isolation and avoid conflicts with user-global configs, the addon invokes `yt-dlp` using `--ignore-config` and uses the configured application cache directory.
