# Архитектура проекта: Контент-архитектор

> **Этот файл — живая документация. Обновлять при каждом изменении логики, добавлении файлов или смене поведения бота.**

---

## Назначение системы

Telegram-бот для Дениса Педченко, консультанта по управленческим потерям в сервисных бизнесах 60–150 млн ₽/год.

Бот генерирует контент для Telegram-канала: предлагает темы, пишет посты, критикует черновики, ведёт редакционную память.

**Воронка продукта:** лид-магнит → экспресс-диагностика (20К) → флагман «Бизнес без потерь» (300К) → сопровождение (70–100К/мес)

---

## Структура проекта

```
content-bot/
├── telegram_ingest/          # Основная логика (Python-пакет)
├── prompts/                  # Системные промпты для LLM
├── memory/                   # Персистентная память (JSON, JSONL, SQLite)
├── scripts/                  # CLI-скрипты для ручного запуска
├── deploy/                   # Скрипты деплоя на сервер
├── tests/                    # Тесты
├── examples/                 # Примеры использования
└── ARCHITECTURE.md           # Этот файл
```

---

## Ключевые модули (`telegram_ingest/`)

### Входная точка и роутинг
| Файл | Роль |
|---|---|
| `run_telegram_polling.py` / `run_telegram_webhook_server.py` | Запуск бота (polling или webhook) |
| `polling_runner.py` | Цикл polling, обработка очереди |
| `message_router.py` | **Главный роутер** — разбирает сообщения, вызывает нужную логику, управляет сессией |
| `bot_api.py` | Обёртка над Telegram Bot API |
| `bot_state.py` | Состояние сессий пользователей; startup-очистка stale drafts |

### Генерация постов (основной pipeline)
```
message_router → command_interface → publishable_engine
                                         ↓
                                   generate_drafts (writer_engine)
                                         ↓
                               maybe_generate_writer_drafts (hybrid_llm)  ← LLM
                                         ↓
                               apply_stop_word_guard   ← ПЕРВЫЙ ПРОХОД ГАРДА
                                         ↓
                                   choose_best_variant (publishable_engine)
                                         ↓
                                   polish_text (polish_engine)
                                         ↓
                               apply_stop_word_guard   ← ВТОРОЙ ПРОХОД ГАРДА (финальный)
                                         ↓
                                   critic_review (critic_engine)
                                         ↓
                                   final_text → Telegram
```

| Файл | Роль |
|---|---|
| `command_interface.py` | Парсинг команд `/post`, `/note`; форматирование ответа в HTML |
| `publishable_engine.py` | Оркестратор: генерирует варианты → полирует → выбирает лучший |
| `writer_engine.py` | Сборка черновиков (rule-based fallback + LLM); `apply_stop_word_guard` |
| `polish_engine.py` | Постобработка: нормализация, ритм абзацев, хардкодные замены |
| `critic_engine.py` | Критика поста: stop_words, повторы, голос, тема, стиль |
| `hybrid_llm.py` | LLM-вызовы: `generate_core_idea`, `maybe_generate_writer_drafts`, `maybe_generate_planner_candidates` |
| `rewrite_engine.py` | Рерайт существующего поста по плану улучшений |

### Планировщик тем

#### Выдача пяти тем в Telegram

```
message_router.format_five_topics
        ↓
planner_engine.plan_next_topics
        ↓
feed_coverage + roadmap_state + backlog + open_loops
        ↓
semantic novelty check + editorial_gate
        ↓
weekly_plan / best_next_topics
        ↓
filter: сначала только fresh + allowed
        ↓
fallback: reframe_only только если fresh-вариантов меньше пяти
        ↓
session["last_topic_suggestions"]
        ↓
handle_topic_pick("1".."5") → build_post_command_result
```

Критичное правило: цифра пользователя выбирает тему из последней сохранённой пятёрки. Если бот "берёт не ту тему", почти всегда проблема в ранжировании/фильтрации выдачи, а не в обработчике номера.

| Файл | Роль |
|---|---|
| `planner_engine.py` | **Главный планировщик** — скоринг кандидатов, roadmap, воронка, `infer_post_type` |
| `narrative_engine.py` | Narrative state: track последних narrative_role, выбор следующей |
| `feed_coverage.py` | Снэпшот ленты: баланс форматов, покрытие тем, нужды контент-плана |
| `backlog_memory.py` | Бэклог тем из `content_backlog.json` |
| `positioning.py` | Флаги позиционирования, CTA-стратегия, баланс content_pillar |
| `open_loops.py` | Открытые крючки — незакрытые нарративные петли |

