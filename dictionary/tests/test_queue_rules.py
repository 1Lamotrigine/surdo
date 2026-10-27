"""Правила статусов очереди нераспознанных слов (``dictionary.queue``)."""

import pytest

from dictionary.models import UnknownWordStatus as ModelStatus
from dictionary.queue import (
    UnknownWordStatus,
    UnknownWordTransitionError,
    allowed_targets,
    can_transition,
    validate_transition,
)


def test_status_values_match_model_choices():
    """StrEnum статусов и Django TextChoices модели не расходятся."""
    assert set(UnknownWordStatus) == set(ModelStatus.values)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (UnknownWordStatus.NEW, UnknownWordStatus.QUEUED),
        (UnknownWordStatus.QUEUED, UnknownWordStatus.RECORDED),
        (UnknownWordStatus.QUEUED, UnknownWordStatus.NEW),
        (UnknownWordStatus.RECORDED, UnknownWordStatus.QUEUED),
    ],
)
def test_allowed_transitions(current, target):
    assert can_transition(current, target)
    validate_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (UnknownWordStatus.NEW, UnknownWordStatus.RECORDED),  # мимо «в работе»
        (UnknownWordStatus.NEW, UnknownWordStatus.NEW),
        (UnknownWordStatus.RECORDED, UnknownWordStatus.NEW),
        (UnknownWordStatus.RECORDED, UnknownWordStatus.RECORDED),
    ],
)
def test_forbidden_transitions(current, target):
    assert not can_transition(current, target)
    with pytest.raises(UnknownWordTransitionError):
        validate_transition(current, target)


def test_allowed_targets():
    assert allowed_targets(UnknownWordStatus.NEW) == {UnknownWordStatus.QUEUED}
    assert allowed_targets(UnknownWordStatus.QUEUED) == {
        UnknownWordStatus.RECORDED,
        UnknownWordStatus.NEW,
    }
    assert allowed_targets(UnknownWordStatus.RECORDED) == {UnknownWordStatus.QUEUED}


def test_unknown_status_has_no_transitions():
    assert allowed_targets("nonsense") == set()
    assert not can_transition("nonsense", UnknownWordStatus.QUEUED)
