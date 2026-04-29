from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass

from .config import MEMORY_DIR, POSTS_INDEX_PATH
from .hybrid_llm import generate_core_idea, maybe_generate_writer_drafts
from .knowledge import load_editorial_feedback, load_terminology_registry
from .planner_engine import plan_next_topics
from .positioning import get_positioning_flags, resolve_cta_strategy

LOGGER = logging.getLogger(__name__)


CTA_LIBRARY = {
    "optional": [
        "Если тема отзывается, напиши в комментариях, где у тебя это проявляется сильнее всего.",
        "Если узнаёшь в этом свой бизнес, напиши в комментариях, какой момент здесь для тебя самый болезненный.",
        "Если будет отклик, можно продолжить это обсуждение в комментариях и разобрать следующий слой темы.",
    ],
    "soft": [
        "Если хочешь быстро понять, на какой стадии сейчас твой бизнес и где главный перекос, можешь пройти бесплатную диагностику в @adizesbizbot.",
        "Если видишь, что тема уже упирается в систему управления, можно пройти диагностику в @adizesbizbot и быстро увидеть главный перекос.",
        "Если понимаешь, что здесь нужен уже персональный разбор именно твоей ситуации, можешь написать мне в личку @pda33.",
    ],
    "comment": [
        "Если тема отзывается, напиши в комментариях, где у тебя это проявляется сильнее всего.",
        "Если узнаёшь в этом свой бизнес, можно продолжить разговор в комментариях и посмотреть, у кого это болит так же.",
        "Если будет отклик, давайте разберём это в комментариях глубже и посмотрим, какой следующий слой темы нужен.",
    ],
    "discussion_soft": [
        "Если тема отзывается, напиши в комментариях, что здесь оказалось самым точным именно для твоего бизнеса.",
        "Если узнаёшь этот перекос у себя, напиши в комментариях, где он проявляется сильнее всего.",
    ],
    "personal_targeted": [
        "Если понимаешь, что здесь уже нет времени на эксперименты и хочется быстрее собрать рабочее решение, пиши @pda33.",
        "Если видишь, что процессы или структура уже проседают и хочется разобрать это предметно, можешь написать мне в личку @pda33.",
        "Если хочешь не теорию, а персональный разбор по своей ситуации, пиши @pda33 — посмотрим, где именно у тебя сейчас теряется эффективность.",
    ],
    "hard": [
        "Если видишь, что бизнес уже упирается не в локальную задачу, а в саму конструкцию управления, можно обсудить формат «Антикризисная стабилизация бизнеса за 45 дней».",
        "Если понимаешь, что здесь уже нужен не совет, а быстрая пересборка системы, логичный следующий шаг — «Антикризисная стабилизация бизнеса за 45 дней».",
    ],
}

HASHTAG_BY_THEME = {
    "оргструктура и роли": "#структура",
    "регламенты и процессы": "#регламенты",
    "перегрузка собственника": "#управление",
    "скрытые потери в операционке": "#управление",
    "работа с причинами, а не симптомами": "#мысли",
    "систематизация и управляемость": "#управление",
    "разбор типичных причинно-следственных ошибок собственника по стадиям бизнеса": "#управление",
    "ввод воронки через диагностику стадий бизнеса": "#управление",
    "рост расходов и оптимизация затрат": "#управление",
}

EMOJI_BY_THEME = {
    "оргструктура и роли": ["🧠", "📍", "⚙️"],
    "регламенты и процессы": ["📋", "⚙️", "📍"],
    "перегрузка собственника": ["⚠️", "📍", "🧩"],
    "скрытые потери в операционке": ["🔍", "💸", "⚙️"],
    "работа с причинами, а не симптомами": ["❌", "📍", "⚙️"],
    "разбор типичных причинно-следственных ошибок собственника по стадиям бизнеса": ["📉", "⚠️", "🎯"],
    "ввод воронки через диагностику стадий бизнеса": ["📊", "🚨", "🎯"],
    "рост расходов и оптимизация затрат": ["📉", "💸", "📍"],
}

STRUCTURE_BLUEPRINTS = [
    ["hook", "scene", "transition", "reason", "focus", "solution", "effect", "reference_tail", "cta"],
    ["hook", "reason", "scene", "focus", "solution", "effect", "reference_tail", "cta"],
    ["hook", "scene", "focus", "reason", "solution", "reference_tail", "effect", "cta"],
    ["hook", "scene", "reason", "transition", "solution", "focus", "effect", "reference_tail", "cta"],
]

