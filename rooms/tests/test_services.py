"""Создание комнат через сервисную функцию."""

from unittest.mock import patch

import pytest

from rooms.models import Room
from rooms.services import JoinCodeGenerationError, create_room, recent_utterances

pytestmark = pytest.mark.django_db


def test_create_room_sets_values_and_unique_code(owner):
    room = create_room(
        owner=owner,
        title="Лекция",
        lang=Room.Language.RU,
        demo_mode=True,
    )

    assert room.owner == owner
    assert room.title == "Лекция"
    assert room.demo_mode is True
    assert room.is_open
    assert len(room.join_code) == 6


def test_create_room_retries_when_code_is_taken(owner):
    Room.objects.create(owner=owner, join_code="AAAAAA")

    with patch(
        "rooms.services.generate_join_code",
        side_effect=("AAAAAA", "BBBBBB"),
    ):
        room = create_room(owner=owner)

    assert room.join_code == "BBBBBB"


def test_create_room_fails_after_too_many_collisions(owner):
    Room.objects.create(owner=owner, join_code="AAAAAA")

    with (
        patch("rooms.services.generate_join_code", return_value="AAAAAA"),
        pytest.raises(JoinCodeGenerationError),
    ):
        create_room(owner=owner)


def test_open_rooms_have_unique_codes(owner):
    codes = {create_room(owner=owner).join_code for _ in range(30)}

    assert len(codes) == 30


def test_recent_utterances_is_empty_until_block_e(owner):
    """Фразы появятся на B1/E1; пока endpoint отдаёт пустой список."""
    room = Room.objects.create(owner=owner)

    assert recent_utterances(room) == []
    assert recent_utterances(room, after_seq=3) == []
