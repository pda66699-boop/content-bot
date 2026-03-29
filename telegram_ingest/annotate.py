from __future__ import annotations

from .models import NormalizedTelegramPost


def annotate_post(post: NormalizedTelegramPost) -> NormalizedTelegramPost:
    """Heuristic first-pass annotator.

    Later this layer can be replaced or strengthened by LLM-assisted annotation
    and by a refreshed positioning base from the user.
    """

    lower = post.body_text.lower()

    if post.mentions_ai:
        if "хаос" in lower:
            post.primary_theme = "ИИ и хаос в процессах"
            post.core_thesis = "ИИ усиливает уже существующую среду и без системы может только увеличить хаос."
        elif "функц" in lower:
            post.primary_theme = "применение ИИ по функциям бизнеса"
            post.core_thesis = "ИИ чаще работает там, где есть повторяемость, понятный результат и управляемый процесс."
        else:
            post.primary_theme = "ИИ как инструмент внутри системы"
            post.core_thesis = "ИИ стоит рассматривать как усилитель процессов и ролей, а не как самостоятельное решение."
        return post

    if "подрядчик" in lower or "договор" in lower:
        post.primary_theme = "подрядчики и контроль исполнения"
        post.core_thesis = "Проблемы с подрядчиками чаще связаны с отсутствием ясных условий и управленческого контроля."
        return post

    if "оргструкт" in lower or "роль" in lower:
        post.primary_theme = "оргструктура и роли"
        post.core_thesis = "Без ролей и ясной ответственности управляемость не появляется, даже если команда уже есть."
        return post

    if "регламент" in lower:
        post.primary_theme = "регламенты и процессы"
        post.core_thesis = "Регламент приносит пользу только тогда, когда поддерживает живой процесс и закрепленную ответственность."
        return post

    if "выгора" in lower or "операцион" in lower:
        post.primary_theme = "перегрузка собственника"
        post.core_thesis = "Постоянная операционная перегрузка является следствием не архитектуры роли собственника, а не просто усталости."
        return post

    if "издерж" in lower or "потер" in lower:
        post.primary_theme = "скрытые потери в операционке"
        post.core_thesis = "Главные потери бизнеса часто скрыты в процессах, времени и управленческих разрывах, а не только в бюджете."
        return post

    post.primary_theme = "систематизация и управляемость"
    post.core_thesis = "Системность начинается там, где собственник перестает надеяться на героизм людей и строит управляемую архитектуру."
    return post
