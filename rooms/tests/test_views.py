"""Страницы комнаты: создание, QR и доступ."""

import pytest
from django.urls import reverse

from rooms.models import Room

pytestmark = pytest.mark.django_db


def test_create_page_requires_login(client):
    response = client.get(reverse("rooms:create"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_create_page_rejects_editor(client, editor):
    client.force_login(editor)

    assert client.get(reverse("rooms:create")).status_code == 403


def test_create_page_available_to_teacher(client, owner):
    client.force_login(owner)

    response = client.get(reverse("rooms:create"))

    assert response.status_code == 200
    assert "Создать комнату" in response.content.decode()


def test_teacher_creates_room_and_sees_qr(client, owner):
    client.force_login(owner)

    response = client.post(
        reverse("rooms:create"),
        {"title": "Алгебра", "demo_mode": "on"},
    )

    room = Room.objects.get()
    assert response.status_code == 302
    assert response.url == reverse("rooms:detail", kwargs={"join_code": room.join_code})

    page = client.get(response.url)
    html = page.content.decode()
    assert page.status_code == 200
    assert room.join_code in html
    assert "<svg" in html
    assert f"/r/{room.join_code}/" in html
    assert "Демо-режим" in html


def test_detail_rejects_other_teacher(client, owner, other_teacher):
    room = Room.objects.create(owner=owner)
    client.force_login(other_teacher)

    response = client.get(reverse("rooms:detail", kwargs={"join_code": room.join_code}))

    assert response.status_code == 403


def test_detail_allows_admin(client, owner, admin_user):
    room = Room.objects.create(owner=owner)
    client.force_login(admin_user)

    response = client.get(reverse("rooms:detail", kwargs={"join_code": room.join_code}))

    assert response.status_code == 200


def test_detail_unknown_code_is_404(client, owner):
    client.force_login(owner)

    response = client.get(reverse("rooms:detail", kwargs={"join_code": "ZZZZZZ"}))

    assert response.status_code == 404


def test_closed_room_hides_qr(client, owner):
    room = Room.objects.create(owner=owner)
    room.close()
    client.force_login(owner)

    response = client.get(reverse("rooms:detail", kwargs={"join_code": room.join_code}))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Комната закрыта" in html
    assert "<svg" not in html