### Память и обучение
| Файл | Роль |
|---|---|
| `editorial_memory.py` | Запись и загрузка редакционной обратной связи |
| `editorial_extractor.py` | Извлечение метаданных из опубликованных постов |
| `editorial_metadata.py` | Обогащение карточки поста метаданными |
| `editorial_evaluation.py` | Оценка качества поста (semantic, style, fit) |
| `editorial_similarity.py` | Novelty check: похожесть новой темы на уже опубликованные |
| `knowledge.py` | Загрузка терминологии, обратной связи, базы знаний |
| `memory_sync.py` | Синхронизация memory-файлов |

### Вспомогательные
| Файл | Роль |
|---|---|
| `llm_client.py` | HTTP-клиент к Anthropic API, кеш, retry |
| `store.py` | SQLite-обёртка для `posts_index` |
| `normalize.py` | Нормализация текста |
| `annotate.py` | Ручная аннотация постов |
| `ui.py` | Форматирование UI-элементов для Telegram |
| `config.py` | Пути к файлам, переменные окружения |
| `models.py` | Dataclass-модели |
| `runtime.py` | Runtime-хелперы |
| `pipeline.py` | Пайплайн инжеста Telegram-постов |

---

## Промпты (`prompts/`)

| Файл | Роль |
|---|---|
| `writer.md` | Системный промпт для генерации постов. Содержит типы постов, голос, запрещённые паттерны, примеры. **Главный файл качества.** |
| `planner.md` | Системный промпт для планировщика тем |
| `critic.md` | Системный промпт для критика |
| `post_types.md` | Справочник типов постов (вспомогательный) |

---

## Память (`memory/`)

| Файл | Что хранит |
|---|---|
| `posts_index.jsonl` | Все опубликованные посты с метаданными (основной архив) |
| `posts_index_summary.md` | Human-readable сводка по постам |
| `style_profile.json` | Стилевой профиль автора (выведен из архива) |
| `user_preferences.json` | Настройки пользователя (эмодзи, лимиты, CTA) |
| `stop_words.json` | Запрещённые фразы и паттерны. Три секции: `banned_phrases`, `template_phrases_to_avoid`, `fragment_triggers` |
| `terminology_registry.json` | Правильная терминология + `taboo_phrases` |
| `golden_style_set.json` | Эталонные посты для стилевых референсов |
| `content_backlog.json` | Бэклог тем (не запланированные, но одобренные идеи) |
| `content_plan_roadmap.json` | Редакционный roadmap по неделям |
| `open_loops.json` | Открытые нарративные петли |
| `editorial_feedback_log.jsonl` | Лог обратной связи по качеству постов |
| `current_feed_snapshot.md` | Актуальный снэпшот ленты |
| `topic_map.md` | Карта тем канала |
| `conversational_style_library.json` | Библиотека разговорных стилей (для reflective-постов) |
| `post_format_registry.json` | Реестр форматов постов |
| `telegram_ingest.sqlite3` | SQLite — posts_index, сессии |
| `telegram_ui_state.json` | Состояние UI (клавиатуры, последние данные) |

### Runtime-состояние и stale drafts

При старте polling `polling_runner.run_polling()` вызывает `bot_state.startup_clear_stale_drafts()`.

Очищаются поля сессий:

- `last_generated`
- `last_analyzed_post`
- `last_improvement_options`

Зачем: если между перезапусками изменились `writer.md`, `stop_words.json` или guard-логика, старый draft не должен возвращаться пользователю через "улучшить", "анализ" или revision-flow без повторного прохождения актуальных гардов.

---

## Типы постов (`post_type`)

Определяются в `planner_engine.py → infer_post_type()`.  
Передаются в LLM как жёсткое ограничение через преамбул в `hybrid_llm.py`.  
Шаблоны описаны в `prompts/writer.md`.