TOPIC_PROFILES = {
    "ии, порядок, процессы и кейсы": {
        "label": "ии в собранной системе",
        "hook": [
            "ИИ сам по себе не создаёт порядок в бизнесе.",
            "Многие компании ждут от ИИ скорости. Но без процесса и владельца результата он чаще просто ускоряет хаос.",
            "Когда в бизнесе нет нормальной процессной сборки, ИИ становится не усилителем, а множителем разнобоя.",
        ],
        "scene": [
            "Снаружи всё может выглядеть терпимо. Но внутри команда тратит силы на лишние действия, решения подвисают, а собственник снова и снова становится точкой сборки.",
            "Обычно это видно по очень простым вещам: задачи идут рывками, ответственность плавает, а новый инструмент добавляет шума больше, чем результата.",
        ],
        "reason": "Проблема чаще не в инструменте. Не хватает процесса, понятного результата, владельца и ритма контроля, в который этот инструмент вообще можно встроить.",
        "solution": "Поэтому начинать лучше не с подключения ИИ, а с базовой управленческой сборки:\n– определить результат;\n– закрепить владельца;\n– описать ход процесса;\n– поставить точку контроля.\n\nИ только потом подключать ИИ к уже собранной конструкции.",
        "effect": "Тогда ИИ действительно начинает давать скорость и экономить время. Без этого он только быстрее размазывает старые сбои по всей системе.",
    },
    "оргструктура и роли": {
        "label": "оргструктура",
        "hook": [
            "Сильная команда сама по себе ещё не делает бизнес управляемым.",
            "Многие собственники думают, что проблема в людях. На практике часто проблема в роли, которой в системе просто нет.",
            "Пока в компании не описаны роли, любой рост начинает опираться на ручное вмешательство собственника.",
        ],
        "scene": [
            "Выглядит это обычно так: сотрудники хорошие, задачи двигаются, но любой нестандартный вопрос всё равно прилетает владельцу. Не потому что команда слабая, а потому что границы решений никто не зафиксировал.",
            "Снаружи всё похоже на рабочий порядок. Но как только возрастает нагрузка, выясняется, что решения принимаются не внутри ролей, а через постоянные уточнения у собственника.",
        ],
        "reason": "Причина обычно не в дисциплине. Просто компания выросла, а роли и ответственность так и остались на уровне 'договорились устно'.",
        "solution": "Здесь полезно начать с трёх вещей:\n– определить, какой результат держит каждая ключевая роль;\n– разделить зоны решений, а не только список задач;\n– закрепить, где сотрудник решает сам, а где поднимает вопрос дальше.",
        "effect": "После этого команда перестаёт работать в режиме постоянных уточнений. Появляется управляемость, а собственник перестаёт быть обязательной прослойкой между всеми функциями.",
    },
    "скрытые потери в операционке": {
        "label": "скрытые потери",
        "hook": [
            "Когда в бизнесе говорят про сокращение издержек, почти всегда режут не там.",
            "Самые дорогие потери в компании обычно не видны в строке расходов.",
            "Проблема многих компаний не в том, что они мало зарабатывают. Проблема в том, что слишком много теряют внутри операционки.",
        ],
        "scene": [
            "На поверхности всё выглядит привычно: люди заняты, процессы идут, клиенты не уходят массово. Но деньги и время утекают в ручных согласованиях, переделках, провалах на стыках и решениях 'по ощущениям'.",
            "Собственник видит ФОТ, рекламу, аренду и пытается оптимизировать именно это. А реальные потери лежат глубже: в сбоях процессов, неверных приоритетах и в том, что половина команды делает лишнюю работу.",
        ],
        "reason": "Пока компания не видит процесс как связную рабочую логику с ответственным и точкой контроля, она лечит видимые расходы и не трогает источник утечки.",
        "solution": "Поэтому сначала имеет смысл не 'резать затраты', а посмотреть:\n– где теряется время;\n– где решения застревают между функциями;\n– где ошибки стали привычной нормой и уже не замечаются командой.",
        "effect": "Именно здесь часто лежит самый быстрый эффект: меньше ручного шума, меньше потерь, выше предсказуемость и понятнее, где реально прячется прибыль.",
    },
    "работа с причинами, а не симптомами": {
        "label": "причины вместо симптомов",
        "hook": [
            "Часто предприниматели чинят не ту поломку.",
            "В бизнесе очень легко перепутать симптом с причиной.",
            "Самая дорогая управленческая ошибка — решать то, что видно, и не трогать то, что ломает систему изнутри.",
        ],
        "scene": [
            "Меняют сотрудников. Ужесточают контроль. Подключают новый инструмент. На пару недель становится спокойнее, а потом всё возвращается в той же форме или ещё тяжелее.",
            "Проблема обычно выглядит как частная: провалился срок, не сработал руководитель, буксует отдел. Но если копнуть глубже, причина часто лежит в модели управления, которая уже не соответствует масштабу бизнеса.",
        ],
        "reason": "Когда компания вырастает, а способ управления остаётся прежним, собственник начинает постоянно работать с последствиями. Симптомы меняются, а корневая причина остаётся той же.",
        "solution": "Поэтому полезно разбирать не только сам сбой, но и три вопроса:\n– что именно сломалось в самом управлении;\n– на какой стадии бизнеса это стало нормой;\n– какая роль, процесс или ритм контроля здесь отсутствует.",
        "effect": "Тогда решения перестают быть реактивными. Бизнес начинает лечить источник проблемы, а не тратить силы на бесконечную борьбу с последствиями.",
    },
    "разбор типичных причинно-следственных ошибок собственника по стадиям бизнеса": {
        "label": "ошибки по стадиям бизнеса",
        "hook": [
            "У вас текучка, слабые руководители или постоянная путаница между отделами?",
            "Один и тот же симптом в бизнесе на разных этапах роста может означать разные управленческие проблемы.",
            "Если не понимать, на каком этапе сейчас бизнес, очень легко лечить не ту проблему.",
        ],
        "scene": [
            "Например, текучка в команде из 10 человек чаще говорит о хаотичном найме. Та же текучка в компании на 40 человек уже может означать слабую адаптацию, перегруз руководителей или размытые ожидания от роли.",
            "Снаружи это выглядит как набор одинаковых проблем: текучка, слабые руководители, путаница между отделами. Но у бизнеса на каждом этапе роста причина этих симптомов обычно разная.",
        ],
        "reason": "Суть в том, что бизнес меняется быстрее, чем управленческая модель собственника. И когда она не успевает перестроиться, кризис проявляется не как теория, а как деньги, сроки, нагрузка и потеря контроля.",
        "solution": "Поэтому здесь полезно проверять не только сам симптом, но и три вещи:\n– бизнес всё ещё держится на собственнике или уже упирается в слабый средний слой;\n– команда не справляется из-за людей или из-за размытых ролей и ожиданий;\n– проблема в одном отделе или уже в стыках между функциями.\n\nЭто и есть практическая диагностика. Она помогает понять, что именно чинить: найм, адаптацию, руководителей, роли или саму конструкцию управления.",
        "effect": "Так у собственника появляется не просто объяснение хаоса, а понятная точка приложения усилий. А значит, меньше случайных решений и больше управляемого движения вперёд.",
    },
    "ввод воронки через диагностику стадий бизнеса": {
        "label": "диагностика стадии бизнеса",
        "hook": [
            "Большинство собственников чувствуют, что бизнес буксует, но не могут точно назвать, где именно главный перекос.",
            "Когда собственник не понимает стадию бизнеса, он почти всегда начинает лечить не ту проблему.",
            "Пока неясно, на какой стадии находится компания, любые управленческие решения становятся стрельбой по туману.",
        ],
        "scene": [
            "Владелец видит симптомы: перегруз, разрывы между отделами, нестабильный рост, слабые руководители. Но без понимания стадии бизнеса всё это выглядит как хаотичный набор отдельных проблем.",
            "Обычно в этот момент предприниматель идёт в инструменты: меняет CRM, вводит новые отчёты, ищет 'сильного операционного'. Но если стадия определена неверно, решения почти всегда бьют мимо.",
        ],
        "reason": "На каждой стадии у бизнеса свой типичный кризис, свой перекос управленческих функций и свой правильный фокус внимания. Без этой рамки даже разумные действия могут не дать результата.",
        "solution": "Поэтому начинать здесь лучше с диагностики, а не с очередного инструмента. Сначала понять стадию, затем увидеть типичный кризис и только потом выбирать управленческий шаг.",
        "effect": "Это резко повышает точность решений. Собственник перестаёт метаться между симптомами и получает понятный ориентир, что именно в управлении нужно чинить первым.",
    },
    "рост расходов и оптимизация затрат": {
        "label": "оптимизация затрат",
        "hook": [
            "Бизнес становится всё дороже. Но проблема часто не только в налогах, ценах и ставках.",
            "Когда всё вокруг дорожает, многие компании начинают экономить слишком быстро и не там.",
            "В период роста расходов вопрос уже не в абстрактной эффективности. Вопрос в том, где именно бизнес теряет деньги каждый день.",
        ],
        "scene": [
            "Собственник режет очевидное: бюджеты, найм, подрядчиков, маркетинг. Иногда это даёт короткий эффект. Но очень часто вместе с расходами режется и способность бизнеса нормально работать.",
            "Сначала может казаться, что главная задача сейчас — просто сократить затраты. Но внутри компании деньги продолжают утекать в переделки, сбои процессов, хаотичные решения и перегруженную операционку.",
        ],
        "reason": "Когда компания не различает внешнее давление рынка и внутренние потери системы, она начинает лечить кассу, но не трогает управленческую причину.",
        "solution": "Поэтому в такой период полезно смотреть не только на статьи расходов, но и на три зоны:\n– где бизнес теряет время;\n– где решения стоят слишком дорого из-за ручного режима;\n– где процессные разрывы уже превращаются в прямые финансовые потери.",
        "effect": "Тогда экономия перестаёт быть хаотичной обороной. Появляется более точная управленческая логика: что действительно резать, что перестраивать, а что защищать как опору прибыли.",
    },
}


@dataclass
class DraftContext:
    theme: str
    angle: str
    why_now: str
    content_role: str
    content_pillar: str
    post_format: str
    cta_need: str
    business_goal: str
    cta_balance: dict
    preferred_cta_mode: str | None
    case_context: dict | None
    user_theme_verdict: dict
    reference_posts: list[dict]
    style_references: list[dict]
    positioning_flags: dict
    style_profile: dict
    user_preferences: dict
    golden_style_set: dict
    stop_words: dict
    terminology_registry: dict
    editorial_feedback: list[dict]
    conversational_style_library: dict


