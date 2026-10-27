"""Модель Room: значения по умолчанию, уникальность кода и закрытие."""

import pytest
from django.db import IntegrityError, transaction

from rooms.models import Room

pytestmark = pytest.mark.django_db


def test_room_defaults_and_automatic_join_code(owner):
    room = Room.objects.create(owner=owner)

    assert room.title == "Урок"
    assert room.lang == Room.Language.RU
    assert room.status == Room.Status.OPEN
    assert room.demo_mode is False
    assert room.closed_at is None
    assert room.is_open
    assert not room.is_closed
    assert len(room.join_code) == 6
    assert set(room.join_code) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def test_duplicate_join_code_is_rejected_for_open_rooms(owner):
    Room.objects.create(owner=owner, join_code="ABC234")

    with pytest.raises(IntegrityError), transaction.atomic():
        Room.objects.create(owner=owner, join_code="ABC234")


def test_join_code_can_be_reused_after_room_is_closed(owner):
    first = Room.objects.create(owner=owner, join_code="ABC234")

    first.close()

    assert first.status == Room.Status.CLOSED
    assert first.closed_at is not None
    second = Room.objects.create(owner=owner, join_code="ABC234")
    assert second.is_open


def test_close_is_idempotent(owner):
    room = Room.objects.create(owner=owner)
    room.close()
    closed_at = room.closed_at

    room.close()
    room.refresh_from_db()

    assert room.closed_at == closed_at


def test_setting_closed_status_fills_closed_at(owner):
    room = Room.objects.create(owner=owner)
    room.status = Room.Status.CLOSED

    room.save(update_fields=("status",))

    room.refresh_from_db()
    assert room.closed_at is not None
