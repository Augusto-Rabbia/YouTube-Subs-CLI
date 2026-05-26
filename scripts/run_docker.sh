#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Keep runtime-created state inside this project folder.
mkdir -p .cache data .config mods downloads
export YTSUBS_UID="${YTSUBS_UID:-$(id -u)}"
export YTSUBS_GID="${YTSUBS_GID:-$(id -g)}"

exec docker compose run --rm ytsubs "$@"
