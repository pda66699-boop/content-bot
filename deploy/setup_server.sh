#!/usr/bin/env bash
# Запускается ОДИН РАЗ на сервере от apex с sudo
# ssh apex@116.203.132.170 'bash -s' < deploy/setup_server.sh

set -euo pipefail

REPO_DIR="/opt/content-bot/repo.git"
APP_DIR="/opt/content-bot/app"
DATA_DIR="/opt/content-bot/data"
SHARED_DIR="/opt/content-bot/shared"
SERVICE_USER="contentbot"
SERVICE_NAME="content-bot-polling"

echo "=== 1. Создаём директории ==="
sudo mkdir -p "$REPO_DIR" "$APP_DIR" "$DATA_DIR/memory" "$SHARED_DIR"

echo "=== 2. Создаём системного пользователя ==="
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    sudo useradd --system --home /opt/content-bot --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "=== 3. Инициализируем bare git репозиторий ==="
sudo git init --bare "$REPO_DIR"

echo "=== 4. Устанавливаем post-receive хук ==="
sudo tee "$REPO_DIR/hooks/post-receive" >/dev/null <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="/opt/content-bot/app"
SERVICE_NAME="content-bot-polling"
echo "==> Deploying to $APP_DIR ..."
export GIT_WORK_TREE="$APP_DIR"
export GIT_DIR="/opt/content-bot/repo.git"
git checkout -f main
echo "==> Restarting $SERVICE_NAME ..."
sudo systemctl restart "$SERVICE_NAME"
echo "==> Done."
sudo systemctl --no-pager status "$SERVICE_NAME" | head -8
HOOK
sudo chmod +x "$REPO_DIR/hooks/post-receive"

echo "=== 5. Разрешаем apex вызывать systemctl без пароля ==="
sudo tee /etc/sudoers.d/content-bot >/dev/null <<'SUDOERS'
apex ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart content-bot-polling
apex ALL=(ALL) NOPASSWD: /usr/bin/systemctl status content-bot-polling
contentbot ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart content-bot-polling
contentbot ALL=(ALL) NOPASSWD: /usr/bin/systemctl status content-bot-polling
SUDOERS
sudo chmod 440 /etc/sudoers.d/content-bot

echo "=== 6. Создаём env-файл с секретами (заполни вручную) ==="
if [ ! -f "$SHARED_DIR/content-bot.env" ]; then
    sudo tee "$SHARED_DIR/content-bot.env" >/dev/null <<'ENV'
TELEGRAM_BOT_TOKEN=ВСТАВЬ_СЮДА_ТОКЕН
TELEGRAM_WEBHOOK_SECRET=ВСТАВЬ_СЮДА_СЕКРЕТ
TELEGRAM_ALLOWED_USER_IDS=ВСТАВЬ_СЮДА_СВОЙ_ID
CONTENT_BOT_LLM_MODE=off
# OPENAI_API_KEY=sk-...  # раскомментировать если нужен LLM
ENV
    sudo chmod 600 "$SHARED_DIR/content-bot.env"
fi

echo "=== 7. Права ==="
sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
sudo chown -R apex:apex "$REPO_DIR" "$APP_DIR"

echo ""
echo "=== Готово! ==="
echo "Теперь на своей машине:"
echo "  git remote add deploy apex@116.203.132.170:/opt/content-bot/repo.git"
echo "  git push deploy main"
echo ""
echo "  Не забудь заполнить секреты: sudo nano $SHARED_DIR/content-bot.env"
echo "  И потом первый раз установить сервис: sudo bash $APP_DIR/deploy/install_remote.sh"
