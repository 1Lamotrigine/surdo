"""Вход студента: главная, ввод имени, гостевая сессия, ошибки."""

import pytest
from django.core.cache import cache
from django.urls import reverse

from rooms.models import Participant, Room

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


OPEN_ROOM_CODE = "ABC234"


@pytest.fixture
def open_room(owner):
    return Room.objects.create(owner=owner, title="Алгебра", join_code=OPEN_ROOM_CODE)


def test_home_posts_join_code_and_redirects(client, open_room):
    response = client.post(reverse("home"), {"join_code": "abc234"})

    assert response.status_code == 302
    assert response.url == reverse("room_student:join", kwargs={"join_code": OPEN_ROOM_CODE})


def test_home_shows_error_for_short_code(client):
    response = client.post(reverse("home"), {"join_code": "AB"})

    assert response.status_code == 400
    assert "6 символов" in response.content.decode()


def test_join_page_asks_for_name(client, open_room):
    response = client.get(reverse("room_student:join", kwargs={"join_code": OPEN_ROOM_CODE}))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Вход без регистрации" in html
    assert open_room.title in html


def test_guest_join_creates_participant_and_session(client, open_room):
    response = client.post(
        reverse("room_student:join", kwargs={"join_code": OPEN_ROOM_CODE}),
        {"name": "  Айгуль   Сериковна "},
    )

    assert response.status_code == 302
    assert response.url == reverse("room_student:live", kwargs={"join_code": OPEN_ROOM_CODE})
    participant = Participant.objects.get(room=open_room)
    assert participant.guest_name == "Айгуль Сериковна"
    assert participant.session_key
    assert participant.is_active
    assert client.session["rooms"][OPEN_ROOM_CODE]["name"] == "Айгуль Сериковна"


def test_unknown_code_returns_404(client):
    response = client.get(reverse("room_student:join", kwargs={"join_code": "ZZZZZZ"}))

    assert response.status_code == 404
    assert "Неверный ID" in response.content.decode()


def test_closed_room_returns_410(client, owner):
    room = Room.objects.create(owner=owner, join_code=OPEN_ROOM_CODE)
    room.close()

    response = client.get(reverse("room_student:join", kwargs={"join_code": OPEN_ROOM_CODE}))

    assert response.status_code == 410
    assert "Комната закрыта" in response.content.decode()


def test_rate_limit_blocks_brute_force(client, open_room, settings):
    settings.JOIN_RATE_LIMIT_ATTEMPTS = 2
    url = reverse("room_student:join", kwargs={"join_code": OPEN_ROOM_CODE})

    first = client.post(url, {"name": "Гость"})
    second = client.post(url, {"name": "Гость"})
    blocked = client.post(url, {"name": "Гость"})

    assert first.status_code == 302
    assert second.status_code == 302
    assert blocked.status_code == 429
    assert "Слишком много попыток" in blocked.content.decode()


def test_live_requires_guest_session(client, open_room):
    response = client.get(reverse("room_student:live", kwargs={"join_code": OPEN_ROOM_CODE}))

    assert response.status_code == 302
    assert response.url == reverse("room_student:join", kwargs={"join_code": OPEN_ROOM_CODE})


def test_live_shows_guest_after_join(client, open_room):
    client.post(
        reverse("room_student:join", kwargs={"join_code": OPEN_ROOM_CODE}),
        {"name": "Гость"},
    )

    response = client.get(reverse("room_student:live", kwargs={"join_code": OPEN_ROOM_CODE}))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Гость" in html
    assert open_room.title in html
    # Страница готовит WebSocket-клиент комнаты (A8).
    assert f'data-join-code="{OPEN_ROOM_CODE}"' in html
    assert "data-presence-list" in html
