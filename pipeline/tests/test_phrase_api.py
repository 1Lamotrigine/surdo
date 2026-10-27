"""F6: HTTP-приём аудиофразы — права, 202, память и фоновая очередь."""

from __future__ import annotations

import io
import threading
import wave

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from pipeline import api
from pipeline.models import Utterance
from pipeline.queue import PipelineQueue
from rooms.models import Room

pytestmark = pytest.mark.django_db


def short_wav(duration_ms: int = 120, framerate: int = 16_000) -> bytes:
    frames = round(framerate * duration_ms / 1000)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(framerate)
        writer.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


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
    return reverse("api-room-phrase", kwargs={"join_code": room.join_code})


def _upload(
    content: bytes | None = None,
    *,
    name: str = "phrase.wav",
    content_type: str = "audio/wav",
):
    if content is None:
        content = short_wav()
    return SimpleUploadedFile(name, content, content_type=content_type)


def _post_phrase(
    client,
    room: Room,
    *,
    content: bytes | None = None,
    name: str = "phrase.wav",
    content_type: str = "audio/wav",
    field: str = "audio",
):
    uploaded = _upload(
        content if content is not None else short_wav(),
        name=name,
        content_type=content_type,
    )
    return client.post(_url(room), {field: uploaded})


def test_anonymous_cannot_send_phrase(client, room):
    response = _post_phrase(client, room)

    assert response.status_code == 401


def test_other_teacher_cannot_send_phrase(client, room, other_teacher):
    client.force_login(other_teacher)

    response = _post_phrase(client, room)

    assert response.status_code == 403


def test_room_owner_gets_202_and_audio_is_queued(
    client, room, owner, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        api,
        "submit_audio",
        lambda room_id, audio, **kwargs: calls.append((room_id, audio, kwargs)),
    )
    client.force_login(owner)
    wav = short_wav()

    with override_settings(MEDIA_ROOT=tmp_path):
        response = _post_phrase(client, room, content=wav)

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert len(calls) == 1
    room_id, audio, kwargs = calls[0]
    assert room_id == room.pk
    assert audio == wav
    assert kwargs["started_at"] is not None
    # Запрос только ставит задание в очередь и не пишет ни БД, ни медиа.
    assert Utterance.objects.count() == 0
    assert list(tmp_path.rglob("*")) == []


def test_admin_can_send_phrase(client, room, admin_user, monkeypatch):
    called = []
    monkeypatch.setattr(api, "submit_audio", lambda *args, **kwargs: called.append(True))
    client.force_login(admin_user)

    response = _post_phrase(client, room)

    assert response.status_code == 202
    assert called == [True]


def test_file_field_is_accepted_for_compatibility(client, room, owner, monkeypatch):
    calls = []
    monkeypatch.setattr(api, "submit_audio", lambda room_id, audio, **kw: calls.append(audio))
    client.force_login(owner)

    response = _post_phrase(client, room, field="file")

    assert response.status_code == 202
    assert len(calls) == 1


def test_missing_audio_is_rejected(client, room, owner, monkeypatch):
    called = []
    monkeypatch.setattr(api, "submit_audio", lambda *args, **kwargs: called.append(True))
    client.force_login(owner)

    response = client.post(_url(room), {})

    assert response.status_code == 400
    assert called == []


def test_empty_audio_is_rejected(client, room, owner, monkeypatch):
    called = []
    monkeypatch.setattr(api, "submit_audio", lambda *args, **kwargs: called.append(True))
    client.force_login(owner)

    response = _post_phrase(client, room, content=b"")

    assert response.status_code == 400
    assert called == []


def test_non_audio_file_is_rejected(client, room, owner, monkeypatch):
    called = []
    monkeypatch.setattr(api, "submit_audio", lambda *args, **kwargs: called.append(True))
    client.force_login(owner)

    response = _post_phrase(
        client,
        room,
        content=b"not audio",
        name="notes.txt",
        content_type="text/plain",
    )

    assert response.status_code == 400
    assert called == []


def test_too_large_audio_is_rejected(client, room, owner, monkeypatch):
    called = []
    monkeypatch.setattr(api, "submit_audio", lambda *args, **kwargs: called.append(True))
    monkeypatch.setattr(api, "MAX_PHRASE_AUDIO_BYTES", 16)
    client.force_login(owner)

    response = _post_phrase(client, room, content=b"x" * 17)

    assert response.status_code == 413
    assert called == []


def test_closed_and_unknown_rooms_return_404(client, owner):
    closed = Room.objects.create(owner=owner, status=Room.Status.CLOSED)
    client.force_login(owner)

    assert _post_phrase(client, closed).status_code == 404
    assert (
        client.post(
            reverse("api-room-phrase", kwargs={"join_code": "ZZZZZZ"}),
            {"audio": _upload()},
        ).status_code
        == 404
    )


def test_request_does_not_wait_for_background_processing(client, room, owner, monkeypatch):
    """202 приходит, пока обработчик аудио ещё заблокирован."""
    started = threading.Event()
    release = threading.Event()

    def processor(job):
        started.set()
        release.wait(timeout=5)
        return len(job.audio)

    queue = PipelineQueue(processor=processor, max_concurrency=1)
    monkeypatch.setattr(
        api,
        "submit_audio",
        lambda room_id, audio, **kwargs: queue.submit_audio(
            room_id, audio, **kwargs
        ),
    )
    client.force_login(owner)

    try:
        response = _post_phrase(client, room)

        assert response.status_code == 202
        assert started.wait(timeout=5)
        assert not release.is_set()
    finally:
        release.set()
        queue.wait_for_idle(timeout=5)
        queue.close()
