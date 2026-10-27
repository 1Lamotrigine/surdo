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
