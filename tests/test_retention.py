"""Хранение данных (G4, ТЗ 17): удаление старых записей и команда purge_old_data."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from pipeline.models import Utterance
from pipeline.retention import purge_expired_data
from rooms.models import Message, Participant, Room

pytestmark = pytest.mark.django_db


def _make_utterance(room: Room, *, seq: int, created_at) -> Utterance:
    utterance = Utterance.objects.create(
        room=room,
        seq=seq,
        text="привет",
        glosses={"tokens": []},
        started_at=created_at,
    )
    # created_at — auto_now_add, поэтому задаём напрямую через update.
    Utterance.objects.filter(pk=utterance.pk).update(created_at=created_at)
    return utterance


def _make_message(room: Room, *, created_at, body="вопрос") -> Message:
    message = Message.objects.create(room=room, author_name="Гость", body=body)
    Message.objects.filter(pk=message.pk).update(created_at=created_at)
    return message


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(
        email="loadtest-owner@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )


@pytest.fixture
def room(owner):
    return Room.objects.create(owner=owner, title="Алгебра")


def test_purges_old_messages_and_keeps_fresh(room):
    old = _make_message(room, created_at=timezone.now() - timedelta(days=100))
    fresh = _make_message(room, created_at=timezone.now() - timedelta(days=1))

    result = purge_expired_data(days=90)

    assert result.messages == 1
    assert not Message.objects.filter(pk=old.pk).exists()
    assert Message.objects.filter(pk=fresh.pk).exists()


def test_purges_old_utterances(room):
    old = _make_utterance(room, seq=1, created_at=timezone.now() - timedelta(days=100))
    fresh = _make_utterance(room, seq=2, created_at=timezone.now())

    result = purge_expired_data(days=90)

    assert result.utterances == 1
    assert not Utterance.objects.filter(pk=old.pk).exists()
    assert Utterance.objects.filter(pk=fresh.pk).exists()


def test_purges_closed_room_with_children(owner):
    room = Room.objects.create(owner=owner, title="Старая")
    Participant.objects.create(room=room, guest_name="Гость")
    _make_message(room, created_at=timezone.now() - timedelta(days=120))
    _make_utterance(room, seq=1, created_at=timezone.now() - timedelta(days=120))
    room.close()
    Room.objects.filter(pk=room.pk).update(closed_at=timezone.now() - timedelta(days=120))

    result = purge_expired_data(days=90)

    assert result.rooms >= 1
    assert not Room.objects.filter(pk=room.pk).exists()
    # Каскад: участников и данные комнаты тоже нет.
    assert not Participant.objects.filter(room_id=room.pk).exists()
    assert not Message.objects.filter(room_id=room.pk).exists()


def test_keeps_open_room_and_recent_closed(owner):
    open_room = Room.objects.create(owner=owner, title="Открытая")
    closed_recent = Room.objects.create(owner=owner, title="Недавно закрытая")
    closed_recent.close()

    purge_expired_data(days=90)

    assert Room.objects.filter(pk=open_room.pk).exists()
    assert Room.objects.filter(pk=closed_recent.pk).exists()


def test_default_days_comes_from_settings(settings, room):
    settings.RETENTION_DAYS = 7
    _make_message(room, created_at=timezone.now() - timedelta(days=10))

    result = purge_expired_data()

    assert result.messages == 1


def test_command_purge_old_data(room, capsys):
    _make_message(room, created_at=timezone.now() - timedelta(days=100))

    call_command("purge_old_data", days=90)

    captured = capsys.readouterr()
    assert "Удалено" in captured.out
    assert not Message.objects.filter(room=room).exists()


def test_command_dry_run_does_not_delete(room, capsys):
    message = _make_message(room, created_at=timezone.now() - timedelta(days=100))

    call_command("purge_old_data", days=90, dry_run=True)

    captured = capsys.readouterr()
    assert "dry-run" in captured.out
    assert Message.objects.filter(pk=message.pk).exists()
