"""Очередь нераспознанных слов: агрегация повторов и статусы.

Слово без жеста (FR-9) попадает в очередь после того, как встретилось во фразе.
Повторы агрегируются по ``(lemma, lang)``: счётчик растёт, ``last_seen_at``
обновляется. Редактор берёт сверху самое частое слово, ставит в работу
(``queued``) и после записи клипа помечает ``recorded`` (FR-21, D4).

Правила статусов — чистые функции без обращений к базе, как в
``dictionary.statuses``: их удобно тестировать и переиспользовать в API и
интерфейсе редактора.
"""

from __future__ import annotations

from enum import StrEnum


class UnknownWordStatus(StrEnum):
    """Статус слова в очереди (значения совпадают с моделью)."""

    NEW = "new"
    QUEUED = "queued"
    RECORDED = "recorded"


# Разрешённые переходы: из статуса → в статус.
TRANSITIONS: dict[str, set[str]] = {
    UnknownWordStatus.NEW: {UnknownWordStatus.QUEUED},
    UnknownWordStatus.QUEUED: {
        UnknownWordStatus.RECORDED,
        UnknownWordStatus.NEW,  # вернуть в очередь, если не берёмся
    },
    UnknownWordStatus.RECORDED: {UnknownWordStatus.QUEUED},  # переоткрыть запись
}


class UnknownWordTransitionError(ValueError):
    """Переход статуса слова в очереди запрещён."""


def can_transition(current: str, target: str) -> bool:
    """Разрешён ли переход ``current`` → ``target``."""
    return target in TRANSITIONS.get(current, set())


def allowed_targets(current: str) -> set[str]:
    """Все статусы, в которые можно перейти из текущего."""
    return set(TRANSITIONS.get(current, set()))


def validate_transition(current: str, target: str) -> None:
    """Проверить переход, иначе ``UnknownWordTransitionError``."""
    if current == target:
        raise UnknownWordTransitionError(f"Слово уже в статусе «{target}».")
    if not can_transition(current, target):
        raise UnknownWordTransitionError(
            f"Нельзя перевести слово из «{current}» в «{target}»."
        )
