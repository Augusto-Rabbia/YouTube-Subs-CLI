#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Keep tool-created state inside this project folder.
mkdir -p .cache data .config mods downloads
export YTSUBS_UID="${YTSUBS_UID:-$(id -u)}"
export YTSUBS_GID="${YTSUBS_GID:-$(id -g)}"

echo "Building Docker image..."
docker compose build
echo "Docker image built successfully."

cat <<'MSG'

Run:
  ./scripts/run_docker.sh

Project-local state (mounted in Docker):
  ./data/
  ./.cache/
  ./.config/
  ./mods/
  ./downloads/
MSG