| post_type | Название | Narrative role | Лимит |
|---|---|---|---|
| `pain_breakdown` | Разбор точки потерь | Pain | 900 зн. |
| `case` | Мини-кейс | Proof | 1 100 зн. |
| `provocation` | Провокация | Reframe | 650 зн. |
| `loss_calculator` | Считаем потери | Pain | 600 зн. |
| `authority_breakdown` | Авторитетный разбор | Proof | 1 000 зн. |
| `personal_insight` | Личный инсайт | **Trust** | 700 зн. |
| `soft_sell` | Мягкая продажа | — | 750 зн. |

**Правило:** `narrative_role == "trust"` → всегда `personal_insight`.

---

## Narrative roles

Определяются в `narrative_engine.py`.  
Используются для балансировки ленты: бот отслеживает последовательность ролей и выбирает следующую нужную.

| Роль | Смысл |
|---|---|
| `trust` | Личный инсайт, эволюция взгляда, человечность |
| `pain` | Боль, потеря, узнаваемая проблема |
| `reframe` | Переосмысление привычного |
| `proof` | Доказательство, кейс, исследование |
| `solution` | Практический путь решения |

---

## Semantic novelty и roadmap

### Источник истины по повторам

Повторы определяются не только по названию темы. Основная проверка живёт в:

- `editorial_extractor.py` — строит semantic metadata;
- `editorial_similarity.py` — считает semantic neighbors и `novelty_status`;
- `planner_engine.py` — превращает novelty в `editorial_gate`, penalty и порядок выдачи.

Ключевые поля:

- `primary_thesis`
- `secondary_theses`
- `angle`
- `business_dimensions`
- `funnel_stage`
- `format_type`
- `novelty_window_days`

### Статусы

| Статус | Значение | Поведение в обычной пятёрке |
|---|---|---|
| `fresh` | Тезис и угол достаточно новые | Можно показывать как обычную тему |
| `reframe_allowed` | Тезис уже звучал, нужен другой угол/формат | Не показывать как fresh; только reframe/fallback |
| `series_continuation` | Продолжение начатой линии | Нужна continuity-evidence/open_loop |
| `too_close` | Слишком близко к уже опубликованному | Исключить из рекомендаций |

### Roadmap

`content_plan_roadmap.json` задаёт редакционную последовательность, но пункт roadmap считается `completed`, если похожий смысл уже закрыт опубликованным постом.

`planner_engine.roadmap_match_score()` дополнительно учитывает смысловые маркеры скрытых потерь:

- `потер`
- `теря`
- `утеч`
- `издерж`
- `расход`
- `деньг`
- `прибыл`
- `p and l`

Это защищает от ситуации, когда тема "где бизнес теряет деньги" повторно предлагается после уже опубликованного поста про оптимизацию издержек и скрытые потери.

---

## Гарды качества

### `apply_stop_word_guard(text, stop_words)` — `writer_engine.py`

**Вызывается дважды:**
1. В `writer_engine.py` — после получения черновика от LLM
2. В `publishable_engine.py → choose_best_variant()` — после `polish_text()`, перед возвратом финального текста

**Логика:** удаляет **целые предложения**, содержащие запрещённые фрагменты (не режет фразу в середине предложения). Источники триггеров из `stop_words.json`:
- `template_phrases_to_avoid` — полные запрещённые фразы
- `fragment_triggers` — короткие подстроки-сигналы семейств фраз

### `apply_voice_authenticity_guard(text)` — `writer_engine.py`
Заменяет консультантский жаргон живыми словами.

### `apply_editorial_feedback_guards(text, feedback)` — `writer_engine.py`
Применяет накопленную редакционную обратную связь.

### `critic_review(text)` — `critic_engine.py`
Скоринг черновика по рискам: stop_words, повторы, голос, тема, стиль. Используется для выбора лучшего варианта.

---

## Преамбул LLM (жёсткие ограничения)

В `hybrid_llm.py → maybe_generate_writer_drafts()` перед системным промптом вставляется жёсткий блок:

```
╔══════════════════════════════════════════════════════════╗
║  ЖЁСТКИЕ ОГРАНИЧЕНИЯ — ПРОЧИТАТЬ ПЕРЕД НАПИСАНИЕМ       ║
╚══════════════════════════════════════════════════════════╝
ТИП ПОСТА: {post_type}
Писать СТРОГО по шаблону типа «{post_type}» из раздела «ШАБЛОН ПО ТИПУ ПОСТА».
Раздел «СТРУКТУРА ПОСТА» — НЕ ПРИМЕНЯЕТСЯ.
ГЛАВНАЯ МЫСЛЬ: «{core_idea}»
Каждый абзац работает только на эту мысль.
══════════════════════════════════════════════════════════
```

