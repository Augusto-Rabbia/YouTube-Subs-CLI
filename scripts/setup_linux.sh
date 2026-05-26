#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Keep tool-created state inside this project folder.
mkdir -p .cache data .config mods downloads
export PIP_CACHE_DIR="$PWD/.cache/pip"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg not found. It is required for merging, metadata, chapters, and SponsorBlock cutting." >&2
  if [ "${YTSUBS_SKIP_SYSTEM_DEPS:-0}" != "1" ] && command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y ffmpeg
  else
    echo "Install ffmpeg with your system package manager, or rerun with YTSUBS_SKIP_SYSTEM_DEPS=1 to skip this check." >&2
  fi
fi

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cat <<'MSG'
Setup complete.

Run:
  ./scripts/run_linux.sh

Project-local state:
  ./data/ytsubs.sqlite3
  ./.venv/
  ./.cache/
  ./.config/
  ./mods/
  ./downloads/
MSG