def load_posts() -> list[dict]:
    if not POSTS_INDEX_PATH.exists():
        return []
    rows = []
    for lineno, line in enumerate(POSTS_INDEX_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            logging.getLogger(__name__).warning("Skipping malformed line %d in posts_index.jsonl: %s", lineno, exc)
    return rows


def load_style_profile() -> dict:
    path = MEMORY_DIR / "style_profile.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_user_preferences() -> dict:
    path = MEMORY_DIR / "user_preferences.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_golden_style_set() -> dict:
    path = MEMORY_DIR / "golden_style_set.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_stop_words() -> dict:
    path = MEMORY_DIR / "stop_words.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_post_format_registry() -> dict:
    path = MEMORY_DIR / "post_format_registry.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_conversational_style_library() -> dict:
    path = MEMORY_DIR / "conversational_style_library.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def merge_stop_word_sources(stop_words: dict, terminology_registry: dict) -> dict:
    merged = dict(stop_words)
    taboo = list(merged.get("banned_phrases", []))
    for phrase in terminology_registry.get("taboo_phrases", []):
        if phrase not in taboo:
            taboo.append(phrase)
    merged["banned_phrases"] = taboo
    return merged


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def mentions_ai_topic(text: str) -> bool:
    lowered = text.lower()
    words = set(re.findall(r"[a-zа-я0-9]+", lowered))
    return any(token in words for token in ("ии", "ai", "gpt")) or "chatgpt" in lowered or "нейро" in lowered


def is_ai_core_topic(text: str) -> bool:
    lowered = text.lower()
    if not mentions_ai_topic(lowered):
        return False
    context_tokens = (
        "процесс",
        "поряд",
        "хаос",
        "бот",
        "внедр",
        "примен",
        "функц",
        "команд",
        "автомат",
        "контент",
        "кейс",
        "скорост",
        "результат",
        "готовност",
    )
    return any(token in lowered for token in context_tokens)


def choose_style_references(theme: str, rows: list[dict], golden_style_set: dict | None = None, limit: int = 3) -> list[dict]:
    theme_words = set(normalize(theme.lower()).split())
    golden_ids = set((golden_style_set or {}).get("post_ids", []))
    pool = [row for row in rows if row.get("post_id") in golden_ids] or rows
    scored: list[tuple[float, dict]] = []
    for row in pool:
        candidate_text = f"{row.get('primary_theme') or ''} {row.get('title_hook') or ''}".lower()
        candidate_words = set(normalize(candidate_text).split())
        if not candidate_words:
            continue
        score = len(theme_words & candidate_words) / len(theme_words | candidate_words)
        if score > 0:
            scored.append((score, row))

    if not scored:
        return pool[-limit:]

    scored.sort(key=lambda item: (item[0], item[1]["date"]), reverse=True)
    return [row for _, row in scored[:limit]]


def split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def extract_reference_patterns(reference_posts: list[dict]) -> dict:
    opening_types: list[str] = []
    body_modes: list[str] = []
    ending_modes: list[str] = []
    for row in reference_posts:
        paragraphs = split_paragraphs(row.get("body_text", ""))
        if not paragraphs:
            continue
        opening = paragraphs[0]
        opening_lower = opening.lower()
        if "?" in opening:
            opening_types.append("question")
        elif any(token in opening_lower for token in ("но ", "иногда", "когда", "почему")):
            opening_types.append("contrast")
        else:
            opening_types.append("statement")

        second = paragraphs[1].lower() if len(paragraphs) > 1 else ""
        if any(token in second for token in ("недавно", "в какой-то момент", "иногда", "кажется")):
            body_modes.append("reflective")
        elif any(token in second for token in ("собственник", "команда", "клиент", "подрядчик")):
            body_modes.append("scene")
        else:
            body_modes.append("diagnostic")

        tail = paragraphs[-1].lower()
        if "@adizesbizbot" in tail or "@pda33" in tail or "диагност" in tail:
            ending_modes.append("cta")
        elif "?" in tail:
            ending_modes.append("question")
        else:
            ending_modes.append("statement")

    return {
        "opening_type": opening_types[0] if opening_types else "statement",
        "body_mode": body_modes[0] if body_modes else "diagnostic",
        "ending_mode": ending_modes[0] if ending_modes else "statement",
    }


def build_context(
    theme: str | None,
    angle: str | None,
    business_goal: str,
    preferred_cta_mode: str | None = None,
    case_context: dict | None = None,
    topic_brief: dict | None = None,
) -> DraftContext:
    plan = plan_next_topics(user_theme=theme, business_goal=business_goal)
    selected = topic_brief or plan["recommended_topic_now"]
    if selected is None:
        raise ValueError("Planner did not return a topic")

    final_theme = theme or selected["theme"]
    final_angle = angle or selected["angle"]
    rows = load_posts()
    golden_style_set = load_golden_style_set()
    terminology_registry = load_terminology_registry()
    stop_words = merge_stop_word_sources(load_stop_words(), terminology_registry)
    editorial_feedback = load_editorial_feedback()
    references = choose_style_references(final_theme, rows, golden_style_set=golden_style_set)
    content_role = "case" if case_context else selected["content_role"]
    content_pillar = (case_context or {}).get("content_pillar") or selected.get("content_pillar") or business_goal
    why_now = (case_context or {}).get("fit_reason") or selected["why_now"]
    post_format = "case" if case_context else infer_post_format(final_theme, final_angle, selected["content_role"], business_goal)

    return DraftContext(
        theme=final_theme,
        angle=final_angle,
        why_now=why_now,
        content_role=content_role,
        content_pillar=content_pillar,
        post_format=post_format,
        cta_need=selected["cta_need"],
        business_goal=business_goal,
        cta_balance=plan.get("cta_balance", {}),
        preferred_cta_mode=preferred_cta_mode,
        case_context=case_context,
        user_theme_verdict=plan["user_theme_verdict"],
        reference_posts=references,
        style_references=references,
        positioning_flags=get_positioning_flags(),
        style_profile=load_style_profile(),
        user_preferences=load_user_preferences(),
        golden_style_set=golden_style_set,
        stop_words=stop_words,
        terminology_registry=terminology_registry,
        editorial_feedback=editorial_feedback,
        conversational_style_library=load_conversational_style_library(),
    )


def infer_post_format(theme: str, angle: str, content_role: str, business_goal: str) -> str:
    normalized_theme = theme.lower()
    normalized_angle = angle.lower()
    if business_goal == "conversational":
        return "reflective"
    if any(token in normalized_angle for token in ("3-5", "3–5", "3 ошибки", "4 признака", "5 шаг")):
        return "list"
    if any(token in normalized_theme for token in ("стад", "кризис", "диагност", "симптом", "причин", "издерж", "расход")):
        return "diagnostic"
    if any(token in normalized_theme for token in ("отношение", "мысл", "время", "свобод")):
        return "reflective"
    if content_role == "diagnostic":
        return "diagnostic"
    if business_goal == "image":
        return "reflective"
    return "explainer"


def infer_profile(theme: str) -> dict:
    normalized_theme = theme.lower()
    if all(token in normalized_theme for token in ("ии", "процесс")) or (
        "ии" in normalized_theme and any(token in normalized_theme for token in ("поряд", "кейс", "скорост"))
    ):
        return TOPIC_PROFILES["ии, порядок, процессы и кейсы"]
    if any(token in normalized_theme for token in ("дороже", "налог", "цен", "эконом", "оптимизац", "расход", "издерж", "себестоим")):
        return TOPIC_PROFILES["рост расходов и оптимизация затрат"]
    for key, profile in TOPIC_PROFILES.items():
        if key in normalized_theme or normalized_theme in key:
            return profile
    if any(token in normalized_theme for token in ("стад", "кризис", "жизненного цикла", "adizes")):
        return TOPIC_PROFILES["разбор типичных причинно-следственных ошибок собственника по стадиям бизнеса"]
    if any(token in normalized_theme for token in ("оргструкт", "роль", "ответствен")):
        return TOPIC_PROFILES["оргструктура и роли"]
    if any(token in normalized_theme for token in ("издерж", "потер", "операцион")):
        return TOPIC_PROFILES["скрытые потери в операционке"]
    if any(token in normalized_theme for token in ("симптом", "причин")):
        return TOPIC_PROFILES["работа с причинами, а не симптомами"]
    return {
        "label": theme.lower(),
        "hook": [
            "Иногда проблема выглядит локальной, хотя на деле упирается в саму конструкцию управления.",
            "Большинство компаний замечают это слишком поздно — когда проблема уже начинает стоить денег и времени владельца.",
            "Когда эта зона в бизнесе не собрана как система, последствия почти всегда догоняют собственника лично.",
        ],
        "scene": [
            "Обычно это выглядит не как большая катастрофа, а как постоянный ручной шум: уточнения, переделки, зависания решений и ощущение, что без владельца ничего не собирается в целое.",
            "Снаружи всё может выглядеть терпимо. Но внутри команда тратит силы на лишние действия, решения подвисают, а собственник снова и снова становится точкой сборки.",
        ],
        "reason": "Проблема здесь редко в одном человеке или одном инструменте. Чаще всего не хватает роли, процесса, понятного результата и ритма контроля.",
        "solution": "Поэтому начинать полезно не с косметических правок, а с базовой управленческой сборки:\n– определить результат;\n– закрепить владельца;\n– описать ход процесса;\n– поставить точку контроля.",
        "effect": "После этого зона перестаёт держаться на ручном включении. Появляется порядок, снижаются потери и становится проще принимать решения без постоянного тушения локальных сбоев.",
    }


def build_hook(profile: dict, variant: int) -> str:
    return profile["hook"][variant % len(profile["hook"])]


def build_scene(profile: dict, variant: int) -> str:
    return profile["scene"][variant % len(profile["scene"])]


def build_reason(profile: dict, angle: str, variant: int) -> str:
    base = profile["reason"]
    if variant % 3 == 1:
        return f"Если копнуть глубже, дело обычно не в поверхности. {base}"
    if variant % 3 == 2:
        return f"Если разбирать это трезво, {base[0].lower() + base[1:]}"
    return base


def build_solution(profile: dict, theme: str, variant: int) -> str:
    solution = profile["solution"]
    prefix_replacements = [
        ("Поэтому в такой период полезно", "В такой период полезно", 0),
        ("Поэтому начинать полезно", "Здесь полезно начинать", 0),
        ("Поэтому полезно", "Здесь полезно", 0),
        ("Поэтому ", "Здесь ", 0),
        ("Поэтому в такой период полезно", "Если смотреть практично, в такой период лучше", 1),
        ("Поэтому начинать полезно", "На практике лучше начинать", 1),
        ("Поэтому полезно", "На практике лучше", 1),
        ("Поэтому ", "На практике ", 1),
        ("Поэтому в такой период полезно", "В такой ситуации важно", 2),
        ("Поэтому начинать полезно", "В такой ситуации важно начинать", 2),
        ("Поэтому полезно", "В такой ситуации важно", 2),
        ("Поэтому ", "В такой ситуации ", 2),
    ]
    for old, new, replacement_variant in prefix_replacements:
        if variant % 3 == replacement_variant and solution.startswith(old):
            solution = new + solution[len(old):]
            break
    if is_ai_core_topic(theme) and "подключать ии" not in solution.lower():
        solution = (
            f"{solution}\n\n"
            "И только после этого имеет смысл подключать ИИ. Иначе он ускорит не порядок, а уже существующий разнобой."
        )
    return solution


def adapt_parts_to_format(parts_map: dict[str, str], context: DraftContext, variant: int) -> dict[str, str]:
    if context.post_format == "reflective":
        parts_map["transition"] = ""
        if variant % 2 == 0:
            parts_map["solution"] = ""

    if context.post_format == "list":
        parts_map["solution"] = (
            "Если раскладывать это прикладно, полезно посмотреть на 3 вещи:\n"
            "– какой симптом вы видите сейчас;\n"
            "– что он означает именно на вашей стадии;\n"
            "– какую управленческую привычку уже пора менять."
        )

    if context.post_format == "diagnostic" and "стад" in context.theme.lower():
        if not parts_map["scene"].startswith("Например"):
            parts_map["scene"] = (
                "Например, текучка, слабые руководители или хаос между отделами на разных стадиях бизнеса означают разные причины.\n\n"
                + parts_map["scene"]
            )

    return parts_map


def build_effect(profile: dict, variant: int) -> str:
    base = profile["effect"]
    if variant % 3 == 1:
        return f"И тогда эффект уже другой. {base}"
    if variant % 3 == 2:
        return f"Тогда меняется и результат. {base}"
    return base


def build_transition(variant: int) -> str:
    variants = [
        "И вот здесь обычно начинается самое важное.",
        "На этом месте большинство компаний и делает дорогую ошибку.",
        "Дальше всё уже упирается не в старание, а в конструкцию управления.",
        "И в этот момент становится видно, где именно бизнес теряет управляемость.",
        "Дальше вопрос уже не в усилиях команды, а в качестве самой конструкции.",
    ]
    return variants[variant % len(variants)]


def tune_hook_with_references(base_hook: str, reference_patterns: dict, variant: int) -> str:
    opening_type = reference_patterns.get("opening_type", "statement")
    if opening_type == "contrast" and variant % 3 == 2 and "Но" not in base_hook:
        return f"{base_hook}\n\nНо снаружи это почти всегда выглядит проще, чем есть на самом деле."
    return base_hook


def tune_scene_with_references(base_scene: str, reference_patterns: dict, variant: int) -> str:
    body_mode = reference_patterns.get("body_mode", "diagnostic")
    if body_mode == "reflective" and variant % 2 == 0:
        return f"Я регулярно вижу этот перекос в разных компаниях.\n\n{base_scene}"
    if body_mode == "scene" and variant % 3 == 1:
        return f"Обычно это проявляется очень приземлённо.\n\n{base_scene}"
    if body_mode == "diagnostic" and variant % 3 == 2:
        return f"Если смотреть на это спокойнее, картина обычно выглядит так.\n\n{base_scene}"
    return base_scene


def build_reference_tail(reference_patterns: dict, variant: int) -> str:
    ending_mode = reference_patterns.get("ending_mode", "statement")
    if ending_mode == "question" and variant % 4 == 3:
        return "Если будет полезно, эту же тему можно дальше развернуть уже на реальной бизнес-сцене."
    if ending_mode == "statement" and variant % 4 == 2:
        return "Именно в этот момент и становится видно, где заканчивается суета и начинается управление."
    return ""


def build_focus_line(theme: str, angle: str, variant: int) -> str:
    normalized_theme = theme.lower()
    if is_ai_core_topic(normalized_theme):
        variants = [
            "Вопрос не в самом ИИ, а в том, усиливает ли он уже собранный процесс или просто ускоряет разнобой.",
            "Сначала нужен порядок в ролях, процессе и контроле. И только потом ИИ начинает давать скорость.",
            "Если под ИИ нет нормальной конструкции, он ускоряет бардак, а не результат.",
        ]
        return variants[variant % len(variants)]
    if any(token in normalized_theme for token in ("дороже", "налог", "цен", "эконом", "расход", "издерж")):
        variants = [
            "Важнее не то, как урезать всё подряд, а где у бизнеса реальные системные потери.",
            "Сейчас важнее не масштаб сокращений, а точность: где расходы действительно лишние, а где бизнес теряет деньги из-за плохой организации.",
            "Ключевой фокус такой: не экономить хаотично, а отличить внешнее давление рынка от внутренних управленческих потерь.",
        ]
        return variants[variant % len(variants)]
    if any(token in normalized_theme for token in ("стад", "кризис")):
        variants = [
            "На каждой стадии у бизнеса своя типичная ошибка управления.",
            "Один и тот же симптом на разных стадиях означает совершенно разную управленческую проблему.",
            "Дело не в самом кризисе, а в том, какой управленческий перекос для этой стадии является типичным.",
        ]
        return variants[variant % len(variants)]
    generic = [
        "Ключевой момент не в отдельном сбое, а в том, какая управленческая логика стоит за ним.",
        "Если сжать это до одной мысли, то она такая: проблема обычно глубже, чем кажется сначала.",
        "Смысл не в симптоме, а в том, что именно в системе даёт ему повторяться снова и снова.",
    ]
    return generic[variant % len(generic)]


def apply_voice_authenticity_guard(text: str, case_context: dict | None) -> str:
    cleaned = text
    replacements = {
        "архитектура управления": "управленческая логика",
        "архитектура ролей": "роли",
        "архитектурная причина": "корневая причина",
        "архитектура компании": "сама компания",
        "контур управления": "управление",
        "эскалирует": "поднимает",
        "эскалации": "передачи вопроса дальше",
        "владелец процесса": "ответственный за процесс",
        "если смотреть глубже": "если копнуть глубже",
        "главный разрыв": "главный сбой",
        "и меня это нисколько не удивило": "меня это совсем не удивило",
    }
    for old, new in replacements.items():
        cleaned = re.sub(re.escape(old), new, cleaned, flags=re.IGNORECASE)

    if not case_context:
        cleaned = re.sub(
            r"В одной компании, с которой я работал,?",
            "В похожих ситуациях я часто вижу, что",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"Через\s+(?:два|2)\s+спринта",
            "Через некоторое время",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\b\d+\s*%", "заметно", cleaned)
        cleaned = re.sub(r"\b\d+\s*час(?:а|ов)?\b", "несколько часов", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bQA[- ]владелец\b", "ответственный за качество", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bЦКП\b", "понятный результат", cleaned)

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def apply_editorial_feedback_guards(text: str, editorial_feedback: list[dict]) -> str:
    cleaned = text
    active_notes = [note.get("summary", "").lower() for note in editorial_feedback if note.get("status") == "active"]
    if any("шаблонно" in note or "одинаков" in note for note in active_notes):
        cleaned = cleaned.replace("Главный вопрос здесь", "Ключевой вопрос здесь")
        cleaned = cleaned.replace("И тогда эффект уже другой.", "Тогда эффект меняется.")
    if any("живым" in note or "копирк" in note for note in active_notes):
        cleaned = cleaned.replace("Если будет полезно, эту же тему можно дальше развернуть уже на реальной бизнес-сцене.", "Если будет полезно, потом разберу это уже на конкретной ситуации.")
    if any("начал" in note or "заголов" in note or "вчитыва" in note or "понят" in note for note in active_notes):
        cleaned = cleaned.replace("Вопрос здесь простой: где именно в этой теме заканчивается управление по привычке и начинается системная работа?", "")
        cleaned = cleaned.replace("Вопрос здесь простой:", "")
        cleaned = cleaned.replace("Ключевой вопрос здесь простой:", "Ключевой момент здесь:")
    return cleaned


def adjust_cta_need(theme: str, current_cta_need: str, content_pillar: str, campaign_mode: str) -> str:
    strategy = resolve_cta_strategy(theme, content_pillar, campaign_mode)
    if current_cta_need == "none":
        return "none"
    preferred = strategy.get("preferred_cta_need") or current_cta_need
    if current_cta_need == "soft" and preferred == "optional":
        return current_cta_need
    return preferred


def select_cta(
    theme: str,
    cta_need: str,
    seed: int,
    content_pillar: str,
    campaign_mode: str,
    preferred_cta_mode: str | None = None,
) -> str:
    strategy = resolve_cta_strategy(theme, content_pillar, campaign_mode)
    allowed = set(strategy.get("allowed_ctas") or [])
    silent_bucket = int(hashlib.md5(f"{theme}|{content_pillar}|{seed}".encode("utf-8")).hexdigest()[:2], 16) % 10
    personal_bias = any(
        token in theme.lower()
        for token in ("оргструкт", "роль", "регламент", "процесс", "эффектив", "операцион", "структур")
    )
    if preferred_cta_mode == "none":
        return ""
    if preferred_cta_mode == "comments" and "comment" in allowed:
        options = CTA_LIBRARY["comment"] if cta_need == "optional" else CTA_LIBRARY["discussion_soft"]
        return options[seed % len(options)]
    if preferred_cta_mode == "diagnostic" and "diagnostic" in allowed:
        options = CTA_LIBRARY["soft"][:2]
        return options[seed % len(options)]
    if preferred_cta_mode == "personal" and "personal" in allowed and personal_bias:
        options = CTA_LIBRARY["personal_targeted"]
        return options[seed % len(options)]
    if cta_need == "soft":
        diagnostic_bias = any(token in theme.lower() for token in ("стад", "кризис", "диагност", "adizes", "перекос", "расход", "издерж", "потер"))
        if (diagnostic_bias and silent_bucket == 0) or (not diagnostic_bias and silent_bucket == 0):
            return ""
        if "diagnostic" in allowed and diagnostic_bias and seed % 3 != 2:
            options = CTA_LIBRARY["soft"][:2]
            return options[seed % len(options)]
        if personal_bias and "personal" in allowed and silent_bucket in {5, 8}:
            options = CTA_LIBRARY["personal_targeted"]
            return options[seed % len(options)]
        if "comment" in allowed and seed % 3 != 1:
            options = CTA_LIBRARY["discussion_soft"]
            return options[seed % len(options)]
        if "diagnostic" in allowed and seed % 4 == 1:
            options = CTA_LIBRARY["soft"][:2]
            return options[seed % len(options)]
        if "personal" in allowed and seed % 6 == 5:
            return CTA_LIBRARY["soft"][2]
        if "comment" in allowed:
            options = CTA_LIBRARY["discussion_soft"]
            return options[seed % len(options)]
    if cta_need == "hard" and "flagship" in set(strategy.get("allowed_ctas") or []):
        options = CTA_LIBRARY["hard"]
        return options[seed % len(options)]
    if cta_need == "optional" and "comment" in allowed:
        if silent_bucket in {0, 1}:
            return ""
        if personal_bias and "personal" in allowed and silent_bucket == 8:
            options = CTA_LIBRARY["personal_targeted"]
            return options[seed % len(options)]
        options = CTA_LIBRARY["comment"]
        return options[seed % len(options)]

    options = CTA_LIBRARY.get(cta_need, [""])
    if not options:
        return ""
    return options[seed % len(options)]


def quota_adjusted_cta_need(
    theme: str,
    cta_need: str,
    content_pillar: str,
    campaign_mode: str,
    cta_balance: dict,
    preferred_cta_mode: str | None = None,
) -> str:
    if cta_need == "none":
        return "none"
    if preferred_cta_mode == "none":
        return "none"

    needs = cta_balance.get("needs") or {}
    normalized = theme.lower()
    diagnostic_bias = any(token in normalized for token in ("стад", "кризис", "диагност", "adizes", "перекос", "расход", "издерж", "потер"))
    personal_bias = any(token in normalized for token in ("оргструкт", "роль", "регламент", "процесс", "эффектив", "операцион", "структур"))

    if preferred_cta_mode == "diagnostic":
        return "soft"
    if preferred_cta_mode in {"comments", "personal"}:
        return "optional"

    if needs.get("none", 0) >= 0.08 and content_pillar != "money" and not diagnostic_bias:
        return "none"

    if cta_need == "soft":
        if needs.get("comments", 0) >= 0.08 and not diagnostic_bias:
            return "optional"
        if needs.get("diagnostic", 0) <= -0.08 and not diagnostic_bias:
            return "optional"
        if needs.get("personal", 0) <= -0.04 and personal_bias:
            return "optional"

    if cta_need == "optional" and needs.get("comments", 0) <= -0.08:
        if needs.get("none", 0) > 0.04:
            return "none"

    return cta_need


def select_hashtag(theme: str) -> str:
    return HASHTAG_BY_THEME.get(theme, "#управление")


def select_theme_emojis(theme: str) -> list[str]:
    normalized = theme.lower()
    if any(token in normalized for token in ("дороже", "налог", "цен", "эконом", "расход", "издерж")):
        return EMOJI_BY_THEME["рост расходов и оптимизация затрат"]
    if any(token in normalized for token in ("стад", "кризис", "диагност", "adizes")):
        return EMOJI_BY_THEME["ввод воронки через диагностику стадий бизнеса"]
    if any(token in normalized for token in ("симптом", "причин")):
        return EMOJI_BY_THEME["работа с причинами, а не симптомами"]
    if any(token in normalized for token in ("оргструкт", "роль", "ответствен")):
        return EMOJI_BY_THEME["оргструктура и роли"]
    if any(token in normalized for token in ("издерж", "потер", "операцион")):
        return EMOJI_BY_THEME["скрытые потери в операционке"]
    return ["📍", "⚙️", "🎯"]


def finalize_text(parts: list[str], hashtag: str) -> str:
    body = "\n\n".join(part for part in parts if part.strip())
    if hashtag and hashtag not in body:
        body = f"{body}\n\n{hashtag}"
    return body.strip()


def build_stage_diagnostic_draft(context: DraftContext, variant: int) -> str:
    openings = [
        "У вас текучка, слабые руководители или постоянная путаница между отделами?",
        "Текучка в команде редко означает то, что кажется.",
        "Один и тот же симптом в бизнесе на разных этапах роста может означать разные причины.",
    ]
    prefaces = [
        "На поверхности кажется, что проблема просто в сотрудниках.\n\nИногда это так и есть. Но чаще это признак хреново выстроенной системы найма и адаптации.",
        "Снаружи всё выглядит просто: люди уходят, руководители не тянут, между отделами бардак. Но если копнуть глубже, это часто не проблема людей, а проблема того, как выстроен сам найм и ввод человека в работу.",
        "Ошибка здесь обычно в одном: собственник видит симптом и начинает чинить его в лоб. Хотя сам симптом может говорить совсем о другой поломке внутри бизнеса.",
    ]
    examples = [
        "Например:\n\nТекучка в команде из 10 человек обычно говорит о хаотичном найме.\nНет чёткого профиля должности, ожидания не проговорены, решение принимается «по ощущениям».\n\nНо та же текучка в компании 40+ человек — уже другая история.\nЗдесь чаще ломается не найм, а сама логика управления.",
        "Например:\n\nКогда команда маленькая, сбой часто в том, что найм и ввод человека в работу идут хаотично.\n\nКогда бизнес вырастает, тот же симптом уже чаще говорит о другом: руководители перегружены, роли размыты, а ожидания по результату нигде не зафиксированы.",
        "Например:\n\nПутаница между отделами на раннем этапе может быть следствием нехватки людей.\nНо на более зрелом этапе тот же симптом уже обычно говорит о слабой оргструктуре, размытых зонах ответственности и сбоях на стыках функций.",
    ]
    breakdowns = [
        "Что обычно происходит:\n– руководители практически не вовлечены в адаптацию нового сотрудника, потому что своих проблем по горло;\n– новый сотрудник плохо понимает, что он должен делать и с кем взаимодействовать, потому что роли и зоны ответственности не прописаны;\n– чего от него вообще ждут, тоже часто непонятно, потому что чёткие ожидания от должности не прописаны и руководитель каждый раз требует то одно, то другое;\n– адаптация дополнительно усложняется тем, что взаимодействие между подразделениями тоже нормально не выстроено.",
        "И в итоге сотрудник приходит в стрессовую систему, где сначала тратит месяцы, чтобы просто понять, что вообще делать, и только потом начинает давать какой-то результат. Если не уходит раньше.",
        "Собственник в этот момент часто делает вывод: «нам просто не везёт с людьми».\nХотя на деле ломается не человек, а сама конструкция управления.",
    ]
    diagnostics = [
        "Чтобы не лечить всё подряд, полезно проверить 3 вещи:\n🔧 Где проявляется проблема: с конкретным человеком, в одном отделе или уже в масштабе всей организации.\n🔧 Кто отвечает за этот процесс и хватает ли ему опыта, компетенций и вовлечённости.\n🔧 Проблема в самих кандидатах или в том, что ожидания и условия по должности вообще не прописаны.",
        "Практически здесь полезно проверить 3 вещи:\n🔧 Где именно ломается найм или адаптация.\n🔧 Кто реально отвечает за результат, а не просто числится ответственным.\n🔧 Понимает ли новый сотрудник, что он должен делать, с кем взаимодействовать и по каким правилам работать.",
        "Если разбирать это системно, я обычно смотрю на 3 вещи:\n🔧 кто держит результат;\n🔧 где размыта ответственность;\n🔧 на каком стыке теряется управляемость.",
    ]
    effects = [
        "После такой диагностики становится понятно, что именно чинить: найм, адаптацию, руководителей, профиль должности, роли или саму компанию как систему.\n\nИ это уже системная работа, а не борьба с симптомами.",
        "Тогда собственник перестаёт делать вывод «нам просто не везёт с людьми» и начинает видеть, где реально ломается система найма и адаптации.",
        "Тогда вместо общего разговора про стадии появляется прикладной вывод: что именно сейчас тормозит бизнес и какой управленческий узел нужно разбирать первым.",
    ]

    opening = openings[variant % len(openings)]
    preface = prefaces[variant % len(prefaces)]
    example = examples[variant % len(examples)]
    breakdown = breakdowns[variant % len(breakdowns)]
    diagnostic = diagnostics[variant % len(diagnostics)]
    effect = effects[variant % len(effects)]
    cta_options = [
        "Если узнаёшь в этом свой бизнес, можно быстро проверить, где у тебя ломается найм, адаптация или сама логика управления — для этого есть короткая диагностика в @adizesbizbot.",
        "Если хочешь, можешь пройти короткую диагностику в @adizesbizbot и посмотреть, где у тебя сейчас главный перекос: в найме, адаптации, ролях или управлении.",
        "",
    ]
    cta = cta_options[variant % len(cta_options)]
    hashtag = select_hashtag(context.theme)
    parts = [opening, preface, example, breakdown, diagnostic, effect]
    if cta:
        parts.append(cta)
    return finalize_text(parts, hashtag)


def build_conversational_draft(context: DraftContext, variant: int) -> str:
    theme_text = normalize(context.theme)
    lowered_theme = theme_text.lower()
    if len(theme_text) >= 120 and (
        re.search(r"\b(я|мне|меня|у меня|мой|моя|мои)\b", lowered_theme)
        or "мне сложно" in lowered_theme
        or "я понял" in lowered_theme
    ):
        sentences = [part.strip(" .") for part in re.split(r"[?.!]\s*", theme_text) if part.strip()]
        opening = sentences[0] if sentences else context.theme
        detail = ""
        resolution = ""

        if "какое решение" in lowered_theme:
            before, _, after = theme_text.partition("Какое решение")
            before_sentences = [part.strip(" .") for part in re.split(r"[?.!]\s*", before) if part.strip()]
            if before_sentences:
                opening = before_sentences[0]
                if len(before_sentences) > 1:
                    detail = before_sentences[1]
            resolution = after.strip(" :.-?") or resolution

        if not resolution and len(sentences) > 1:
            resolution = sentences[-1]
        if not detail and len(sentences) > 1:
            detail = sentences[1]

        if "заслужить отдых" in lowered_theme:
            bridge = (
                "Когда отдых сначала нужно заслужить, работа почти неизбежно начинает жить через внутреннее "
                "«надо», а не через ясный выбор и нормальный ритм."
            )
        elif "мне сложно работать через" in lowered_theme or "через «надо»" in lowered_theme or "через \"надо\"" in lowered_theme:
            bridge = (
                "В такие моменты проблема обычно не в дисциплине. Проблема в том, что сама внутренняя конструкция "
                "работы собрана через давление, а не через понятный приоритет."
            )
        else:
            bridge = (
                "Иногда такая тема кажется просто личной привычкой. Но если смотреть глубже, она довольно быстро "
                "начинает влиять и на качество решений, и на общий ритм жизни."
            )

        if not detail:
            detail = (
                "И в какой-то момент становится заметно, что дело уже не в продуктивности, а в том, из какого "
                "состояния вообще собирается день."
            )

        if resolution:
            action = f"Для себя здесь вижу более рабочий ход: {resolution[0].lower() + resolution[1:]}"
        else:
            action = (
                "Для себя здесь рабочее решение одно: не пытаться тащить весь день как обязательство, а заранее "
                "выделять только несколько действий, которые действительно держат результат."
            )

        ending = (
            "Тогда работа перестаёт быть бесконечным долгом. Появляется больше воздуха, а вместе с ним и более "
            "спокойное управление собой, а не только постоянное внутреннее подталкивание."
        )

        cta = select_cta(
            context.theme,
            "optional",
            variant,
            context.content_pillar,
            context.positioning_flags.get("campaign_mode", "base"),
            context.preferred_cta_mode,
        )
        parts = [opening, detail, bridge, action, ending]
        if cta and context.preferred_cta_mode != "none":
            parts.append(cta)
        return finalize_text(parts, "#мысли")

    library = context.conversational_style_library or {}
    profiles = library.get("profiles", {})
    normalized_theme = context.theme.lower()
    normalized_angle = context.angle.lower()
    combined = f"{normalized_theme} {normalized_angle}"

    profile_key = "pause_reset"
    best_score = -1
    for key, profile in profiles.items():
        signals = profile.get("signals", [])
        score = sum(1 for signal in signals if signal in combined)
        if score > best_score:
            best_score = score
            profile_key = key

    profile = profiles.get(profile_key, {})
    hooks = profile.get("hooks") or [
        "Есть темы, в которых полезнее не торопиться с выводом, а сначала честно посмотреть, что с тобой и с системой происходит",
    ]
    scenes = profile.get("scenes") or [
        "Иногда один короткий эпизод или пауза дают больше ясности, чем ещё один день в привычной гонке",
    ]
    bridges = profile.get("bridges") or [
        "И именно в этот момент становится видно, что жизнь и бизнес одинаково быстро уходят в инерцию, если вовремя не смотреть на них сверху",
    ]
    lists = profile.get("lists") or [""]
    endings = profile.get("endings") or [
        "Поэтому иногда самый взрослый шаг – не ускоряться, а сначала вернуть себе ясность",
    ]
    cta_options = profile.get("cta") or [""]

    opening = hooks[variant % len(hooks)]
    scene = scenes[variant % len(scenes)]
    bridge = bridges[variant % len(bridges)]
    optional_list = lists[variant % len(lists)] if lists else ""
    ending = endings[variant % len(endings)]
    cta = cta_options[variant % len(cta_options)] if cta_options else ""

    if profile_key == "pause_reset" and variant % 3 == 0:
        scene = (
            "На праздниках, в поездке или просто в редком тихом окне особенно хорошо видно одну вещь: "
            + scene[0].lower()
            + scene[1:]
        )

    if profile_key == "post_event_insight" and variant % 2 == 1:
        bridge = f"{bridge}\n\nИ вот здесь уже начинается не просто эмоция от момента, а нормальная пересборка следующего шага"

    if profile_key == "overload_life" and variant % 2 == 0:
        ending = f"{ending}\n\nИ для меня это как раз тот случай, когда порядок нужен не ради контроля, а ради свободы"

    parts = [opening]

    if variant % 2 == 0:
        parts.append(scene)
        parts.append(bridge)
    else:
        parts.append(f"{scene}\n\n{bridge}")

    if optional_list and variant % 3 != 1:
        parts.append(optional_list)

    parts.append(ending)

    if cta:
        parts.append(cta)

    hashtag = "#мысли" if profile_key in {"pause_reset", "overload_life", "post_event_insight"} else select_hashtag(context.theme)
    return finalize_text(parts, hashtag)


def build_case_draft(context: DraftContext, variant: int) -> str:
    case = context.case_context or {}
    case_query = (case.get("case_query") or "").strip()
    confirmed = case.get("what_is_confirmed") or []
    changes = case.get("system_changes") or []
    outcomes = case.get("measurable_outcomes") or []
    fit_reason = (case.get("fit_reason") or context.why_now or "").strip()

    openings = [
        f"Иногда сильный рост начинается не с маркетинга, а с честного признания системной проблемы. Это хорошо видно на кейсе {case_query}.",
        f"Кейс {case_query} хорошо показывает одну важную вещь: маркетинг не спасает, если внутри компании ломается сама система.",
        f"История {case_query} интересна не брендом, а тем, что компания выбралась не рекламой, а пересборкой процессов и контроля.",
    ]
    explanations = [
        "В таких историях важен не сам кризис, а то, что руководство перестаёт спорить с реальностью и начинает собирать систему заново.",
        "Это как раз тот случай, когда компания перестаёт лечить фасад и идёт в причину: продукт, стандарты, исполнение и контроль.",
        "Самое ценное здесь не в красивой коммуникации, а в том, что за ней стояла реальная управленческая пересборка.",
    ]

    opening = openings[variant % len(openings)]
    explanation = explanations[variant % len(explanations)]

    fact_line = ""
    if confirmed:
        fact_line = "Что подтверждается по кейсу:\n" + "\n".join(f"– {item}" for item in confirmed[:3])

    change_line = ""
    if changes:
        change_line = "Что именно пересобрали:\n" + "\n".join(f"– {item}" for item in changes[:4])

    outcome_line = ""
    if outcomes:
        outcome_line = "Какой это дало эффект:\n" + "\n".join(f"– {item}" for item in outcomes[:4])

    bridge = fit_reason or "Именно поэтому этот кейс хорошо ложится в ваш контекст: рост здесь шёл через порядок, стандарты, контроль и системные изменения."
    angle_line = f"Если переводить это в тему канала, то главный вывод здесь такой: {context.angle}" if context.angle else ""

    effective_cta_need = quota_adjusted_cta_need(
        context.theme,
        adjust_cta_need(
            context.theme,
            context.cta_need,
            context.content_pillar,
            context.positioning_flags.get("campaign_mode", "base"),
        ),
        context.content_pillar,
        context.positioning_flags.get("campaign_mode", "base"),
        context.cta_balance,
        context.preferred_cta_mode,
    )
    cta = select_cta(
        context.theme,
        effective_cta_need,
        variant,
        context.content_pillar,
        context.positioning_flags.get("campaign_mode", "base"),
        context.preferred_cta_mode,
    )
    hashtag = "#управление" if context.content_pillar != "conversational" else "#мысли"
    parts = [opening, explanation]
    if fact_line:
        parts.append(fact_line)
    if change_line:
        parts.append(change_line)
    if outcome_line:
        parts.append(outcome_line)
    if angle_line:
        parts.append(angle_line)
    parts.append(bridge)
    if cta and effective_cta_need != "none":
        parts.append(cta)
    return finalize_text(parts, hashtag)


def _remove_sentences_with_triggers(text: str, triggers: list[str]) -> str:
    """Remove entire sentences that contain any of the trigger substrings.

    Splitting on sentence-ending punctuation keeps paragraphs intact:
    we split inside each paragraph, then rejoin.
    """
    if not triggers:
        return text
    paragraphs = text.split("\n\n")
    result_paragraphs: list[str] = []
    for paragraph in paragraphs:
        # Split on sentence boundaries (. ! ?) followed by a space or end of paragraph.
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        kept: list[str] = []
        for sentence in sentences:
            lower = sentence.lower()
            if any(trigger in lower for trigger in triggers):
                continue  # drop entire sentence
            kept.append(sentence)
        result_paragraphs.append(" ".join(kept))
    # Drop empty paragraphs produced by removing all sentences from a paragraph.
    result_paragraphs = [p for p in result_paragraphs if p.strip()]
    return "\n\n".join(result_paragraphs)


def apply_stop_word_guard(text: str, stop_words: dict) -> str:
    cleaned = text
    # Only replace with genuinely better alternatives.
    replacements = {
        "архитектура управления": "управленческая логика",
        "контур управления": "управление",
        "и меня это нисколько не удивило": "Меня это совсем не удивило",
    }
    for old, new in replacements.items():
        cleaned = re.sub(re.escape(old), new, cleaned, flags=re.IGNORECASE)

    # Remove entire sentences that contain any forbidden fragment.
    # This replaces the old phrase-only regex that left broken fragments.
    all_triggers: list[str] = [
        p.lower() for p in stop_words.get("template_phrases_to_avoid", [])
    ] + [
        t.lower() for t in stop_words.get("fragment_triggers", [])
    ]
    if all_triggers:
        cleaned = _remove_sentences_with_triggers(cleaned, all_triggers)

    # Remove exact banned_phrases (straight replacement, no sentence removal needed).
    for phrase in stop_words.get("banned_phrases", []):
        cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"  +", " ", cleaned)
    return cleaned.strip()


def has_generation_artifacts(text: str) -> bool:
    """Detect broken generation artifacts that indicate LLM output corruption."""
    patterns = [
        r"—\s*,",                  # "не , а" — пустое место после тире
        r"\bфото\b(?!\s+\w{4,})",  # "системную фото" без продолжения
        r"\s{3,}",                  # тройные пробелы
        r"[а-яa-z]—[а-яa-z]",     # слово-тире-слово без пробелов
    ]
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def assemble_parts(parts_map: dict[str, str], variant: int) -> list[str]:
    blueprint = STRUCTURE_BLUEPRINTS[variant % len(STRUCTURE_BLUEPRINTS)]
    return [parts_map[key] for key in blueprint if parts_map.get(key)]


def strip_emojis_if_needed(text: str, user_preferences: dict) -> str:
    if user_preferences.get("emoji_policy") != "none":
        return text
    # Remove most pictographic / symbol emoji-like characters but keep punctuation and hashtags.
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)
    text = re.sub(r"^[\s]*[^\wА-Яа-я#\"«(]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def count_emojis(text: str) -> int:
    return len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text))


