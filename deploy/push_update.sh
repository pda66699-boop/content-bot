#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-116.203.132.170}"
REMOTE_USER="${REMOTE_USER:-root}"
APP_ROOT="${APP_ROOT:-/opt/content-bot}"
REMOTE_APP_DIR="$APP_ROOT/app"
SERVICE_NAME="${SERVICE_NAME:-content-bot-polling}"

rsync -az --delete \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'memory/telegram_ingest.sqlite3' \
  --exclude 'memory/telegram_polling_offset.json' \
  --exclude 'memory/telegram_ui_state.json' \
  --exclude 'memory/raw_updates/' \
  ./ "${REMOTE_USER}@${HOST}:${REMOTE_APP_DIR}/"

ssh "${REMOTE_USER}@${HOST}" \
  "APP_ROOT='${APP_ROOT}' SERVICE_NAME='${SERVICE_NAME}' bash '${REMOTE_APP_DIR}/deploy/install_remote.sh'"
