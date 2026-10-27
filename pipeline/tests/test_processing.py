"""Фоновая обработка фразы (E2): задание создаёт Utterance вне запроса."""

import pytest
from django.db import connection
from django.utils import timezone

from pipeline import queue as queue_module
from pipeline.models import Utterance
from pipeline.queue import PipelineQueue, process_text_job
from rooms.models import Room


@pytest.mark.django_db(transaction=True)
def test_background_job_saves_utterance(django_user_model):
    owner = django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )
    room = Room.objects.create(owner=owner)
    started_at = timezone.now()

    def processor(job):
        # Закрываем соединение в потоке обработчика, чтобы тестовая база не
        # осталась занятой после завершения теста.
        try:
            return process_text_job(job)
        finally:
            connection.close()

    queue = PipelineQueue(processor=processor, max_concurrency=1)

    try:
        future = queue.submit(room.pk, "Учебник Иванов", started_at=started_at)
        utterance = future.result(timeout=10)
    finally:
        queue.close()

    assert utterance.pk is not None
    assert utterance.room_id == room.pk
    assert utterance.seq == 1
    assert utterance.text == "Учебник Иванов"
    assert utterance.started_at == started_at
    assert [token["type"] for token in utterance.glosses["tokens"]] == [
        "fingerspell",
        "fingerspell",
    ]
    assert Utterance.objects.filter(room=room).count() == 1


@pytest.mark.django_db(transaction=True)
def test_processing_broadcasts_text_before_utterance(monkeypatch, django_user_model):
    owner = django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )
    room = Room.objects.create(owner=owner)
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        queue_module,
        "broadcast_asr_text",
        lambda room_id, text: calls.append(("asr_text", (room_id, text))),
    )
    monkeypatch.setattr(
        queue_module,
        "broadcast_utterance",
        lambda utterance: calls.append(("utterance", utterance.seq)),
    )

    def processor(job):
        try:
            return process_text_job(job)
        finally:
            connection.close()

    pipeline = PipelineQueue(processor=processor, max_concurrency=1)
    try:
        future = pipeline.submit(room.pk, "Учебник")
        utterance = future.result(timeout=10)
    finally:
        pipeline.close()

    assert calls == [
        ("asr_text", (room.pk, "Учебник")),
        ("utterance", utterance.seq),
    ]