def resolve_emoji_bounds(user_preferences: dict, business_goal: str) -> tuple[int, int]:
    if business_goal == "money":
        return (
            int(user_preferences.get("money_min_emojis_per_post", user_preferences.get("min_emojis_per_post", 2))),
            int(user_preferences.get("money_max_emojis_per_post", user_preferences.get("max_emojis_per_post", 6))),
        )
    if business_goal == "conversational":
        return (
            int(user_preferences.get("conversational_min_emojis_per_post", 2)),
            int(user_preferences.get("conversational_max_emojis_per_post", 5)),
        )
    if business_goal == "image":
        return (
            int(user_preferences.get("image_min_emojis_per_post", 1)),
            int(user_preferences.get("image_max_emojis_per_post", 3)),
        )
    return (
        int(user_preferences.get("expert_min_emojis_per_post", user_preferences.get("min_emojis_per_post", 2))),
        int(user_preferences.get("expert_max_emojis_per_post", user_preferences.get("max_emojis_per_post", 4))),
    )


def add_emojis_if_needed(text: str, theme: str, user_preferences: dict, business_goal: str) -> str:
    if user_preferences.get("emoji_policy") == "none":
        return text

    emojis = select_theme_emojis(theme)
    min_emojis, max_emojis = resolve_emoji_bounds(user_preferences, business_goal)
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return text

    if count_emojis(text) >= max_emojis:
        return text

    first = paragraphs[0]
    if not re.match(r"^[\U0001F300-\U0001FAFF\u2600-\u27BF]", first) and count_emojis("\n\n".join(paragraphs)) < max_emojis:
        paragraphs[0] = f"{emojis[0]} {first}"

    for idx, paragraph in enumerate(paragraphs[1:], start=1):
        lower = paragraph.lower()
        if lower.startswith("главный вопрос") or lower.startswith("поэтому") or lower.startswith("часто"):
            if not re.match(r"^[\U0001F300-\U0001FAFF\u2600-\u27BF]", paragraph):
                if count_emojis("\n\n".join(paragraphs)) < max_emojis:
                    paragraphs[idx] = f"{emojis[1]} {paragraph}"
                break

    for idx, paragraph in enumerate(paragraphs[1:], start=1):
        lower = paragraph.lower()
        if "диагностик" in lower or "@adizesbizbot" in lower or "@pda33" in lower or lower.startswith("если хочешь"):
            if not re.match(r"^[\U0001F300-\U0001FAFF\u2600-\u27BF]", paragraph):
                if count_emojis("\n\n".join(paragraphs)) < max_emojis:
                    paragraphs[idx] = f"{emojis[2]} {paragraph}"
                break

    if count_emojis("\n\n".join(paragraphs)) < min_emojis:
        for idx, paragraph in enumerate(paragraphs[1:], start=1):
            if paragraph.startswith("#"):
                continue
            if re.match(r"^[\U0001F300-\U0001FAFF\u2600-\u27BF]", paragraph):
                continue
            paragraphs[idx] = f"{emojis[min(idx, len(emojis) - 1)]} {paragraph}"
            if count_emojis("\n\n".join(paragraphs)) >= min_emojis:
                break

    return "\n\n".join(paragraphs)


