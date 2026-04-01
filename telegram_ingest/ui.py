from __future__ import annotations


BUTTON_TOPICS = "✨ Предложить 5 тем"
BUTTON_SECTION_CASES = "🌐 Кейсы"
BUTTON_CASES = "🌐 Найти кейсы"
BUTTON_CHECK_CASE = "🔎 Проверить кейс"
BUTTON_MORE_CASES = "🔁 Ещё 5 кейсов"
BUTTON_RESET_CASES = "↩️ К первым 5 кейсам"
BUTTON_SECTION_ANALYTICS = "📊 Аналитика канала"
BUTTON_ANALYTICS = "📊 Аналитика ленты"
BUTTON_ROADMAP = "🗺 Roadmap"
BUTTON_EVALUATE = "🧭 Оценить мою тему"
BUTTON_EVALUATE_POST = "📝 Оценить пост"
BUTTON_WRITE = "✍️ Написать пост на мою тему"
BUTTON_MODE_EXPERT = "🧠 Экспертный"
BUTTON_MODE_MONEY = "💸 Денежный"
BUTTON_MODE_CONVERSATIONAL = "🗣 Разговорный"
BUTTON_SECTION_MY_TOPICS = "📚 Мои темы"
BUTTON_SAVE_TOPICS = "💾 Сохранить темы"
BUTTON_VIEW_BACKLOG = "📚 Мои сохранённые темы"
BUTTON_SECTION_REWRITE = "♻️ Рерайт"
BUTTON_REWRITE = "♻️ Рерайт поста"
BUTTON_MORE_TOPICS = "🔁 Ещё 5 вариантов"
BUTTON_RESET_TOPICS = "↩️ К первым 5 темам"
BUTTON_BACK_TO_MENU = "⬅️ В меню"
BUTTON_BACKLOG_MARK_USED = "✅ Отметить использованной"
BUTTON_BACKLOG_DELETE = "🗑️ Удалить тему"

CALLBACK_REVISE = "post:revise"
CALLBACK_ACCEPT = "post:accept"
CALLBACK_FORGET = "post:forget"
CALLBACK_NEXT_VARIANT = "post:next_variant"
CALLBACK_ANALYZE = "post:analyze"
CALLBACK_IMPROVE = "post:improve"
CALLBACK_REWRITE_OPTION_1 = "post:rewrite_option_1"
CALLBACK_REWRITE_OPTION_2 = "post:rewrite_option_2"
CALLBACK_SAVE_RULE = "post:save_rule"
CALLBACK_SAVE_TO_TOPICS = "post:save_to_topics"
CALLBACK_BUILD_VERIFIED_CASE_POST = "case:build_post"
CALLBACK_SAVE_VERIFIED_CASE = "case:save"
CALLBACK_CASE_TOPIC_PICK_PREFIX = "case:topic:"


def build_main_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": BUTTON_TOPICS}],
            [{"text": BUTTON_SECTION_CASES}],
            [{"text": BUTTON_SECTION_ANALYTICS}],
            [{"text": BUTTON_SECTION_MY_TOPICS}],
            [{"text": BUTTON_SECTION_REWRITE}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def build_cases_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": BUTTON_CASES}],
            [{"text": BUTTON_CHECK_CASE}],
            [{"text": BUTTON_BACK_TO_MENU}],
        ],
        "resize_keyboard": True,
        "is_persistent": False,
    }


def build_analytics_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": BUTTON_ANALYTICS}],
            [{"text": BUTTON_ROADMAP}],
            [{"text": BUTTON_EVALUATE}],
            [{"text": BUTTON_EVALUATE_POST}],
            [{"text": BUTTON_BACK_TO_MENU}],
        ],
        "resize_keyboard": True,
        "is_persistent": False,
    }


def build_my_topics_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": BUTTON_WRITE}],
            [{"text": BUTTON_SAVE_TOPICS}],
            [{"text": BUTTON_VIEW_BACKLOG}],
            [{"text": BUTTON_BACK_TO_MENU}],
        ],
        "resize_keyboard": True,
        "is_persistent": False,
    }


def build_rewrite_menu_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": BUTTON_REWRITE}],
            [{"text": BUTTON_BACK_TO_MENU}],
        ],
        "resize_keyboard": True,
        "is_persistent": False,
    }


