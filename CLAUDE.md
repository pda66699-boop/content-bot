# Инструкции для ассистента — проект content-bot

> Этот файл читается автоматически при каждом открытии проекта Claude/Codex.
> Архитектура проекта — в `ARCHITECTURE.md`.

Эти правила считать проектными инструкциями. Если они конфликтуют с системными правилами среды выполнения, приоритет у системных правил, но в остальных случаях следовать этому файлу.

---

## ОБЯЗАТЕЛЬНОЕ ПРАВИЛО ДЕПЛОЯ

**Никогда не предлагай проверить изменения до деплоя, если задача подразумевает выпуск исправления в работающий Telegram-бот.**

Порядок действий при любой правке кода, которая должна попасть в прод:

1. **Закоммить** изменения в git
2. **`git push github main`** — пуш на GitHub
3. **`git push deploy main`** — деплой на сервер (запускает post-receive хук)
4. **Убедиться**, что сервис поднялся (`systemctl status content-bot-polling`)
5. **Только после этого** — сообщить о результате и предложить проверить

Если пользователь просит только исследование, локальную правку документации или черновик без выпуска в прод — явно сказать, что деплой не выполнялся.

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

---

## Текущие критичные правила логики

### Темы и повторы

- Кнопка **«✨ Предложить 5 тем»** должна показывать обычному пользователю прежде всего темы со статусами `novelty_status=fresh` и `editorial_gate=allowed`.
- `reframe_only`, `series_only` и `too_close` нельзя маскировать под свежие темы. Они допустимы только как явно помеченный reframe/continuation или как fallback, если fresh-вариантов меньше пяти.
- Roadmap — не абсолютная истина. Если тема из roadmap уже закрыта опубликованным постом по смыслу, planner обязан считать её completed и не проталкивать повтор.
- Для тем про деньги/потери учитывать разные формулировки: `потери`, `теряет деньги`, `утечки`, `издержки`, `расходы`, `P&L`.

### Выбор темы по номеру

- Цифра пользователя (`1`, `2`, `3`...) выбирает тему из `session["last_topic_suggestions"]`.
- Если выдача тем была неправильной, чинить нужно `format_five_topics()` / `planner_engine.py`, а не `handle_topic_pick()`.

### Состояние сессий

- На старте polling вызывается `startup_clear_stale_drafts()`, чтобы старые `last_generated`, `last_analyzed_post`, `last_improvement_options` не всплывали после изменения prompt/stop_words.
- Не удалять это поведение без замены на версионирование drafts.
