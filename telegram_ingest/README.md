# Telegram Ingest Scaffold

Каркас ingest-слоя для автосинхронизации новых постов канала.

## Что уже умеет

- принимать JSON update из Telegram Bot API;
- выделять `channel_post` и `edited_channel_post`;
- сохранять сырой update;
- нормализовать пост в вашу внутреннюю карточку;
- делать черновую аннотацию темы и тезиса;
- мягко нормализовать editorial metadata для новых и старых карточек;
- upsert-ить запись в SQLite;
- добавлять или обновлять пост в `memory/posts_index.jsonl`.
- запускаться в режиме polling;
- запускаться как локальный webhook server.
- собирать готовый ответ в формате `/post тема` для локального CLI и будущего Telegram-бота.
- принимать личные сообщения боту с `/post ...` и отвечать прямо в Telegram.

## Что ещё не подключено

- реальный webhook или polling runner;
- LLM-аннотация;
- автоматическое обновление `topic_map` и `content_backlog`;
- публикация через бота.

## Быстрый запуск на sample payload

```bash
python3 content-bot/scripts/process_telegram_update.py content-bot/examples/telegram_channel_post.sample.json
python3 content-bot/scripts/refresh_memory_views.py
```

## Editorial Metadata

Каждая карточка поста теперь может хранить дополнительный semantic layer:

- `primary_thesis`
- `secondary_theses`
- `angle`
- `content_goal`
- `funnel_stage`
- `business_dimensions`
- `format_type`
- `novelty_window_days`

Для стабильности downstream-логики `funnel_stage` теперь канонизируется в slug-формат:

- `problem_aware`
- `solution_aware`
- `solution_consideration`
- `aware`
- `trust`

За совместимость отвечает `telegram_ingest.editorial_metadata.normalize_editorial_metadata()`:

- новые поля добавляются мягко;
- старые карточки без этих полей продолжают читаться без ошибок;
- SQLite schema не меняется, новые поля живут внутри `content_record_json` и JSONL-карточек.

Semantic metadata теперь автоматически обогащается через `telegram_ingest.editorial_extractor`:

- `rules-only` режим работает локально и не требует API;
- `hybrid LLM` режим использует отдельный classification prompt;
- при невалидном JSON или недоступном API extractor автоматически возвращается к локальным правилам.

Для проверки повторов и новизны добавлен `telegram_ingest.editorial_similarity`:

- `find_semantic_neighbors()` ищет ближайшие совпадения по editorial metadata;
- `classify_topic_novelty()` возвращает один из статусов `fresh`, `reframe_allowed`, `series_continuation`, `too_close`;
- `suggest_reframes()` предлагает безопасные углы для темы, если рядом уже есть близкие публикации.

Planner теперь использует semantic novelty layer поверх rules-only логики:

- кандидаты сначала собираются как и раньше;
- затем для novelty/gate обогащаются editorial metadata extractor'ом в `rules-only` режиме;
- после этого получают `novelty_status`, `reason`, `allowed_reframes`, `recommended_format`, `recommended_cta_type`;
- смысловые дубли больше не должны подниматься как полностью свежие темы.

Это сделано специально: даже если глобально включён `CONTENT_BOT_LLM_MODE=hybrid`, planner ranking и editorial gate используют локальную rules-only extraction path как стабильный источник правды для повторов и новизны. LLM можно использовать в генерации тем/текстов, но не для критичного novelty gating.

Planner также поднят до уровня content-plan slot planning:

- сначала считается coverage ленты по `business_dimensions`, `angles`, `funnel_stage`, `content_goal`, `format_type`;
- затем выбирается `recommended_slot`, который объясняет, что перегрето и чего сейчас не хватает;
- только после этого темы ранжируются под нужный слот, а не как случайный список идей.

Rewrite engine теперь поддерживает explicit rewrite plan:

- `rewrite_post_by_improvement(..., rewrite_plan=...)` принимает целевой смысловой план;
- план может задавать `target_primary_thesis`, `target_angle`, `target_format_type`, `target_content_goal`, `target_funnel_stage`;
- также поддерживаются `avoid_similarity_with_post_ids` и `must_remove_patterns`;
- даже без LLM fallback старается менять не только формулировки, но и угол/роль/формат переписывания.

