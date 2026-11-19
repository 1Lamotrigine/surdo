"""Страницы комнаты: создание, QR и доступ."""

import re

import pytest
from django.urls import reverse
from django.utils import timezone

from pipeline.models import Utterance
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


def test_teacher_live_page_shows_avatar_stage_and_model(client, owner, settings):
    """Преподаватель видит ту же сцену аватара, что и студент (E3)."""
    settings.AVATAR_MODEL_URL = "/media/avatar/surd.vrm"
    room = Room.objects.create(owner=owner, join_code="LIVE05")
    client.force_login(owner)

    html = client.get(reverse("rooms:live", kwargs={"join_code": room.join_code})).content.decode()

    assert "data-room-avatar-stage" in html
    assert "data-room-subtitles" in html
    assert "data-room-phrase-status" in html
    assert 'data-avatar-model-url="/media/avatar/surd.vrm"' in html


def test_teacher_phrase_feed_sits_right_under_avatar(client, owner, settings):
    """Лента фраз идёт сразу под аватаром: видно и жест, и текст (E5)."""
    settings.AVATAR_MODEL_URL = "/media/avatar/surd.vrm"
    room = Room.objects.create(owner=owner, join_code="LIVE06")
    client.force_login(owner)

    html = client.get(reverse("rooms:live", kwargs={"join_code": room.join_code})).content.decode()

    avatar = html.index("data-room-avatar-stage")
    feed = html.index("data-phrase-feed")
    presence = html.index("data-presence-list")
    # Сцена аватара, затем сразу лента фраз, и уже потом участники комнаты.
    assert avatar < feed < presence
    # Панели «Отставание аватара» и «Слова без жеста» из панели убраны.
    assert "data-lag-panel" not in html
    assert "data-unknown-words" not in html


def test_teacher_chat_lives_in_main_column(client, owner):
    """Чат — в левой колонке с формой: писать не пролистывая страницу."""
    room = Room.objects.create(owner=owner, join_code="LIVE07")
    client.force_login(owner)

    html = client.get(reverse("rooms:live", kwargs={"join_code": room.join_code})).content.decode()

    # Чат идёт после формы фразы, но до сцены аватара: на узком экране (одна
    # колонка) он оказывается выше аватара и ленты, писать не пролистывая.
    chat = html.index("data-chat-log")
    assert html.index('name="text"') < chat
    assert chat < html.index("data-room-avatar-stage")
    assert chat < html.index("data-phrase-feed")


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


def test_teacher_live_shows_phrase_form_and_feed(client, owner):
    room = Room.objects.create(owner=owner, join_code="LIVE05")
    Utterance.objects.create(
        room=room,
        seq=1,
        text="Откройте учебник Иванов",
        glosses={"unknown": ["Иванов"]},
        started_at=timezone.now(),
    )
    client.force_login(owner)

    response = client.get(reverse("rooms:live", kwargs={"join_code": room.join_code}))
    html = response.content.decode()

    assert response.status_code == 200
    assert 'name="text"' in html
    assert "data-phrase-feed" in html
    assert reverse("rooms:live-feed", kwargs={"join_code": room.join_code}) in html
    assert "Откройте учебник Иванов" in html
    assert "Иванов" in html
    assert "Фраза для показа студентам" in html
    assert "data-microphone" in html
    assert "data-mic-toggle" in html
    assert reverse("api-room-phrase", kwargs={"join_code": room.join_code}) in html


def test_teacher_live_disables_microphone_for_closed_room(client, owner):
    room = Room.objects.create(owner=owner, join_code="LIVE06")
    room.close()
    client.force_login(owner)

    response = client.get(reverse("rooms:live", kwargs={"join_code": room.join_code}))
    html = response.content.decode()

    assert response.status_code == 200
    assert "data-microphone" in html
    assert "Комната закрыта: микрофон недоступен." in html
    button = re.search(r"<button[^>]*data-mic-toggle[^>]*>", html)
    assert button is not None
    assert "disabled" in button.group(0)


