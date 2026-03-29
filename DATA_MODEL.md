# Модель данных для контент-бота

## 1. Карточка поста

Одна запись на один опубликованный пост.

```json
{
  "post_id": "2026-03-05_2042",
  "date": "2026-03-05",
  "source": "telegram_channel",
  "title_hook": "Часто предприниматели решают не те проблемы",
  "body_summary": "Автор объясняет, что бизнес лечит симптомы, пока модель управления не соответствует стадии развития.",
  "primary_theme": "диагностика управленческих причин",
  "secondary_themes": ["стадия бизнеса", "реактивное управление"],
  "primary_thesis": "Бизнес лечит симптомы, пока модель управления не соответствует стадии развития.",
  "secondary_theses": ["сначала диагностировать архитектурную причину", "не путать симптомы со стадией"],
  "angle": "зайти через ошибку собственника, который оптимизирует не тот слой системы",
  "content_goal": "diagnostic",
  "format": "expert",
  "format_type": "expert",
  "content_role": "diagnostic",
  "funnel_stage": "problem-aware",
  "business_dimensions": ["управление", "операционка", "прибыль"],
  "novelty_window_days": 30,
  "core_thesis": "Проблемы накапливаются, когда руководитель работает с последствиями, а не с архитектурной причиной.",
  "cta_type": "soft",
  "cta_present": true,
  "cta_target": "video_or_bot",
  "hashtags": ["мысли", "управление"],
  "mentions_ai": false,
  "mentions_offer": true,
  "related_previous_post_id": "2026-02-13_0000",
  "novelty_keys": ["симптом_vs_причина", "стадия_развития", "архитектурный_разрыв"]
}
```

## 2. Карта тем

Одна запись на тему, а не на пост.

```json
{
  "theme_id": "owner_role_vs_operations",
  "theme_name": "роль собственника и перегрузка операционкой",
  "times_used_total": 7,
  "times_used_last_30d": 2,
  "last_used_at": "2026-03-05",
  "angles_used": [
    "симптомы перегрузки",
    "стадия развития бизнеса",
    "не те управленческие решения"
  ],
  "angles_missing": [
    "цена для собственника",
    "ошибка делегирования без роли",
    "кейсовый разбор"
  ],
  "status": "active",
  "repeat_risk": "medium",
  "recommended_next_angle": "делегирование без роли создает псевдоразгрузку"
}
```

## 3. Backlog тем

Очередь потенциальных постов.

```json
{
  "theme": "ИИ в найме и адаптации",
  "angle": "ИИ ускоряет рутину, но не заменяет владельца процесса",
  "goal": "expert",
  "priority": 7,
  "best_after_topic": "роль и владелец процесса",
  "risk_of_repeat": "medium",
  "evidence_source": "web_research,messages,webinar",
  "offer_fit": "diagnostic",
  "status": "ready"
}
```

## 4. Что важно хранить обязательно

- дата публикации;
- тема;
- тезис;
- primary thesis / secondary theses;
- editorial angle;
- content goal и format type;
- business dimensions и novelty window;
- формат;
- роль поста в ленте;
- CTA;
- наличие ИИ;
- связь с предыдущими постами;
- риск повтора.

Без этого нельзя качественно планировать следующий пост.

## 5. Совместимость со старыми карточками

Новый editorial semantic layer добавляется мягко:

- старые строки в `posts_index.jsonl` могут не содержать новые поля;
- при чтении и записи применяется единый normalizer;
- `primary_thesis` по умолчанию наследуется из `core_thesis`;
- `secondary_theses` по умолчанию наследуется из `secondary_themes`;
- `format_type` по умолчанию наследуется из `format`;
- `content_goal` по умолчанию наследуется из `content_role`;
- `novelty_window_days` по умолчанию равен `30`.

## 6. Extractor и semantic enrichment

Для новых постов и тем semantic layer строится через `editorial_extractor`.

Он работает в двух режимах:

- `rules-only` — локальные эвристики и безопасные defaults;
- `hybrid LLM` — отдельный classification prompt, который возвращает строгое JSON-представление semantic metadata.

Extractor не пишет красивый текст. Его роль только классифицировать:

- какой тезис главный;
- какие поддерживающие тезисы есть;
- под каким углом это раскрыто;
- какой content goal и funnel stage у темы;
- какие business dimensions затронуты;
- какой format type и novelty window подходят.

## 7. Semantic similarity и novelty statuses

Сравнение тем и постов теперь строится не только по lexical overlap.

Основные поля для similarity:

- `primary_thesis`
- `secondary_theses`
- `angle`
- `business_dimensions`
- `funnel_stage`
- `format_type`
- `novelty_window_days`

Статусы новизны:

- `fresh`
  Тезис и угол достаточно далеки от недавнего архива.
- `reframe_allowed`
  Центральный тезис уже звучал, но допустим новый угол, формат или другой slot в ленте.
- `series_continuation`
  Это не новая тема сама по себе, а логичное продолжение уже начатой линии.
- `too_close`
  Пост или тема слишком близки к недавней публикации, поэтому их нельзя подавать как свежую рекомендацию.

## 8. Planner slots

Planner теперь думает не только темами, но и слотами контент-плана.

Сначала считается coverage последних 15-20 постов по:

- `business_dimensions`
- `angles`
- `funnel_stage`
- `content_goal`
- `format_type`

Потом выбирается `recommended_slot`, в котором фиксируется:

- что перегрето;
- чего не хватает;
- какой следующий слой ленты нужен сейчас.

И только после этого под слот подбирается тема.

## 9. Как проверить, почему тема получила свой status

Практическая проверка делается так:

1. Посмотреть `recommended_slot` в planner output.
2. Посмотреть у кандидата:
   - `primary_thesis`
   - `angle`
   - `content_goal`
   - `funnel_stage`
   - `business_dimensions`
   - `format_type`
   - `novelty_status`
   - `reason`
   - `allowed_reframes`
3. Сравнить кандидата с ближайшими semantic neighbors из архива.

Интерпретация:

- `fresh`: близкого тезиса в окне новизны нет;
- `reframe_allowed`: тезис повторяет линию, но угол или формат можно сменить;
- `series_continuation`: лучше подавать как продолжение серии;
- `too_close`: слишком близко по тезису и подаче к недавней публикации.