## Evaluation Mode

Для ручной проверки semantic layer добавлен `telegram_ingest.editorial_evaluation`.

Что можно посмотреть в debug/review output:

- `primary_thesis`
- `secondary_theses`
- `angle`
- `content_goal`
- `funnel_stage`
- `business_dimensions`
- `novelty_status`
- `editorial_admissibility`
- `matched_posts`
- `allowed_reframes`
- `score_breakdown`
- `reason`

Быстрый review для списка тем или постов:

```bash
python3 content-bot/scripts/review_editorial_semantic.py --input content-bot/examples/editorial_review_cases.json --mode rules-only
python3 content-bot/scripts/review_editorial_semantic.py --input content-bot/examples/editorial_review_cases.json --mode hybrid --format json
```

Planner-ranking review для нескольких тем между собой:

```bash
python3 content-bot/scripts/review_editorial_semantic.py \
  --review-type planner \
  --input content-bot/examples/planner_topic_review_cases.json \
  --compare

python3 content-bot/scripts/review_editorial_semantic.py \
  --review-type planner \
  --topic "скрытые потери в операционке" \
  --topic "оргструктура и роли" \
  --topic "ошибки собственника по стадиям бизнеса" \
  --format json
```

Golden-set evaluation:

```bash
python3 content-bot/scripts/evaluate_editorial_semantic.py --input content-bot/examples/editorial_golden_set.json --mode rules-only
python3 content-bot/scripts/evaluate_editorial_semantic.py --input content-bot/examples/editorial_golden_set.json --mode hybrid --limit 20
```

Planner-ranking golden set:

```bash
python3 content-bot/scripts/evaluate_editorial_semantic.py --input content-bot/examples/planner_ranking_golden_set.json --mode rules-only
```

Для planner и critic есть быстрые debug-флаги:

```bash
python3 content-bot/scripts/plan_next_topics.py --debug
python3 content-bot/scripts/critic_post.py --file draft.txt --debug
```

## How To Read Novelty Status

Если нужно понять, почему тема получила конкретный статус:

- `fresh`: рядом не нашлось близкого тезиса и угла в актуальном novelty window;
- `reframe_allowed`: тезис уже звучал, но угол, формат или стадия воронки достаточно отличаются;
- `too_close`: рядом есть недавний пост с почти тем же тезисом и очень похожей подачей;
- `series_continuation`: это осмысленное продолжение уже начатой линии, а не случайный дубль.

Чтобы вручную проверить решение классификатора:

1. Запустите `review_editorial_semantic.py` на теме или посте.
2. Посмотрите `primary_thesis`, `angle`, `funnel_stage` и список `matched_posts`.
3. Сверьте `reason` и `novelty_status` с ближайшими совпадениями.
4. Если тема спорная, прогоните её ещё раз в `hybrid` режиме и сравните расхождение с `rules-only`.
5. Если нужно понять ranking order между несколькими темами, используйте `review_editorial_semantic.py --review-type planner --compare`.

## Retro Enrichment

Чтобы дообогатить старый архив editorial metadata, используйте:

```bash
python3 content-bot/scripts/enrich_posts_editorial_metadata.py --dry-run --mode rules-only
python3 content-bot/scripts/enrich_posts_editorial_metadata.py --mode rules-only
python3 content-bot/scripts/enrich_posts_editorial_metadata.py --mode hybrid --limit 50
```

Что умеет скрипт:

- читает `memory/posts_index.jsonl`;
- дозаполняет только неполные записи;
- поддерживает `--dry-run`;
- поддерживает `--limit`;
- поддерживает `rules-only` и `hybrid` режимы;
- пишет обратно через безопасный JSONL writer, не меняя структуру индекса.

## Test Run

Минимальный прогон semantic layer:

```bash
python3 -m unittest discover -s content-bot/tests -p 'test_*.py'
```

Точечные наборы:

