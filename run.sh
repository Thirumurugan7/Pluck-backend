#!/usr/bin/env bash
# Start the yt2mp3 backend on localhost only.
set -euo pipefail

cd "$(dirname "$0")"

# Prefer a local virtualenv if present.
if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "warning: ffmpeg not found. Install with: brew install ffmpeg" >&2
fi

exec uvicorn main:app --host 127.0.0.1 --port 8000
