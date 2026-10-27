"""Модель Message и сервисные функции чата."""

import pytest

from rooms.models import Message, Room
from rooms.services import (
    MAX_MESSAGE_LENGTH,
    ChatValidationError,
    clean_message_body,
    post_message,
    recent_messages,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def room(owner):
    return Room.objects.create(owner=owner, join_code="CHAT01")


def test_message_as_event(room):
    message = Message.objects.create(room=room, author_name="Айгуль", body="Привет")

    event = message.as_event()

    assert event["id"] == message.pk
    assert event["user"] == "Айгуль"
    assert event["body"] == "Привет"
    assert event["is_teacher"] is False
    assert "ts" in event


def test_clean_message_body_normalizes_whitespace():
    assert clean_message_body("  привет \n мир  ") == "привет мир"


def test_clean_message_body_rejects_empty():
    with pytest.raises(ChatValidationError):
        clean_message_body("   ")


def test_clean_message_body_rejects_too_long():
    with pytest.raises(ChatValidationError):
        clean_message_body("a" * (MAX_MESSAGE_LENGTH + 1))


def test_post_message_stores_author_and_teacher_flag(room):
    message = post_message(
        room_id=room.pk,
        participant_id=None,
        author_name="Преподаватель",
        body="Ответ",
        is_teacher=True,
    )

    assert message.room == room
    assert message.author_name == "Преподаватель"
    assert message.is_teacher is True


def test_recent_messages_returns_last_in_order(room):
    for index in range(5):
        Message.objects.create(room=room, author_name="Гость", body=f"msg {index}")

    messages = recent_messages(room, limit=3)

    assert [m.body for m in messages] == ["msg 2", "msg 3", "msg 4"]


def test_recent_messages_after_id_returns_only_new(room):
    first = Message.objects.create(room=room, author_name="Гость", body="one")
    Message.objects.create(room=room, author_name="Гость", body="two")
    Message.objects.create(room=room, author_name="Гость", body="three")

    messages = recent_messages(room, after_id=first.pk)

    assert [m.body for m in messages] == ["two", "three"]


def test_messages_are_isolated_between_rooms(owner, room):
    other = Room.objects.create(owner=owner, join_code="CHAT02")
    Message.objects.create(room=room, author_name="A", body="в первой")
    Message.objects.create(room=other, author_name="B", body="во второй")

    assert [m.body for m in recent_messages(room)] == ["в первой"]
    assert [m.body for m in recent_messages(other)] == ["во второй"]
