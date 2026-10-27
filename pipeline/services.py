"""Сервис конвейера: приём текста фразы и сохранение ``Utterance``.

E1 — упрощённый режим без ИИ: слова ищутся в проверенном словаре, остальные
показываются дактилем и попадают в очередь нераспознанных слов (FR-9). Здесь
живёт общая серверная логика; HTTP-приём (E2), фоновые очереди и рассылка
событий (E3) используют её, не дублируя разбор текста.
"""

from __future__ import annotations

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
) -> Utterance:
    """Разобрать текст, сохранить фразу и отметить незнакомые слова.

    Порядковый номер ``seq`` выдаётся внутри транзакции под блокировкой строки
    комнаты: две одновременные фразы одной комнаты не получат один номер (ТЗ
    5.7). Незнакомые слова записываются в очередь в той же транзакции, поэтому
    при сбое сохранения фразы счётчики не разъедутся.

    ``asr_ms`` заполняется, когда текст пришёл из распознавания речи (E2);
    ``gloss_ms`` измеряется здесь. ``display_lag_ms`` заполняет consumer,
    когда студент присылает ``display_started`` (E4).
    """
    started_at = started_at or timezone.now()
    clean_text = normalize_text(text)
    sign_lang = _clean_lang(lang, room)

    started = perf_counter()
    glosses = build_simplified_glosses(
        clean_text,
        lang=sign_lang,
        signs=verified_sign_glosses(sign_lang),
    )
    gloss_ms = max(0, round((perf_counter() - started) * 1000))

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
            gloss_ms=gloss_ms,
            started_at=started_at,
        )
        if unknown_lemmas:
            record_unknown_words(unknown_lemmas, lang=sign_lang)

    return utterance