`generate_core_idea()` вызывается отдельным дешёвым LLM-вызовом перед генерацией.

---

## Известные баги и исправления

| Дата | Проблема | Файл | Решение |
|---|---|---|---|
| 2026-04-28 | `narrative_role=trust` → `post_type=pain_breakdown` вместо `personal_insight` | `planner_engine.py` | Добавлен параметр `narrative_role` в `infer_post_type()` |
| 2026-04-28 | `apply_stop_word_guard` резал фразу в середине предложения → оставлял мусор | `writer_engine.py` | Переписан: удаляет целое предложение через `_remove_sentences_with_triggers()` |
| 2026-04-28 | Гард не вызывался после `polish_text` → forbidden phrases проходили в финал | `publishable_engine.py` | Добавлен второй вызов `apply_stop_word_guard` после `polish_text` |
| 2026-04-28 | `post_type` и `core_idea` были мягкими подсказками в промпте — LLM игнорировал | `hybrid_llm.py` | Заменены жёстким преамбулом, вставляемым ДО `writer.md` |
| 2026-04-28 | После изменения prompt/stop_words старые drafts могли всплывать из сессии без актуальных гардов | `bot_state.py`, `polling_runner.py` | На старте polling очищаются stale draft-поля: `last_generated`, `last_analyzed_post`, `last_improvement_options` |
| 2026-04-28 | Бот снова предлагал тему про "самые дорогие потери / где бизнес теряет деньги", хотя близкий пост уже был в канале | `editorial_extractor.py`, `planner_engine.py`, `message_router.py` | Добавлены маркеры `теря/утеч`, roadmap-матчинг скрытых потерь и фильтр обычной пятёрки по `fresh + allowed` |

---

## Добавление новой запрещённой фразы

1. Добавить в `memory/stop_words.json`:
   - Если полная фраза → в `template_phrases_to_avoid`
   - Если короткий триггер целого семейства → в `fragment_triggers`
2. Проверить: `python3 -c "from telegram_ingest.writer_engine import apply_stop_word_guard, load_stop_words, merge_stop_word_sources; from telegram_ingest.knowledge import load_terminology_registry; sw = merge_stop_word_sources(load_stop_words(), load_terminology_registry()); print(apply_stop_word_guard('ТЕСТОВАЯ ФРАЗА.', sw))"`

## Добавление нового типа поста

1. Добавить шаблон в `prompts/writer.md` (раздел «ШАБЛОН ПО ТИПУ ПОСТА»)
2. Добавить `char_limit` в `hybrid_llm.py → _POST_TYPE_CHAR_LIMITS`
3. Добавить в `VALID_POST_TYPES` в `hybrid_llm.py`
4. Обновить условия в `planner_engine.py → infer_post_type()`
5. Обновить таблицу типов в этом файле

---

## Деплой

### Топология

```
Локальная машина
    ├── git push github main  ──▶  github.com/pda66699-boop/content-bot
    └── git push deploy main  ──▶  apex@116.203.132.170:/opt/content-bot/repo.git
                                        └── post-receive → checkout + systemctl restart
```

**Сервер:** `116.203.132.170`  
**Рабочая директория:** `/opt/content-bot/app/`  
**Сервис:** `content-bot-polling` (systemd, пользователь `contentbot`)  
**Секреты:** `/opt/content-bot/shared/content-bot.env`

### Стандартный деплой (оба шага обязательны)

```bash
git push github main      # GitHub — бэкап и видимость
git push deploy main      # Сервер — post-receive хук деплоит и рестартует сервис
```

### Проверка после деплоя

```bash
ssh apex@116.203.132.170 'sudo systemctl status content-bot-polling'
ssh apex@116.203.132.170 'journalctl -u content-bot-polling -n 50 --no-pager'
```

### Альтернатива: rsync-деплой

```bash
bash deploy/push_update.sh 116.203.132.170
```

Делает rsync → запускает `deploy/install_remote.sh` → systemctl restart.

### Локальный запуск

```bash
python3 scripts/run_telegram_polling.py
```