```bash
python3 -m unittest content-bot/tests/test_editorial_metadata.py
python3 -m unittest content-bot/tests/test_editorial_extractor.py
python3 -m unittest content-bot/tests/test_editorial_similarity.py
python3 -m unittest content-bot/tests/test_editorial_evaluation.py
python3 -m unittest content-bot/tests/test_planner_semantic.py
python3 -m unittest content-bot/tests/test_planner_regression.py
python3 -m unittest content-bot/tests/test_critic_semantic.py
python3 -m unittest content-bot/tests/test_rewrite_plan.py
```

Regression coverage для planner:

- near-duplicate не должен обгонять fresh topic;
- `reframe_allowed` не должен маскироваться под fresh в user-facing output;
- `series_continuation` требует continuity evidence;
- `too_close` должен исключаться из top recommendations;
- кейс `скрытые потери в операционке` против близкой темы про оптимизацию издержек через процессы;
- fresh personal/trust topic должен подниматься выше повторного diagnostic topic;
- promised continuation с подтверждённым open loop может подниматься выше обычной fresh темы.

Запуск только regression tests:

```bash
python3 -m unittest content-bot/tests/test_planner_regression.py
```

## Local `/post` command

```bash
PYTHONPATH=content-bot python3 content-bot/scripts/post_command.py "/post Типичные кризисы на разных стадиях бизнеса"
```

Команда вернёт:

- лучший готовый пост;
- почему он уместен сейчас;
- риск повтора;
- какой CTA выбран и почему;
- альтернативный угол;
- какой открытый крючок учитывается.

## Long Polling

Нужен `TELEGRAM_BOT_TOKEN`.

```bash
PYTHONPATH=content-bot TELEGRAM_BOT_TOKEN=... python3 content-bot/scripts/run_telegram_polling.py
```

Polling автоматически слушает только:

- `channel_post`
- `edited_channel_post`
- `message`

Оффсет сохраняется в `memory/telegram_polling_offset.json`.

## Webhook Server

Можно поднять локальный HTTP-сервер:

```bash
PYTHONPATH=content-bot TELEGRAM_WEBHOOK_SECRET=... python3 content-bot/scripts/run_telegram_webhook_server.py --host 127.0.0.1 --port 8081
```

Затем повесить webhook на внешний URL, который проксируется на этот сервер.

Если нужен вызов Telegram API для установки webhook:

```bash
PYTHONPATH=content-bot TELEGRAM_BOT_TOKEN=... python3 - <<'PY'
from telegram_ingest.bot_api import set_webhook
print(set_webhook("https://your-domain.example/telegram/webhook", secret_token="your-secret", allowed_updates=["channel_post","edited_channel_post"]))
PY
```

Для поддержки команд бота в webhook лучше использовать:

```python
allowed_updates=["channel_post", "edited_channel_post", "message"]
```

## Deploy on a server

Для полного теста на сервере сейчас лучше использовать polling-режим: ему не нужен домен, TLS и reverse proxy.

В проект добавлена безопасная схема обновлений:

- код живёт в `/opt/content-bot/app`;
- рабочие данные живут отдельно в `/opt/content-bot/data/memory`;
- обновления кода не затирают SQLite, offset, UI state и raw updates.

Подготовка на сервере:

```bash
mkdir -p /opt/content-bot/app
```

Выгрузка новой версии с локальной машины:

```bash
cd content-bot
REMOTE_USER=root ./deploy/push_update.sh 116.203.132.170
```

После первого запуска нужно заполнить `/opt/content-bot/shared/content-bot.env`:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_IDS=123456789
```

Полезные команды на сервере:

```bash
systemctl status content-bot-polling
journalctl -u content-bot-polling -n 100 --no-pager
systemctl restart content-bot-polling
```

## Telegram `/post` command

После запуска polling или webhook бот может принимать команды в личке:

```text
/post Типичные кризисы на разных стадиях бизнеса
```

В ответ бот отправит:

- лучший готовый пост;
- почему тема уместна сейчас;
- риск повтора;
- CTA и объяснение;
- альтернативный угол;
- открытый крючок, который можно закрыть.

## Что важно для будущего

Если вы пришлёте обновлённую базу позиционирования, её нужно не просто "добавить в prompt", а завести как новую версию в `memory/knowledge_registry.json`.

Тогда новые посты смогут аннотироваться уже с пометкой новой версии базы, и мы не потеряем преемственность между старой и усиленной логикой.
