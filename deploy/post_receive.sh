#!/usr/bin/env bash
# Этот файл копируется на сервер в /opt/content-bot/repo.git/hooks/post-receive
# Срабатывает автоматически при git push

set -euo pipefail

APP_DIR="/opt/content-bot/app"
SERVICE_NAME="content-bot-polling"

echo "==> Deploying to $APP_DIR ..."

# Checkout свежего кода из bare-репозитория в рабочую директорию
export GIT_WORK_TREE="$APP_DIR"
export GIT_DIR="$(dirname "$0")/.."
git checkout -f main

echo "==> Restarting $SERVICE_NAME ..."
sudo systemctl restart "$SERVICE_NAME"

echo "==> Deploy complete. Status:"
sudo systemctl --no-pager status "$SERVICE_NAME" | head -8