def generate_drafts(
    theme: str | None = None,
    angle: str | None = None,
    business_goal: str = "expert",
    count: int = 2,
    preferred_cta_mode: str | None = None,
    case_context: dict | None = None,
    topic_brief: dict | None = None,
) -> dict:
    context = build_context(
        theme=theme,
        angle=angle,
        business_goal=business_goal,
        preferred_cta_mode=preferred_cta_mode,
        case_context=case_context,
        topic_brief=topic_brief,
    )
    drafts = []
    profile = infer_profile(context.theme)
    reference_patterns = extract_reference_patterns(context.reference_posts)

    # Generate the controlling thought before drafts so it acts as a hard constraint.
    core_idea = generate_core_idea(context.theme, context.angle)
    if core_idea:
        LOGGER.info("core_idea generated: %s", core_idea)
    else:
        LOGGER.warning("core_idea generation skipped or failed — drafts will use soft prompt guidance only")

    post_type = (topic_brief or {}).get("post_type") or ""
    LOGGER.info("generate_drafts: post_type=%s theme=%r", post_type or "(none)", context.theme)

    _MAX_ARTIFACT_RETRIES = 2
    _writer_payload = {
        "selected_topic": context.theme,
        "angle": context.angle,
        "goal": business_goal,
        "campaign_mode": context.positioning_flags.get("campaign_mode"),
        "flagship_offer": context.positioning_flags.get("flagship_offer"),
        "content_role": context.content_role,
        "content_pillar": context.content_pillar,
        "cta_policy": context.cta_need,
        "style_references": [
            {
                "date": row.get("date"),
                "primary_theme": row.get("primary_theme"),
                "title_hook": row.get("title_hook"),
                "body_text": row.get("body_text"),
            }
            for row in context.style_references
        ],
        "knowledge_core_notes": context.terminology_registry,
        "avoid_phrases": context.stop_words,
        "voice_profile": context.style_profile,
        "post_type": post_type,
        "core_idea": core_idea or "",
        "editorial_feedback": context.editorial_feedback,
        "case_context": context.case_context,
        "topic_brief": topic_brief,
    }

    llm_drafts = None
    for _attempt in range(_MAX_ARTIFACT_RETRIES + 1):
        llm_drafts = maybe_generate_writer_drafts(_writer_payload, count=min(count, 2))
        if not llm_drafts:
            break
        _attempt_drafts: list[dict] = []
        _artifact_hits = 0
        for idx, item in enumerate(llm_drafts, start=1):
            llm_text = item["text"]
            llm_text = add_emojis_if_needed(llm_text, context.theme, context.user_preferences, context.business_goal)
            llm_text = apply_stop_word_guard(llm_text, context.stop_words)
            llm_text = apply_voice_authenticity_guard(llm_text, context.case_context)
            llm_text = apply_editorial_feedback_guards(llm_text, context.editorial_feedback)
            llm_text = strip_emojis_if_needed(llm_text, context.user_preferences)
            if has_generation_artifacts(llm_text):
                LOGGER.warning(
                    "[ARTIFACT] draft %d/%d attempt %d/%d — skipping corrupted output",
                    idx, len(llm_drafts), _attempt + 1, _MAX_ARTIFACT_RETRIES + 1,
                )
                _artifact_hits += 1
                continue
            _attempt_drafts.append(
                {
                    "variant": idx,
                    "theme": context.theme,
                    "angle": context.angle,
                    "content_role": context.content_role,
                    "cta_need": quota_adjusted_cta_need(
                        context.theme,
                        adjust_cta_need(
                            context.theme,
                            context.cta_need,
                            context.content_pillar,
                            context.positioning_flags.get("campaign_mode", "base"),
                        ),
                        context.content_pillar,
                        context.positioning_flags.get("campaign_mode", "base"),
                        context.cta_balance,
                        context.preferred_cta_mode,
                    ),
                    "text": llm_text,
                }
            )
        if _attempt_drafts:
            drafts.extend(_attempt_drafts)
            break
        if _attempt < _MAX_ARTIFACT_RETRIES:
            LOGGER.warning(
                "[ARTIFACT] all %d LLM draft(s) had artifacts — retrying (%d/%d)",
                len(llm_drafts), _attempt + 1, _MAX_ARTIFACT_RETRIES,
            )

    # Rule-based drafts are fallback only — skip when LLM produced results
    if llm_drafts:
        return {
            "selected_theme": context.theme,
            "selected_angle": context.angle,
            "positioning_flags": context.positioning_flags,
            "style_profile": context.style_profile,
            "user_preferences": context.user_preferences,
            "why_now": context.why_now,
            "preferred_cta_mode": context.preferred_cta_mode,
            "case_context": context.case_context,
            "user_theme_verdict": context.user_theme_verdict,
            "style_references": [
                {
                    "post_id": row.get("post_id"),
                    "date": row.get("date"),
                    "title_hook": row.get("title_hook"),
                    "primary_theme": row.get("primary_theme"),
                }
                for row in context.style_references
            ],
            "drafts": drafts,
        }

    for variant in range(count):
        if context.post_format == "reflective":
            draft = build_conversational_draft(context, variant)
            draft = add_emojis_if_needed(draft, context.theme, context.user_preferences, context.business_goal)
            draft = apply_stop_word_guard(draft, context.stop_words)
            draft = apply_voice_authenticity_guard(draft, context.case_context)
            draft = apply_editorial_feedback_guards(draft, context.editorial_feedback)
            draft = strip_emojis_if_needed(draft, context.user_preferences)
            drafts.append(
                {
                    "variant": variant + 1,
                    "theme": context.theme,
                    "angle": context.angle,
                    "content_role": context.content_role,
                    "cta_need": "none",
                    "text": draft,
                }
            )
            continue

        if context.post_format == "case":
            draft = build_case_draft(context, variant)
            draft = add_emojis_if_needed(draft, context.theme, context.user_preferences, context.business_goal)
            draft = apply_stop_word_guard(draft, context.stop_words)
            draft = apply_voice_authenticity_guard(draft, context.case_context)
            draft = apply_editorial_feedback_guards(draft, context.editorial_feedback)
            draft = strip_emojis_if_needed(draft, context.user_preferences)
            drafts.append(
                {
                    "variant": variant + 1,
                    "theme": context.theme,
                    "angle": context.angle,
                    "content_role": context.content_role,
                    "cta_need": quota_adjusted_cta_need(
                        context.theme,
                        adjust_cta_need(
                            context.theme,
                            context.cta_need,
                            context.content_pillar,
                            context.positioning_flags.get("campaign_mode", "base"),
                        ),
                        context.content_pillar,
                        context.positioning_flags.get("campaign_mode", "base"),
                        context.cta_balance,
                        context.preferred_cta_mode,
                    ),
                    "text": draft,
                }
            )
            continue

        if context.post_format == "diagnostic" and "стад" in context.theme.lower():
            draft = build_stage_diagnostic_draft(context, variant)
            draft = add_emojis_if_needed(draft, context.theme, context.user_preferences, context.business_goal)
            draft = apply_stop_word_guard(draft, context.stop_words)
            draft = apply_voice_authenticity_guard(draft, context.case_context)
            draft = apply_editorial_feedback_guards(draft, context.editorial_feedback)
            draft = strip_emojis_if_needed(draft, context.user_preferences)
            drafts.append(
                {
                    "variant": variant + 1,
                    "theme": context.theme,
                    "angle": context.angle,
                    "content_role": context.content_role,
                    "cta_need": quota_adjusted_cta_need(
                        context.theme,
                        adjust_cta_need(
                            context.theme,
                            context.cta_need,
                            context.content_pillar,
                            context.positioning_flags.get("campaign_mode", "base"),
                        ),
                        context.content_pillar,
                        context.positioning_flags.get("campaign_mode", "base"),
                        context.cta_balance,
                        context.preferred_cta_mode,
                    ),
                    "text": draft,
                }
            )
            continue

        hook = tune_hook_with_references(build_hook(profile, variant), reference_patterns, variant)
        scene = tune_scene_with_references(build_scene(profile, variant), reference_patterns, variant)
        transition = build_transition(variant)
        reason = build_reason(profile, context.angle, variant)
        focus_line = build_focus_line(context.theme, context.angle, variant)
        solution = build_solution(profile, context.theme, variant)
        effect = build_effect(profile, variant)
        reference_tail = build_reference_tail(reference_patterns, variant)
        effective_cta_need = quota_adjusted_cta_need(
            context.theme,
            adjust_cta_need(
                context.theme,
                context.cta_need,
                context.content_pillar,
                context.positioning_flags.get("campaign_mode", "base"),
            ),
            context.content_pillar,
            context.positioning_flags.get("campaign_mode", "base"),
            context.cta_balance,
            context.preferred_cta_mode,
        )
        cta = select_cta(
            context.theme,
            effective_cta_need,
            variant,
            context.content_pillar,
            context.positioning_flags.get("campaign_mode", "base"),
            context.preferred_cta_mode,
        )
        hashtag = select_hashtag(context.theme)

        parts_map = {
            "hook": hook,
            "scene": scene,
            "transition": transition if variant % 2 == 0 else "",
            "reason": reason,
            "focus": focus_line,
            "solution": solution,
            "effect": effect,
            "reference_tail": reference_tail if variant % 3 == 0 else "",
            "cta": cta if effective_cta_need != "none" else "",
        }
        parts_map = adapt_parts_to_format(parts_map, context, variant)
        draft = finalize_text(assemble_parts(parts_map, variant), hashtag)
        draft = add_emojis_if_needed(draft, context.theme, context.user_preferences, context.business_goal)
        draft = apply_stop_word_guard(draft, context.stop_words)
        draft = apply_voice_authenticity_guard(draft, context.case_context)
        draft = apply_editorial_feedback_guards(draft, context.editorial_feedback)
        draft = strip_emojis_if_needed(draft, context.user_preferences)
        drafts.append(
            {
                "variant": variant + 1,
                "theme": context.theme,
                "angle": context.angle,
                "content_role": context.content_role,
                "cta_need": effective_cta_need,
                "text": draft,
            }
        )

    return {
        "selected_theme": context.theme,
        "selected_angle": context.angle,
        "positioning_flags": context.positioning_flags,
        "style_profile": context.style_profile,
        "user_preferences": context.user_preferences,
        "why_now": context.why_now,
        "preferred_cta_mode": context.preferred_cta_mode,
        "case_context": context.case_context,
        "user_theme_verdict": context.user_theme_verdict,
        "style_references": [
            {
                "post_id": row.get("post_id"),
                "date": row.get("date"),
                "title_hook": row.get("title_hook"),
                "primary_theme": row.get("primary_theme"),
            }
            for row in context.style_references
        ],
        "drafts": drafts,
    }
