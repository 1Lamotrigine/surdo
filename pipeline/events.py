"""События конвейера фраз (E3–E4): ``asr_text``, ``utterance``, клипы и слова без жеста.

Фоновая очередь E2 работает в отдельном потоке, а Channels-группы живут в
цикле событий ASGI. Чтобы не смешивать циклы, ASGI-приложение при каждом
запросе запоминает свой цикл (``bind_event_loop``), а рассылка из фонового
потока ставится в него через ``run_coroutine_threadsafe``. В тестах без ASGI
цикла события просто не отправляются — обработка фразы от этого не падает.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from channels.layers import get_channel_layer
from django.db.models.functions import Upper

from dictionary.models import Language, Sign, SignStatus

logger = logging.getLogger(__name__)

# Тип события Channels для ``asr.text`` превращается в метод consumer'а
# ``asr_text``. Для ``utterance`` имя совпадает с методом напрямую.
ASR_TEXT_EVENT = "asr.text"
UTTERANCE_EVENT = "utterance"
UNKNOWN_WORDS_EVENT = "unknown.words"

_BROADCAST_TIMEOUT = 5.0

_event_loop: asyncio.AbstractEventLoop | None = None
_event_loop_lock = threading.Lock()


def bind_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Запомнить цикл событий ASGI для рассылки из фоновых потоков."""
    global _event_loop
    with _event_loop_lock:
        _event_loop = loop


def group_name_for(room_id: int) -> str:
    """Имя группы комнаты (совпадает с ``rooms.consumers.group_name_for``)."""
    return f"room_{room_id}"


def _clip_payload(sign: Sign, clip) -> dict:
    return {
        "id": clip.pk,
        "gloss": sign.gloss,
        "format": clip.format,
        "version": clip.version,
        "fps": clip.fps,
        "frames": clip.frames,
        "duration_ms": clip.duration_ms,
        "url": clip.file_url(),
    }


def select_best_clip(clips: list) -> object | None:
    """Лучший клип жеста: анимация важнее landmarks, затем версия и кадры.

    Если у жеста есть и запись с камеры, и ручная анимация (H1), показываем
    анимацию — она сделана специально для модели. Иначе поведение прежнее:
    последняя версия, затем больше кадров.
    """
    if not clips:
        return None
    return max(
        clips,
        key=lambda clip: (
            clip.is_animation,
            clip.version,
            clip.frames,
        ),
    )


def _iter_gloss_slots(glosses: dict):
    """Пары «индекс токена / вид / глосса клипа» в порядке показа."""
    for token_index, token in enumerate(glosses.get("tokens") or []):
        token_type = token.get("type")
        if token_type == "sign" and token.get("gloss"):
            yield token_index, "sign", str(token["gloss"]).strip()
        elif token_type == "number" and token.get("value") is not None:
            yield token_index, "number", f"ЦИФРА_{token['value']}"
        elif token_type == "fingerspell":
            for raw_letter in token.get("letters") or []:
                letter = str(raw_letter).upper()
                if letter.isdigit():
                    yield token_index, "fingerspell", f"ЦИФРА_{letter}"
                elif letter:
                    yield token_index, "fingerspell", f"ДАКТИЛЬ_{letter}"


def clip_refs_for_glosses(glosses: dict) -> list[dict]:
    """Собрать клипы для токенов глосс в порядке показа.

    Жест и число дают один клип, слово по буквам — клип на каждую найденную
    букву. Берётся лучший клип проверенного жеста (последняя версия, затем
    больше кадров); отсутствующие клипы просто пропускаются, и клиент покажет
    только субтитры. Ссылки отдаются клиенту уже в том порядке, в котором их
    нужно проигрывать, вместе с ``token_index`` для подсветки слова.
    """
    lang = glosses.get("lang")
    if lang not in Language.values:
        return []

    slots = list(_iter_gloss_slots(glosses))
    if not slots:
        return []

    wanted = {gloss.upper() for _, _, gloss in slots}
    signs = (
        Sign.objects.filter(lang=lang, status=SignStatus.VERIFIED)
        .annotate(gloss_key=Upper("gloss"))
        .filter(gloss_key__in=wanted)
        .prefetch_related("clips")
    )

    # Один проверенный жест на нормализованную глоссу; при дублях берём первый.
    best_by_gloss: dict[str, tuple[Sign, object]] = {}
    for sign in signs:
        clips = list(sign.clips.all())
        if not clips:
            continue
        best = select_best_clip(clips)
        if best is None:
            continue
        best_by_gloss.setdefault(sign.gloss.upper(), (sign, best))

    refs: list[dict] = []
    for token_index, kind, gloss in slots:
        found = best_by_gloss.get(gloss.upper())
        if found is None:
            continue
        sign, clip = found
        refs.append(
            {
                "token_index": token_index,
                "kind": kind,
                **_clip_payload(sign, clip),
            }
        )
    return refs


def utterance_event(utterance) -> dict:
    """Событие ``utterance``: глоссы конвейера (E1/F4) плюс клипы словаря."""
    payload = utterance.as_event()
    payload["clips"] = clip_refs_for_glosses(utterance.glosses)
    return payload


def _send(group: str, event: dict) -> None:
    """Отправить событие в группу из синхронного фонового потока."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning("channel layer is not configured: event=%s", event.get("type"))
        return

    with _event_loop_lock:
        loop = _event_loop
    if loop is None or loop.is_closed() or not loop.is_running():
        # Нет активного ASGI-цикла (например, прямой вызов обработчика в
        # тестах). Рассылать некуда, но обработка фразы должна продолжиться.
        logger.debug("no running ASGI loop: event=%s group=%s", event.get("type"), group)
        return

    coroutine = channel_layer.group_send(group, event)
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is loop:
        # Защита от deadlock, если когда-нибудь вызвать рассылку из самого
        # ASGI-цикла: не ждём future, а планируем задачу.
        loop.create_task(coroutine)
        return

    try:
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        future.result(timeout=_BROADCAST_TIMEOUT)
    except Exception:
        logger.exception(
            "failed to broadcast %s to %s",
            event.get("type"),
            group,
        )


def broadcast_asr_text(room_id: int, text: str) -> None:
    """Показать распознанный текст сразу, не дожидаясь глосс."""
    _send(group_name_for(room_id), {"type": ASR_TEXT_EVENT, "text": text})


def unknown_words_for(utterance) -> list[str]:
    """Слова фразы без проверенного жеста (дактиль) для преподавателя."""
    unknown = (utterance.glosses or {}).get("unknown") or []
    return [str(word) for word in unknown if str(word).strip()]


def broadcast_utterance(utterance) -> None:
    """Разослать сохранённую фразу с глоссами и ссылками на клипы.

    Вместе с фразой уходит ``unknown_words``: consumer отдаёт его только
    преподавателю, студент продолжает получать лишь текст и клипы.
    """
    group = group_name_for(utterance.room_id)
    _send(group, {"type": UTTERANCE_EVENT, "utterance": utterance_event(utterance)})
    _send(
        group,
        {
            "type": UNKNOWN_WORDS_EVENT,
            "words": unknown_words_for(utterance),
            "utterance_id": getattr(utterance, "pk", None),
        },
    )
