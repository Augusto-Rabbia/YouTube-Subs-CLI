#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Keep runtime-created state inside this project folder.
mkdir -p .cache data .config mods downloads

if [ ! -x .venv/bin/python ]; then
  echo "Virtualenv not found. Run ./scripts/setup_linux.sh first." >&2
  exit 1
fi
. .venv/bin/activate
exec python -m ytsubs "$@"
