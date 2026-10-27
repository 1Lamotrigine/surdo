"""Сервис конвейера: приём текста фразы и сохранение ``Utterance``.

E1 — упрощённый режим без ИИ: слова ищутся в проверенном словаре, остальные
показываются дактилем и попадают в очередь нераспознанных слов (FR-9). F4
передаёт сюда готовые глоссы LLM/F2, ``gloss_ms`` и ``degraded``; без них
``create_utterance`` по-прежнему работает путём E1. HTTP-приём (E2), фоновые
очереди и рассылка событий (E3) используют сервис, не дублируя разбор текста.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from dictionary.models import Language, Sign, SignStatus
from dictionary.services import record_unknown_words
from pipeline.glosses import build_simplified_glosses, normalize_word
from pipeline.models import Utterance
from rooms.models import Room

# Разумный предел текста одной фразы: защищает JSONField и очередь от мусора.
MAX_UTTERANCE_TEXT_LENGTH = 2000

# Сколько последних фраз показывает лента преподавателя (E5).
PHRASE_FEED_LIMIT = 20

# Язык комнаты (речь) → язык жестов, по которому ищем словарь.
SIGN_LANG_BY_ROOM_LANG = {
    Room.Language.RU: Language.RSL,
    Room.Language.KK: Language.KSL,
}


class UtteranceValidationError(ValueError):
    """Текст фразы не прошёл проверку."""


# FR-15: зелёный до 5 с, жёлтый до 10 с, красный выше.
LAG_GREEN_MAX_MS = 5_000
LAG_YELLOW_MAX_MS = 10_000

# Клиентские часы могут расходиться с сервером: используем `ts` только если
# расхождение небольшое, иначе считаем по времени получения события.
_DISPLAY_TS_TOLERANCE_SECONDS = 60


@dataclass(frozen=True)
class LagStatus:
    """Отставание показа фразы от начала её обработки (FR-15)."""

    lag_ms: int
    level: str

    def as_event(self) -> dict:
        return {"lag_ms": self.lag_ms, "level": self.level}


def lag_level(lag_ms: int) -> str:
    """Уровень индикатора отставания: ``green``, ``yellow`` или ``red``."""
    if lag_ms <= LAG_GREEN_MAX_MS:
        return "green"
    if lag_ms <= LAG_YELLOW_MAX_MS:
        return "yellow"
    return "red"


def displayed_at_from_ts(value: Any, *, now: datetime | None = None) -> datetime:
    """Разобрать клиентский ``ts`` (epoch мс/с или ISO) с защитой от сдвига часов.

    Если поле отсутствует или время сильно расходится с серверным, берём
    момент получения события: отставание не должно зависеть от часов студента.
    """
    now = now or timezone.now()
    parsed: datetime | None = None
    if isinstance(value, bool):
        parsed = None
    elif isinstance(value, (int, float)):
        seconds = value / 1000 if abs(value) > 100_000_000_000 else value
        try:
            parsed = datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            parsed = None
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None and timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, UTC)

    if parsed is None:
        return now
    if abs((now - parsed).total_seconds()) > _DISPLAY_TS_TOLERANCE_SECONDS:
        return now
    return parsed


def record_display_started(
    room_id: int,
    utterance_id: int,
    *,
    ts: Any = None,
    received_at: datetime | None = None,
) -> LagStatus | None:
    """Сохранить ``display_lag_ms`` и вернуть статус для преподавателя.

    Отставание — время от ``Utterance.started_at`` (начало обработки фразы) до
    реального начала показа у студента. Первое событие фиксирует метрику:
    повторный ``display_started`` (например, после переподключения) не должен
    искусственно увеличивать отставание. Фраза обязана принадлежать комнате.
    """
    utterance = Utterance.objects.filter(room_id=room_id, pk=utterance_id).first()
    if utterance is None:
        return None

    if utterance.display_lag_ms is None:
        displayed_at = displayed_at_from_ts(ts, now=received_at)
        lag_ms = max(0, round((displayed_at - utterance.started_at).total_seconds() * 1000))
        utterance.display_lag_ms = lag_ms
        utterance.save(update_fields=("display_lag_ms",))

    return LagStatus(lag_ms=utterance.display_lag_ms, level=lag_level(utterance.display_lag_ms))


def latest_display_lag_ms(room_id: int) -> int | None:
    """Последнее известное отставание комнаты (для политики F8).

    Пока новая фраза обрабатывается, фактическое отставание ещё неизвестно:
    студент сообщит его только после начала показа. Поэтому берём метрику
    последней показанной фразы комнаты; если такой ещё нет — ``None``.
    """
    return (
        Utterance.objects.filter(room_id=room_id, display_lag_ms__isnull=False)
        .order_by("-seq")
        .values_list("display_lag_ms", flat=True)
        .first()
    )


def normalize_text(text: str) -> str:
    """Схлопнуть пробелы и проверить, что фраза не пустая."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise UtteranceValidationError("Фраза не может быть пустой.")
    if len(cleaned) > MAX_UTTERANCE_TEXT_LENGTH:
        raise UtteranceValidationError(
            f"Фраза длиннее {MAX_UTTERANCE_TEXT_LENGTH} символов."
        )
    return cleaned


