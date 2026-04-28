# Инструкции для Claude — проект content-bot

> Этот файл читается автоматически при каждом открытии проекта.
> Архитектура проекта — в `ARCHITECTURE.md`.

---

## ОБЯЗАТЕЛЬНОЕ ПРАВИЛО ДЕПЛОЯ

**Никогда не предлагай проверить изменения до деплоя.**

Порядок действий при любой правке кода:

1. **Закоммить** изменения в git
2. **`git push github main`** — пуш на GitHub
3. **`git push deploy main`** — деплой на сервер (запускает post-receive хук)
4. **Убедиться**, что сервис поднялся (`systemctl status content-bot-polling`)
5. **Только после этого** — сообщить о результате и предложить проверить

---

## Топология деплоя

```
Локальная машина
    │
    ├── git push github main  ──▶  github.com/pda66699-boop/content-bot
    │
    └── git push deploy main  ──▶  apex@116.203.132.170:/opt/content-bot/repo.git
                                        │
                                        └── post-receive hook
                                              ├── git checkout -f main → /opt/content-bot/app/
                                              └── systemctl restart content-bot-polling
```

**Сервер:** `116.203.132.170`  
**SSH-пользователь:** `apex`  
**Рабочая директория на сервере:** `/opt/content-bot/app/`  
**Сервис:** `content-bot-polling` (systemd)  
**Env-файл с секретами:** `/opt/content-bot/shared/content-bot.env`

---

## Git-ремоуты

```bash
git remote -v
# deploy  apex@116.203.132.170:/opt/content-bot/repo.git  (push)
# github  git@github.com:pda66699-boop/content-bot.git    (push)
```

---

## Команды деплоя

```bash
# Стандартный деплой (всегда оба шага):
git push github main
git push deploy main

# Проверить статус сервиса на сервере:
ssh apex@116.203.132.170 'sudo systemctl status content-bot-polling'

# Посмотреть логи на сервере:
ssh apex@116.203.132.170 'journalctl -u content-bot-polling -n 50 --no-pager'

# Альтернативный деплой через rsync (если git-деплой недоступен):
cd "/Users/dpedcenko/Codex — Контент-мейкер/content-bot"
bash deploy/push_update.sh 116.203.132.170
```

---

## Исключения из деплоя

Следующие файлы **не деплоятся** (исключены в `.gitignore` или rsync):
- `memory/telegram_ingest.sqlite3` — база данных сессий
- `memory/telegram_polling_offset.json` — оффсет polling
- `memory/telegram_ui_state.json` — состояние UI
- `memory/raw_updates/` — сырые апдейты Telegram
- `.claude/` — настройки Claude Code
- `__pycache__/`, `.pytest_cache/`

---

## Обновление ARCHITECTURE.md

При каждом изменении логики бота, добавлении файлов или исправлении багов:
1. Добавить запись в раздел **«Известные баги и исправления»** (если это фикс)
2. Обновить таблицу модулей, если добавлен новый файл
3. Обновить описание pipeline, если изменился порядок вызовов