def build_topic_pick_keyboard(count: int) -> dict:
    number_row = [{"text": str(index)} for index in range(1, count + 1)]
    return {
        "keyboard": [
            number_row,
            [{"text": BUTTON_MORE_TOPICS}],
            [{"text": BUTTON_RESET_TOPICS}],
            [{"text": BUTTON_BACK_TO_MENU}],
        ],
        "resize_keyboard": True,
        "is_persistent": False,
    }


def build_case_pick_keyboard(count: int) -> dict:
    number_row = [{"text": str(index)} for index in range(1, count + 1)]
    return {
        "keyboard": [
            number_row,
            [{"text": BUTTON_MORE_CASES}],
            [{"text": BUTTON_RESET_CASES}],
            [{"text": BUTTON_BACK_TO_MENU}],
        ],
        "resize_keyboard": True,
        "is_persistent": False,
    }


def build_post_mode_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": BUTTON_MODE_EXPERT}, {"text": BUTTON_MODE_MONEY}],
            [{"text": BUTTON_MODE_CONVERSATIONAL}],
            [{"text": BUTTON_BACK_TO_MENU}],
        ],
        "resize_keyboard": True,
        "is_persistent": False,
    }


def build_backlog_keyboard(count: int) -> dict:
    number_row = [{"text": str(index)} for index in range(1, count + 1)]
    return {
        "keyboard": [
            number_row,
            [{"text": BUTTON_BACKLOG_MARK_USED}, {"text": BUTTON_BACKLOG_DELETE}],
            [{"text": BUTTON_BACK_TO_MENU}],
        ],
        "resize_keyboard": True,
        "is_persistent": False,
    }


def build_post_actions_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "🔁 Ещё вариант", "callback_data": CALLBACK_NEXT_VARIANT},
                {"text": "✏️ Доработать пост", "callback_data": CALLBACK_REVISE},
            ],
            [
                {"text": "📋 Анализ", "callback_data": CALLBACK_ANALYZE},
                {"text": "✨ 2 улучшения", "callback_data": CALLBACK_IMPROVE},
            ],
            [
                {"text": "💾 Сохранить в темы", "callback_data": CALLBACK_SAVE_TO_TOPICS},
            ],
            [
                {"text": "🧠 Сохранить как правило", "callback_data": CALLBACK_SAVE_RULE},
            ],
            [
                {"text": "✅ Принят", "callback_data": CALLBACK_ACCEPT},
                {"text": "🗑️ Удалить из памяти", "callback_data": CALLBACK_FORGET},
            ],
        ]
    }


def build_post_improvement_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "1️⃣ Переписать по 1", "callback_data": CALLBACK_REWRITE_OPTION_1},
                {"text": "2️⃣ Переписать по 2", "callback_data": CALLBACK_REWRITE_OPTION_2},
            ],
            [
                {"text": "✏️ Внести изменения", "callback_data": CALLBACK_REVISE},
                {"text": "🧠 В правило", "callback_data": CALLBACK_SAVE_RULE},
            ],
            [
                {"text": "✅ Принят", "callback_data": CALLBACK_ACCEPT},
            ]
        ]
    }


def build_verified_case_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✍️ Собрать пост", "callback_data": CALLBACK_BUILD_VERIFIED_CASE_POST},
                {"text": "💾 Сохранить в темы", "callback_data": CALLBACK_SAVE_VERIFIED_CASE},
            ],
            [
                {"text": "⬅️ В меню", "callback_data": CALLBACK_ACCEPT},
            ],
        ]
    }


def build_case_topic_suggestion_keyboard(count: int) -> dict:
    buttons = [
        {"text": f"🧠 Тема {index}", "callback_data": f"{CALLBACK_CASE_TOPIC_PICK_PREFIX}{index - 1}"}
        for index in range(1, count + 1)
    ]
    rows: list[list[dict]] = []
    for idx in range(0, len(buttons), 2):
        rows.append(buttons[idx : idx + 2])
    rows.append([{"text": "⬅️ В меню", "callback_data": CALLBACK_ACCEPT}])
    return {"inline_keyboard": rows}
