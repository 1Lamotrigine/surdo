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


def test_teacher_live_page_shows_chat_and_presence(client, owner):
    room = Room.objects.create(owner=owner, join_code="LIVE01")
    client.force_login(owner)

    response = client.get(reverse("rooms:live", kwargs={"join_code": room.join_code}))
    html = response.content.decode()

    assert response.status_code == 200
    assert 'data-room-live' in html
    assert f'data-join-code="{room.join_code}"' in html
    assert "data-chat-log" in html
    assert "data-chat-form" in html
    assert "data-presence-list" in html


def test_detail_shows_management_actions(client, owner):
    room = Room.objects.create(owner=owner, join_code="MANAGE")
    client.force_login(owner)

    html = client.get(
        reverse("rooms:detail", kwargs={"join_code": room.join_code})
    ).content.decode()

    assert "Сменить ID" in html
    assert "Закрыть комнату" in html
    assert reverse("rooms:close", kwargs={"join_code": room.join_code}) in html
    assert reverse("rooms:rotate-code", kwargs={"join_code": room.join_code}) in html


def test_live_page_marks_teacher_view_and_remove_url(client, owner):
    room = Room.objects.create(owner=owner, join_code="LIVE04")
    client.force_login(owner)

    html = client.get(reverse("rooms:live", kwargs={"join_code": room.join_code})).content.decode()

    assert "data-teacher-view" in html
    assert "data-remove-participant-url" in html
    assert f"/rooms/{room.join_code}/participants/0/remove/" in html
    assert "data-csrf-token" in html


def test_closed_room_detail_hides_management_actions(client, owner):
    room = Room.objects.create(owner=owner, join_code="CLOSED")
    room.close()
    client.force_login(owner)

    html = client.get(
        reverse("rooms:detail", kwargs={"join_code": room.join_code})
    ).content.decode()

    assert "Сменить ID" not in html
    assert "Закрыть комнату" not in html


def test_teacher_live_rejects_other_teacher(client, owner, other_teacher):
    room = Room.objects.create(owner=owner, join_code="LIVE02")
    client.force_login(other_teacher)

    response = client.get(reverse("rooms:live", kwargs={"join_code": room.join_code}))

    assert response.status_code == 403


def test_teacher_live_requires_login(client, owner):
    room = Room.objects.create(owner=owner, join_code="LIVE03")

    response = client.get(reverse("rooms:live", kwargs={"join_code": room.join_code}))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url
