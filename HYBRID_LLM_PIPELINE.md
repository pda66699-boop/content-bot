# Hybrid LLM Pipeline

Текущий бот работает в двух режимах:

- `CONTENT_BOT_LLM_MODE=off` — только rules, память и эвристики
- `CONTENT_BOT_LLM_MODE=hybrid` — LLM генерирует идеи и тексты, а rules фильтруют и направляют результат

## Где участвует LLM

В hybrid-режиме LLM подключается в четыре узла:

1. `planner`
   Генерирует дополнительные темы и углы для следующего окна ленты

2. `editorial_extractor`
   Классифицирует semantic metadata постов и тем:
   - `primary_thesis`
   - `secondary_theses`
   - `angle`
   - `content_goal`
   - `funnel_stage`
   - `business_dimensions`
   - `format_type`
   - `novelty_window_days`

3. `writer`
   Пишет 1-2 живых черновика поста по выбранной теме

4. `rewrite`
   Делает рерайт под explicit rewrite plan, а не только по абстрактной метке улучшения

Если LLM недоступна, система автоматически падает обратно в детерминированный режим без ошибок.

## Что контролируют rules

Даже в hybrid-режиме результат проходит через ограничения:

- память ленты и последних постов
- open loops
- backlog тем
- editorial feedback
- терминологию и табу-слова
- CTA-логику
- ограничение на перегрев ИИ-тем
- semantic similarity и novelty statuses
- content-plan slot planning
- style / polish / critic слои

## Что именно теперь остаётся детерминированным

Даже без LLM проект сохраняет полезную semantic-логику:

- normalizer карточек поста;
- rules-only extractor;
- semantic similarity / novelty classification;
- planner slot planning;
- critic semantic repeat detection;
- rewrite fallback по explicit rewrite plan.

То есть LLM здесь используется как semantic classifier и text generator, но не как единственный носитель логики.

## Как проверить novelty status без чтения всего кода

Практический порядок:

1. Запустить planner и посмотреть:
   - `recommended_slot`
   - `best_next_topics[*].novelty_status`
   - `best_next_topics[*].reason`
   - `best_next_topics[*].allowed_reframes`
2. Если нужно проверить уже готовый текст:
   - вызвать `critic_review(text)`
   - посмотреть `semantic_repeat_risk`
   - посмотреть `semantic_repeat_note`

Интерпретация статусов:

- `fresh` — semantic neighbors не блокируют новую подачу;
- `reframe_allowed` — тезис можно брать только через новый угол или формат;
- `series_continuation` — лучше подавать как продолжение уже начатой серии;
- `too_close` — сейчас это слишком близко к недавнему посту.

## Как включить

Нужно задать переменные окружения:

```bash
export CONTENT_BOT_LLM_MODE=hybrid
export OPENAI_API_KEY="..."
```

Опционально можно явно указать модель и уровень reasoning:

```bash
export CONTENT_BOT_LLM_MODEL="gpt-5-mini"
export CONTENT_BOT_LLM_REASONING_EFFORT="minimal"
```

После этого можно запускать бота как обычно.

Пример:

```bash
cd "/Users/dpedcenko/Codex — Контент-мейкер"
PYTHONPATH=content-bot \
CONTENT_BOT_LLM_MODE=hybrid \
CONTENT_BOT_LLM_MODEL="gpt-5-mini" \
OPENAI_API_KEY="..." \
TELEGRAM_BOT_TOKEN="..." \
TELEGRAM_ALLOWED_USER_IDS="261230790" \
python3 content-bot/scripts/run_telegram_polling.py
```

## Поведение по умолчанию

Если не задан `OPENAI_API_KEY`, бот не ломается.
Он просто продолжает работать на текущем rule-based движке.

Если `CONTENT_BOT_LLM_MODEL` не задана, бот по умолчанию возьмёт `gpt-5-mini`.
