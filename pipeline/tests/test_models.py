"""Модель ``Utterance``: поля, уникальность seq и представление события."""

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from pipeline.models import Utterance
from rooms.models import Room

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )


@pytest.fixture
def room(owner):
    return Room.objects.create(owner=owner)


def test_utterance_defaults(room):
    started_at = timezone.now()
    utterance = Utterance.objects.create(room=room, seq=1, started_at=started_at)

    assert utterance.text == ""
    assert utterance.glosses == {}
    assert utterance.asr_ms is None
    assert utterance.gloss_ms is None
    assert utterance.display_lag_ms is None
    assert utterance.degraded is False
    assert utterance.started_at == started_at
    assert utterance.created_at is not None


def test_utterance_room_seq_is_unique(room):
    Utterance.objects.create(room=room, seq=1, started_at=timezone.now())

    with pytest.raises(IntegrityError), transaction.atomic():
        Utterance.objects.create(room=room, seq=1, started_at=timezone.now())


def test_same_seq_allowed_in_other_room(owner, room):
    other_room = Room.objects.create(owner=owner)
    Utterance.objects.create(room=room, seq=1, started_at=timezone.now())

    other = Utterance.objects.create(room=other_room, seq=1, started_at=timezone.now())

    assert other.pk is not None


def test_utterances_ordered_by_room_and_seq(room):
    second = Utterance.objects.create(room=room, seq=2, started_at=timezone.now())
    first = Utterance.objects.create(room=room, seq=1, started_at=timezone.now())

    assert list(Utterance.objects.all()) == [first, second]


def test_as_event_contains_glosses_and_seq(room):
    started_at = timezone.now()
    utterance = Utterance.objects.create(
        room=room,
        seq=3,
        text="Откройте учебник",
        glosses={"tokens": [{"type": "sign", "gloss": "УЧЕБНИК"}]},
        started_at=started_at,
    )

    event = utterance.as_event()

    assert event["id"] == utterance.pk
    assert event["seq"] == 3
    assert event["text"] == "Откройте учебник"
    assert event["glosses"] == utterance.glosses
    assert event["degraded"] is False
    assert event["ts"] == started_at.isoformat()