def sign_language_for_room(room: Room) -> str:
    """Язык жестов комнаты: русская речь → РЖЯ, казахская → КЖЯ."""
    return SIGN_LANG_BY_ROOM_LANG.get(room.lang, Language.RSL)


def _clean_lang(lang: str | None, room: Room) -> str:
    if not lang:
        return sign_language_for_room(room)
    if lang not in Language.values:
        raise UtteranceValidationError(f"Неизвестный язык: {lang}.")
    return lang


def sign_language_for_utterance(room: Room, lang: str | None = None) -> str:
    """Язык жестов фразы с учётом явного языка и языка комнаты.

    F4 вычисляет язык до вызова LLM, поэтому проверка вынесена в публичную
    функцию: очередь не обращается к приватному ``_clean_lang``.
    """
    return _clean_lang(lang, room)


def verified_sign_glosses(lang: str) -> dict[str, str]:
    """Карта «нормализованная глосса → глосса из БД» для проверенных жестов.

    Студентам показывает только проверенный словарь (FR-19). Пока в комнате
    нет демо-режима с черновиками: это отдельный сценарий словаря, а не E1.
    """
    glosses = Sign.objects.filter(
        lang=lang,
        status=SignStatus.VERIFIED,
    ).values_list("gloss", flat=True)
    result: dict[str, str] = {}
    for gloss in glosses:
        key = normalize_word(gloss)
        if key:
            result.setdefault(key, gloss)
    return result


def create_utterance(
    room: Room,
    text: str,
    *,
    lang: str | None = None,
    asr_ms: int | None = None,
    started_at=None,
    glosses: dict | None = None,
    gloss_ms: int | None = None,
    degraded: bool = False,
    playback: dict | None = None,
) -> Utterance:
    """Сохранить фразу и отметить незнакомые слова.

    Без ``glosses`` работает прежний путь E1: точная форма из проверенного
    словаря или дактиль. F4 передаёт готовые глоссы LLM/F2 и измеренный
    ``gloss_ms``; ``degraded`` означает «показано только субтитрами» или
    упрощённый режим. В переданных глоссах сервер всё равно подставляет
    авторитетные ``text``/``lang``.

    Порядковый номер ``seq`` выдаётся внутри транзакции под блокировкой строки
    комнаты: две одновременные фразы одной комнаты не получат один номер (ТЗ
    5.7). Незнакомые слова записываются в очередь в той же транзакции, поэтому
    при сбое сохранения фразы счётчики не разъедутся.

    ``asr_ms`` заполняется, когда текст пришёл из распознавания речи (E2);
    ``gloss_ms`` измеряется здесь для E1. ``display_lag_ms`` заполняет consumer,
    когда студент присылает ``display_started`` (E4). ``playback`` — политика
    догона F8, вычисленная по предыдущему отставанию и сохранённая вместе с
    фразой, чтобы история и переподключение показывали её теми же параметрами.
    """
    started_at = started_at or timezone.now()
    clean_text = normalize_text(text)
    sign_lang = _clean_lang(lang, room)
    if playback is not None and not isinstance(playback, dict):
        raise UtteranceValidationError("Параметры показа должны быть объектом.")

    if glosses is None:
        started = perf_counter()
        glosses = build_simplified_glosses(
            clean_text,
            lang=sign_lang,
            signs=verified_sign_glosses(sign_lang),
        )
        measured_gloss_ms = max(0, round((perf_counter() - started) * 1000))
    else:
        if not isinstance(glosses, dict) or not isinstance(glosses.get("tokens"), list):
            raise UtteranceValidationError("Глоссы фразы должны содержать список токенов.")
        glosses = copy.deepcopy(glosses)
        glosses["lang"] = sign_lang
        glosses["text"] = clean_text
        measured_gloss_ms = max(0, int(gloss_ms or 0))

    # Каждое вхождение незнакомого слова увеличивает счётчик очереди (FR-9).
    unknown_lemmas = [
        token["src"] for token in glosses["tokens"] if token["type"] == "fingerspell"
    ]

    with transaction.atomic():
        # Блокировка комнаты сериализует выдачу seq между транзакциями.
        Room.objects.select_for_update().get(pk=room.pk)
        last_seq = Utterance.objects.filter(room=room).aggregate(Max("seq"))["seq__max"]
        utterance = Utterance.objects.create(
            room=room,
            seq=(last_seq or 0) + 1,
            text=clean_text,
            glosses=glosses,
            asr_ms=asr_ms,
            gloss_ms=measured_gloss_ms,
            degraded=degraded,
            playback=copy.deepcopy(playback) if playback else {},
            started_at=started_at,
        )
        if unknown_lemmas:
            record_unknown_words(unknown_lemmas, lang=sign_lang)

    return utterance


def recent_room_utterances(
    room: Room, *, limit: int = PHRASE_FEED_LIMIT
) -> list[Utterance]:
    """Последние фразы комнаты по возрастанию ``seq`` для ленты преподавателя."""
    queryset = Utterance.objects.filter(room=room).order_by("-seq")
    return list(queryset[: max(1, limit)])[::-1]