def test_phrase_feed_returns_latest_room_phrases(client, owner):
    room = Room.objects.create(owner=owner, join_code="FEED01")
    other = Room.objects.create(owner=owner, join_code="FEED02")
    for seq in (1, 2, 3):
        Utterance.objects.create(
            room=room,
            seq=seq,
            text=f"Фраза {seq}",
            started_at=timezone.now(),
        )
    Utterance.objects.create(
        room=other,
        seq=1,
        text="Чужая фраза",
        started_at=timezone.now(),
    )
    client.force_login(owner)

    response = client.get(reverse("rooms:live-feed", kwargs={"join_code": room.join_code}))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Фраза 1" in html
    assert "Фраза 2" in html
    assert "Фраза 3" in html
    assert "Чужая фраза" not in html
    # Свежие фразы сверху: последняя сказанная идёт первой в ленте.
    assert html.index("Фраза 3") < html.index("Фраза 1")


def test_phrase_form_htmx_queues_text_and_returns_fragment(client, owner, monkeypatch):
    room = Room.objects.create(owner=owner, join_code="FORM01")
    calls = []
    monkeypatch.setattr(
        "rooms.views.submit_text",
        lambda room_id, text, **kwargs: calls.append((room_id, text, kwargs)),
    )
    client.force_login(owner)

    response = client.post(
        reverse("rooms:live-phrase", kwargs={"join_code": room.join_code}),
        {"text": "  Учебник   Иванов "},
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()

    assert response.status_code == 200
    assert response["HX-Trigger"] == "phrase-saved"
    assert len(calls) == 1
    room_id, text, kwargs = calls[0]
    assert room_id == room.pk
    assert text == "Учебник Иванов"
    assert kwargs["started_at"] is not None
    assert "Фраза поставлена в очередь." in html
    assert "Учебник Иванов" not in html
    phrase_url = reverse("rooms:live-phrase", kwargs={"join_code": room.join_code})
    assert f'hx-post="{phrase_url}"' in html


def test_phrase_form_rejects_empty_text_and_keeps_input(client, owner, monkeypatch):
    room = Room.objects.create(owner=owner, join_code="FORM02")
    called = []
    monkeypatch.setattr("rooms.views.submit_text", lambda *args, **kwargs: called.append(True))
    client.force_login(owner)

    response = client.post(
        reverse("rooms:live-phrase", kwargs={"join_code": room.join_code}),
        {"text": "   "},
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()

    assert response.status_code == 200
    assert "HX-Trigger" not in response
    assert "не может быть пустой" in html
    assert called == []


def test_phrase_form_rejects_closed_room(client, owner, monkeypatch):
    room = Room.objects.create(owner=owner, join_code="FORM03")
    room.close()
    called = []
    monkeypatch.setattr("rooms.views.submit_text", lambda *args, **kwargs: called.append(True))
    client.force_login(owner)

    response = client.post(
        reverse("rooms:live-phrase", kwargs={"join_code": room.join_code}),
        {"text": "Учебник"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert "Комната закрыта" in response.content.decode()
    assert called == []


def test_phrase_form_without_htmx_redirects_with_message(client, owner, monkeypatch):
    room = Room.objects.create(owner=owner, join_code="FORM04")
    monkeypatch.setattr("rooms.views.submit_text", lambda *args, **kwargs: None)
    client.force_login(owner)

    response = client.post(
        reverse("rooms:live-phrase", kwargs={"join_code": room.join_code}),
        {"text": "Учебник"},
        follow=True,
    )

    assert response.status_code == 200
    assert "Фраза поставлена в очередь." in response.content.decode()


def test_phrase_form_and_feed_reject_other_teacher(client, owner, other_teacher):
    room = Room.objects.create(owner=owner, join_code="FORM05")
    client.force_login(other_teacher)

    phrase = client.post(
        reverse("rooms:live-phrase", kwargs={"join_code": room.join_code}),
        {"text": "Учебник"},
    )
    feed = client.get(reverse("rooms:live-feed", kwargs={"join_code": room.join_code}))

    assert phrase.status_code == 403
    assert feed.status_code == 403
