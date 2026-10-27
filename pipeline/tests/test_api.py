"""HTTP-приём текста E2: права, ответ 202 и фоновая обработка."""

import json
import threading

import pytest
from django.urls import reverse

from pipeline import api
from pipeline.models import Utterance
from pipeline.queue import PipelineQueue
from rooms.models import Room

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )


@pytest.fixture
def other_teacher(django_user_model):
    return django_user_model.objects.create_user(
        email="other@example.com",
        password="StrongPass-12345",
        name="Другой преподаватель",
    )


@pytest.fixture
def admin_user(django_user_model):
    return django_user_model.objects.create_superuser(
        email="admin@example.com",
        password="StrongPass-12345",
        name="Администратор",
    )


@pytest.fixture
def room(owner):
    return Room.objects.create(owner=owner)


def _url(room: Room) -> str:
    return reverse("api-room-text", kwargs={"join_code": room.join_code})


def _post_text(client, room: Room, text: str):
    return client.post(
        _url(room),
        data=json.dumps({"text": text}),
        content_type="application/json",
    )


def test_anonymous_cannot_send_text(client, room):
    response = _post_text(client, room, "Учебник")

    assert response.status_code == 401


def test_other_teacher_cannot_send_text(client, room, other_teacher):
    client.force_login(other_teacher)

    response = _post_text(client, room, "Учебник")

    assert response.status_code == 403


def test_room_owner_gets_202_and_text_is_queued(client, room, owner, monkeypatch):
    calls = []
    monkeypatch.setattr(
        api,
        "submit_text",
        lambda room_id, text, **kwargs: calls.append((room_id, text, kwargs)),
    )
    client.force_login(owner)

    response = _post_text(client, room, "  Учебник   Иванов ")

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert len(calls) == 1
    room_id, text, kwargs = calls[0]
    assert room_id == room.pk
    assert text == "Учебник Иванов"
    assert kwargs["started_at"] is not None
    # Запрос только ставит фразу в очередь, сам он ничего не сохраняет.
    assert Utterance.objects.count() == 0


def test_admin_can_send_text(client, room, admin_user, monkeypatch):
    called = []
    monkeypatch.setattr(api, "submit_text", lambda *args, **kwargs: called.append(True))
    client.force_login(admin_user)

    response = _post_text(client, room, "Учебник")

    assert response.status_code == 202
    assert called == [True]


def test_form_payload_is_accepted(client, room, owner, monkeypatch):
    calls = []
    monkeypatch.setattr(api, "submit_text", lambda room_id, text, **kwargs: calls.append(text))
    client.force_login(owner)

    response = client.post(_url(room), {"text": "Учебник"})

    assert response.status_code == 202
    assert calls == ["Учебник"]


def test_empty_text_is_rejected_without_queueing(client, room, owner, monkeypatch):
    called = []
    monkeypatch.setattr(api, "submit_text", lambda *args, **kwargs: called.append(True))
    client.force_login(owner)

    response = _post_text(client, room, "   ")

    assert response.status_code == 400
    assert called == []


def test_missing_text_is_rejected(client, room, owner):
    client.force_login(owner)

    response = client.post(
        _url(room),
        data=json.dumps({}),
        content_type="application/json",
    )

    assert response.status_code == 400


def test_too_long_text_is_rejected(client, room, owner):
    client.force_login(owner)

    response = _post_text(client, room, "а" * 2001)

    assert response.status_code == 400


def test_invalid_json_is_rejected(client, room, owner):
    client.force_login(owner)

    response = client.post(_url(room), data="{", content_type="application/json")

    assert response.status_code == 400


def test_closed_and_unknown_rooms_return_404(client, owner):
    closed = Room.objects.create(owner=owner, status=Room.Status.CLOSED)
    client.force_login(owner)

    assert _post_text(client, closed, "Учебник").status_code == 404
    assert (
        client.post(
            reverse("api-room-text", kwargs={"join_code": "ZZZZZZ"}),
            data=json.dumps({"text": "Учебник"}),
            content_type="application/json",
        ).status_code
        == 404
    )


def test_request_does_not_wait_for_background_processing(client, room, owner, monkeypatch):
    """Ответ приходит, пока обработчик ещё заблокирован (запрос не блокирует)."""
    started = threading.Event()
    release = threading.Event()

    def processor(job):
        started.set()
        release.wait(timeout=5)
        return job.text

    queue = PipelineQueue(processor=processor, max_concurrency=1)
    monkeypatch.setattr(
        api,
        "submit_text",
        lambda room_id, text, **kwargs: queue.submit(room_id, text, **kwargs),
    )
    client.force_login(owner)

    try:
        response = _post_text(client, room, "Учебник")

        assert response.status_code == 202
        assert started.wait(timeout=5)
        assert not release.is_set()
    finally:
        release.set()
        queue.wait_for_idle(timeout=5)
        queue.close()
