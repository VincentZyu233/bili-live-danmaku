#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PORT=6161
OPEN_BROWSER=1
PASSTHROUGH=0

args=("$@")
for ((i = 0; i < ${#args[@]}; i += 1)); do
  case "${args[i]}" in
    --port)
      if ((i + 1 < ${#args[@]})); then
        PORT="${args[i + 1]}"
        i=$((i + 1))
      fi
      ;;
    --port=*)
      PORT="${args[i]#--port=}"
      ;;
    --no-browser)
      OPEN_BROWSER=0
      ;;
    -h|--help|--version)
      PASSTHROUGH=1
      ;;
  esac
done

ADMIN_URL="http://127.0.0.1:${PORT}/admin"
HEALTH_URL="http://127.0.0.1:${PORT}/api/config"

cd "$ROOT_DIR"

open_admin() {
  if command -v xdg-open >/dev/null 2>&1 && xdg-open "$ADMIN_URL" >/dev/null 2>&1; then
    return
  fi
  if command -v gio >/dev/null 2>&1 && gio open "$ADMIN_URL" >/dev/null 2>&1; then
    return
  fi
  if command -v open >/dev/null 2>&1 && open "$ADMIN_URL" >/dev/null 2>&1; then
    return
  fi
  printf 'Open in browser: %s\n' "$ADMIN_URL"
}

is_running() {
  if command -v curl >/dev/null 2>&1; then
    curl --fail --silent --show-error --max-time 2 "$HEALTH_URL" >/dev/null 2>&1
    return
  fi
  if command -v wget >/dev/null 2>&1; then
    wget --quiet --timeout=2 --output-document=/dev/null "$HEALTH_URL" >/dev/null 2>&1
    return
  fi
  return 1
}

if [ "$PASSTHROUGH" -eq 0 ] && is_running; then
  echo "Bili Live Danmaku is already running."
  if [ "$OPEN_BROWSER" -eq 1 ]; then
    open_admin
  else
    printf 'Admin URL: %s\n' "$ADMIN_URL"
  fi
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "[ERROR] uv was not found in PATH." >&2
  echo "Install uv: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [ "$PASSTHROUGH" -eq 0 ]; then
  echo "Starting Bili Live Danmaku on $ADMIN_URL"
fi
exec uv run bili-live-danmaku "$@"
