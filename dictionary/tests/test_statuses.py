"""Правила переходов статусов жеста (чистые функции ``dictionary.statuses``)."""

import pytest

from dictionary.models import SignStatus as ModelStatus
from dictionary.statuses import (
    ROLE_EDITOR,
    ROLE_EXPERT,
    SignStatus,
    StatusTransitionError,
    allowed_targets,
    can_transition,
    required_role,
    validate_transition,
)

# Все переходы, разрешённые по жизненному циклу FR-19.
ALLOWED = {
    (SignStatus.DRAFT, SignStatus.REVIEW): ROLE_EDITOR,
    (SignStatus.REVIEW, SignStatus.VERIFIED): ROLE_EXPERT,
    (SignStatus.REVIEW, SignStatus.REJECTED): ROLE_EXPERT,
    (SignStatus.REVIEW, SignStatus.DRAFT): ROLE_EDITOR,
    (SignStatus.REJECTED, SignStatus.DRAFT): ROLE_EDITOR,
    (SignStatus.REJECTED, SignStatus.REVIEW): ROLE_EDITOR,
    (SignStatus.VERIFIED, SignStatus.REVIEW): ROLE_EXPERT,
    (SignStatus.VERIFIED, SignStatus.REJECTED): ROLE_EXPERT,
}


def test_status_values_match_model_choices():
    """StrEnum статусов и Django TextChoices модели не расходятся."""
    assert set(SignStatus) == set(ModelStatus.values)


@pytest.mark.parametrize(("current", "target"), list(ALLOWED))
def test_allowed_transitions(current, target):
    assert can_transition(current, target)
    assert required_role(current, target) == ALLOWED[(current, target)]


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (SignStatus.DRAFT, SignStatus.VERIFIED),  # нельзя утвердить мимо ревью
        (SignStatus.DRAFT, SignStatus.REJECTED),
        (SignStatus.REJECTED, SignStatus.VERIFIED),  # мимо повторной проверки
        (SignStatus.VERIFIED, SignStatus.DRAFT),
        (SignStatus.DRAFT, SignStatus.DRAFT),  # тот же статус
    ],
)
def test_forbidden_transitions(current, target):
    if current == target:
        with pytest.raises(StatusTransitionError):
            validate_transition(current, target)
    else:
        assert not can_transition(current, target)
        with pytest.raises(StatusTransitionError):
            validate_transition(current, target)


def test_validate_returns_required_role():
    assert validate_transition(SignStatus.DRAFT, SignStatus.REVIEW) == ROLE_EDITOR
    assert validate_transition(SignStatus.REVIEW, SignStatus.VERIFIED) == ROLE_EXPERT


def test_allowed_targets():
    assert allowed_targets(SignStatus.DRAFT) == {SignStatus.REVIEW}
    assert allowed_targets(SignStatus.REVIEW) == {
        SignStatus.VERIFIED,
        SignStatus.REJECTED,
        SignStatus.DRAFT,
    }
    assert allowed_targets(SignStatus.VERIFIED) == {
        SignStatus.REVIEW,
        SignStatus.REJECTED,
    }


def test_unknown_status_has_no_transitions():
    assert allowed_targets("nonsense") == set()
    assert not can_transition("nonsense", SignStatus.REVIEW)
