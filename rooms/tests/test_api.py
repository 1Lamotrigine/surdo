"""JSON-эндпоинт создания комнаты."""

import json

import pytest
from django.urls import reverse

from rooms.models import Room

pytestmark = pytest.mark.django_db


def test_api_requires_authentication(client):
    response = client.post(reverse("api-room-create"), {"title": "Урок"})

    assert response.status_code == 401


def test_api_rejects_editor(client, editor):
    client.force_login(editor)

    response = client.post(reverse("api-room-create"), {"title": "Урок"})

    assert response.status_code == 403
    assert Room.objects.count() == 0


def test_api_creates_room_for_teacher(client, owner):
    client.force_login(owner)

    response = client.post(reverse("api-room-create"), {"title": "Физика"})

    assert response.status_code == 201
    data = response.json()
    room = Room.objects.get()
    assert data["join_code"] == room.join_code
    assert data["join_url"].endswith(f"/r/{room.join_code}/")
    assert data["id"] == room.pk


def test_api_accepts_json_body(client, owner):
    client.force_login(owner)

    response = client.post(
        reverse("api-room-create"),
        data=json.dumps({"title": "Химия", "demo_mode": True}),
        content_type="application/json",
    )

    assert response.status_code == 201
    assert Room.objects.filter(demo_mode=True).exists()


def test_api_validates_title(client, owner):
    client.force_login(owner)

    response = client.post(
        reverse("api-room-create"),
        data=json.dumps({"title": ""}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "title" in response.json()["errors"]


def test_history_requires_membership(client, owner, other_teacher):
    room = Room.objects.create(owner=owner, join_code="HIST01")
    client.force_login(other_teacher)

    response = client.get(reverse("api-room-history", kwargs={"join_code": room.join_code}))

    assert response.status_code == 403


def test_history_for_owner(client, owner):
    from rooms.models import Message

    room = Room.objects.create(owner=owner, join_code="HIST02")
    Message.objects.create(room=room, author_name="Гость", body="один")
    Message.objects.create(room=room, author_name="Гость", body="два")
    client.force_login(owner)

    response = client.get(reverse("api-room-history", kwargs={"join_code": room.join_code}))

    assert response.status_code == 200
    bodies = [m["body"] for m in response.json()["messages"]]
    assert bodies == ["один", "два"]


def test_history_after_message_id(client, owner):
    from rooms.models import Message

    room = Room.objects.create(owner=owner, join_code="HIST03")
    first = Message.objects.create(room=room, author_name="Гость", body="один")
    Message.objects.create(room=room, author_name="Гость", body="два")
    client.force_login(owner)

    response = client.get(
        reverse("api-room-history", kwargs={"join_code": room.join_code}),
        {"after_message_id": first.pk},
    )

    assert response.status_code == 200
    assert [m["body"] for m in response.json()["messages"]] == ["два"]


def test_history_available_to_guest_with_session(client, owner):
    from rooms.models import Message
    from rooms.services import GUEST_ROOMS_SESSION_KEY

    room = Room.objects.create(owner=owner, join_code="HIST04")
    Message.objects.create(room=room, author_name="Гость", body="вопрос")
    session = client.session
    # имитируем вход гостя: имя записано в сессию
    session[GUEST_ROOMS_SESSION_KEY] = {room.join_code: {"name": "Гость", "room_id": room.pk}}
    session.save()

    response = client.get(reverse("api-room-history", kwargs={"join_code": room.join_code}))

    assert response.status_code == 200
    assert [m["body"] for m in response.json()["messages"]] == ["вопрос"]
