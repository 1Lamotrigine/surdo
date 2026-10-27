"""Модель Participant: гость и зарегистрированный пользователь."""

import pytest

from rooms.models import Participant, Room

pytestmark = pytest.mark.django_db


def test_guest_participant_display_name_and_flags(owner):
    room = Room.objects.create(owner=owner)

    guest = Participant.objects.create(room=room, guest_name="Айгуль", session_key="abc")

    assert guest.display_name == "Айгуль"
    assert guest.is_guest
    assert guest.is_active
    assert guest.removed_at is None


def test_user_participant_display_name_uses_name(owner):
    room = Room.objects.create(owner=owner)

    participant = Participant.objects.create(room=room, user=owner)

    assert participant.display_name == owner.name
    assert not participant.is_guest


def test_remove_is_idempotent(owner):
    room = Room.objects.create(owner=owner)
    participant = Participant.objects.create(room=room, guest_name="Гость")

    participant.remove()
    removed_at = participant.removed_at
    participant.remove()
    participant.refresh_from_db()

    assert removed_at is not None
    assert participant.removed_at == removed_at
    assert not participant.is_active


def test_two_guests_in_one_room(owner):
    room = Room.objects.create(owner=owner)

    Participant.objects.create(room=room, guest_name="Первый", session_key="s1")
    Participant.objects.create(room=room, guest_name="Второй", session_key="s2")

    assert room.participants.count() == 2
