# Следующие шаги по внедрению

## Что уже внедрено

Базовый editorial semantic layer уже есть в проекте:

- нормализатор semantic metadata в карточке поста;
- extractor для постов и тем;
- semantic similarity и novelty statuses;
- planner slot planning поверх coverage ленты;
- explicit rewrite plan;
- retro-enrichment CLI для старого архива;
- минимальный набор unit/smoke tests.

Этот файл теперь играет роль краткого operational handoff по следующим шагам.

## Этап 1. Собрать память

1. Распарсить `messages.txt` в отдельные посты.
2. Отфильтровать служебные сообщения и шум.
3. Запустить retro-enrichment старого архива:
   - `python3 content-bot/scripts/enrich_posts_editorial_metadata.py --dry-run --mode rules-only`
   - `python3 content-bot/scripts/enrich_posts_editorial_metadata.py --mode rules-only`
4. Для последних 40-60 постов точечно проверить:
   - `primary_theme`
   - `primary_thesis`
   - `angle`
   - `content_goal`
   - `funnel_stage`
   - `business_dimensions`

## Этап 2. Держать четыре режима модели

Нужны четыре отдельных prompt/logic режима:

1. `planner`
   Выбирает следующий content-plan slot, затем лучшую тему и объясняет почему.
2. `editorial_extractor`
   Классифицирует посты и темы как semantic metadata, а не пишет текст.
3. `writer`
   Пишет пост по выбранной теме.
4. `critic`
   Проверяет пост на повтор, стиль и метод.
5. `polish`
   Превращает хороший черновик в более естественную публикационную версию.
6. `generate_publishable_post`
   Прогоняет весь конвейер и отдаёт лучший финальный вариант для публикации.

## Этап 3. Подключить дополнительные источники голоса

После запуска основной версии добавить:

- транскрибации вебинаров;
- диалоги с клиентами;
- голосовые или видео-расшифровки.

Их лучше использовать как дополнительный корпус формулировок, а не как главный источник финального письма.

## Этап 4. Перенос в Telegram-бота

Telegram-бот должен быть только интерфейсом поверх ядра.

Минимальные команды:

- `/suggest` — предложить 3 темы на сейчас;
- `/draft` — написать пост по выбранной теме;
- `/check` — проверить черновик на стиль и повторы;
- `/memory` — показать, какие темы уже были недавно;
- `/backlog` — показать лучшие следующие темы.

## Этап 5. Что можно улучшить потом

- учитывать реакции и вовлеченность по постам;
- учиться на постах, которые вы реально публикуете без правок;
- привязывать внешние новости к уже существующим смысловым линиям канала;
- автоматически следить, чтобы ИИ не становился центральной темой слишком часто.
- показать в UI `recommended_slot`, перегретые зоны и allowed reframes;
- перевести все старые overlap-only проверки на единый semantic слой;
- расширить golden set и начать калибровку extractor/novelty classifier по реальным спорным кейсам.

## Evaluation Mode

Для explainability и калибровки уже добавлен evaluation mode:

- `python3 content-bot/scripts/review_editorial_semantic.py --input content-bot/examples/editorial_review_cases.json --mode rules-only`
- `python3 content-bot/scripts/evaluate_editorial_semantic.py --input content-bot/examples/editorial_golden_set.json --mode rules-only`
- `python3 content-bot/scripts/plan_next_topics.py --debug`
- `python3 content-bot/scripts/critic_post.py --file draft.txt --debug`

На что смотреть в первую очередь:

- корректно ли извлечены `primary_thesis`, `angle`, `content_goal`, `funnel_stage`;
- совпадает ли `novelty_status` с ближайшими `matched_posts`;
- выглядит ли `reason` как реальное объяснение решения, а не как формальность;
- какие поля чаще всего расходятся с golden set и требуют перекалибровки.
