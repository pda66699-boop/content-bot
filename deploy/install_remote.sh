#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/content-bot}"
APP_DIR="$APP_ROOT/app"
DATA_DIR="$APP_ROOT/data"
SHARED_DIR="$APP_ROOT/shared"
SERVICE_NAME="${SERVICE_NAME:-content-bot-polling}"
SERVICE_USER="${SERVICE_USER:-contentbot}"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$APP_DIR" "$DATA_DIR/memory" "$SHARED_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_ROOT"

if [ ! -f "$SHARED_DIR/content-bot.env" ]; then
  cat >"$SHARED_DIR/content-bot.env" <<'ENV'
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
ENV
  chmod 600 "$SHARED_DIR/content-bot.env"
  chown "$SERVICE_USER:$SERVICE_USER" "$SHARED_DIR/content-bot.env"
fi

sed "s/__SERVICE_USER__/$SERVICE_USER/g" \
  "$APP_DIR/deploy/content-bot-polling.service" \
  >"/etc/systemd/system/$SERVICE_NAME.service"
chmod 0644 "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME.service"
systemctl restart "$SERVICE_NAME.service"
systemctl --no-pager --full status "$SERVICE_NAME.service" | sed -n '1,20p'
