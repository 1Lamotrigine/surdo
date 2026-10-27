"""Переходы статусов жеста: чистые правила без обращений к базе.

Жизненный цикл (FR-19): ``draft`` → ``review`` → ``verified`` → ``rejected``.
Редактор готовит жест и отправляет на проверку, эксперт утверждает (тогда
растёт версия словаря) или отклоняет с комментарием. Отклонённый жест можно
доработать и отправить на проверку снова.

Модуль намеренно без зависимостей от Django-модели: правила можно покрыть
тестами и переиспользовать в админке, API и интерфейсе эксперта.
"""

from __future__ import annotations

from enum import StrEnum


class SignStatus(StrEnum):
    """Статус жеста (значения совпадают с ``dictionary.models.SignStatus``)."""

    DRAFT = "draft"
    REVIEW = "review"
    VERIFIED = "verified"
    REJECTED = "rejected"


# Какую роль требует переход: редактор словаря или эксперт-носитель.
ROLE_EDITOR = "editor"
ROLE_EXPERT = "expert"

# Разрешённые переходы: из статуса → в статус → требуемая роль.
TRANSITIONS: dict[str, dict[str, str]] = {
    SignStatus.DRAFT: {
        SignStatus.REVIEW: ROLE_EDITOR,
    },
    SignStatus.REVIEW: {
        SignStatus.VERIFIED: ROLE_EXPERT,
        SignStatus.REJECTED: ROLE_EXPERT,
        SignStatus.DRAFT: ROLE_EDITOR,  # вернуть себе на доработку
    },
    SignStatus.REJECTED: {
        SignStatus.DRAFT: ROLE_EDITOR,
        SignStatus.REVIEW: ROLE_EDITOR,
    },
    SignStatus.VERIFIED: {
        SignStatus.REVIEW: ROLE_EXPERT,  # переоткрыть спорный жест
        SignStatus.REJECTED: ROLE_EXPERT,  # отозвать утверждение
    },
}

# Статусы, после которых жест считается проверенным носителем.
VERIFIED_STATUS = SignStatus.VERIFIED
# Статус, при переходе в который растёт версия словаря.
VERSION_BUMP_STATUS = SignStatus.VERIFIED


class StatusTransitionError(ValueError):
    """Переход статуса запрещён."""


def can_transition(current: str, target: str) -> bool:
    """Разрешён ли переход ``current`` → ``target`` по таблице переходов."""
    return target in TRANSITIONS.get(current, {})


def required_role(current: str, target: str) -> str | None:
    """Роль, которая может выполнить переход, или ``None``, если он запрещён."""
    return TRANSITIONS.get(current, {}).get(target)


def allowed_targets(current: str) -> set[str]:
    """Все статусы, в которые можно перейти из текущего."""
    return set(TRANSITIONS.get(current, {}))


def validate_transition(current: str, target: str) -> str:
    """Проверить переход и вернуть требуемую роль.

    Бросает ``StatusTransitionError`` для запрещённого перехода или совпадения
    статусов (жест уже в этом статусе).
    """
    if current == target:
        raise StatusTransitionError(f"Жест уже в статусе «{target}».")
    role = required_role(current, target)
    if role is None:
        raise StatusTransitionError(
            f"Нельзя перевести жест из «{current}» в «{target}»."
        )
    return role
