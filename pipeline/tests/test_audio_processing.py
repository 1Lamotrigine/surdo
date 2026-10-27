"""F6: аудиофраза распознаётся в фоне и идёт общим путём глосс/сохранения."""

from __future__ import annotations

import asyncio
from time import perf_counter

import pytest
from django.test import override_settings
from django.utils import timezone

from pipeline import queue as queue_module
from pipeline.models import Utterance
from pipeline.queue import PipelineQueue
from rooms.models import Room
from services.asr import (
    AsrError,
    AsrResult,
    reset_asr_service,
    set_asr_provider,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )


@pytest.fixture
def room(owner):
    return Room.objects.create(owner=owner, lang=Room.Language.RU)


@override_settings(ASR_TIMEOUT=20, LLM_PROVIDER="", LLM_MODEL="", LLM_API_KEY="")
def test_audio_job_saves_asr_ms_and_broadcasts_text_before_utterance(
    room, monkeypatch, tmp_path
):
    calls: list[tuple[bytes, str, float | None]] = []
    events: list[tuple] = []

    async def fake_transcribe(audio, lang, *, timeout=None):
        calls.append((audio, lang, timeout))
        await asyncio.sleep(0.05)
        return AsrResult(text="  Учебник   Иванов ", duration_ms=1_200, language=lang)

    monkeypatch.setattr(queue_module, "transcribe_async", fake_transcribe)
    monkeypatch.setattr(
        queue_module,
        "broadcast_asr_text",
        lambda room_id, text: events.append(("asr_text", room_id, text)),
    )
    monkeypatch.setattr(
        queue_module,
        "broadcast_utterance",
        lambda utterance: events.append(("utterance", utterance.seq)),
    )
    started = perf_counter()
    started_at = timezone.now()
    queue = PipelineQueue(max_concurrency=1)

    with override_settings(MEDIA_ROOT=tmp_path):
        try:
            future = queue.submit_audio(room.pk, b"RIFF-audio", started_at=started_at)
            utterance = future.result(timeout=10)
        finally:
            queue.close()

    elapsed = perf_counter() - started
    assert calls == [(b"RIFF-audio", "ru", 20.0)]
    assert utterance.text == "Учебник Иванов"
    assert utterance.room_id == room.pk
    assert utterance.asr_ms is not None
    assert 0 <= utterance.asr_ms <= round(elapsed * 1000)
    assert utterance.started_at == started_at
    assert utterance.glosses["text"] == "Учебник Иванов"
    assert utterance.degraded is True  # LLM не настроена → запасной режим F2
    assert Utterance.objects.filter(room=room).count() == 1
    assert events == [
        ("asr_text", room.pk, "Учебник Иванов"),
        ("utterance", utterance.seq),
    ]
    # Аудио живёт только в памяти: после обработки медиа-файлов нет.
    assert list(tmp_path.rglob("*")) == []


@override_settings(ASR_TIMEOUT=20, LLM_PROVIDER="", LLM_MODEL="", LLM_API_KEY="")
def test_kazakh_room_passes_kk_to_asr_and_ksl_to_glosses(owner, monkeypatch):
    room = Room.objects.create(owner=owner, lang=Room.Language.KK)
    languages: list[str] = []

    async def fake_transcribe(audio, lang, *, timeout=None):
        languages.append(lang)
        return AsrResult(text="Сәлем", duration_ms=500, language=lang)

    monkeypatch.setattr(queue_module, "transcribe_async", fake_transcribe)
    queue = PipelineQueue(max_concurrency=1)
    try:
        utterance = queue.submit_audio(room.pk, b"RIFF").result(timeout=10)
    finally:
        queue.close()

    assert languages == ["kk"]
    assert utterance.glosses["lang"] == "ksl"


@override_settings(ASR_TIMEOUT=20, LLM_PROVIDER="", LLM_MODEL="", LLM_API_KEY="")
def test_empty_asr_text_skips_utterance_and_events(room, monkeypatch):
    events: list[tuple] = []

    async def fake_transcribe(audio, lang, *, timeout=None):
        return AsrResult(text="   ", duration_ms=500, language=lang)

    monkeypatch.setattr(queue_module, "transcribe_async", fake_transcribe)
    monkeypatch.setattr(
        queue_module,
        "broadcast_asr_text",
        lambda room_id, text: events.append(("asr_text", room_id, text)),
    )
    monkeypatch.setattr(
        queue_module,
        "broadcast_utterance",
        lambda utterance: events.append(("utterance", utterance.seq)),
    )
    queue = PipelineQueue(max_concurrency=1)
    try:
        result = queue.submit_audio(room.pk, b"RIFF").result(timeout=10)
    finally:
        queue.close()

    assert result is None
    assert events == []
    assert Utterance.objects.filter(room=room).count() == 0


@override_settings(ASR_TIMEOUT=20, LLM_PROVIDER="", LLM_MODEL="", LLM_API_KEY="")
def test_asr_error_does_not_stop_room_worker(room, monkeypatch):
    calls = 0

    async def fake_transcribe(audio, lang, *, timeout=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AsrError("модель недоступна")
        return AsrResult(text="Вторая фраза", duration_ms=500, language=lang)

    monkeypatch.setattr(queue_module, "transcribe_async", fake_transcribe)
    queue = PipelineQueue(max_concurrency=1)
    try:
        first = queue.submit_audio(room.pk, b"first")
        second = queue.submit_audio(room.pk, b"second")
        with pytest.raises(AsrError, match="недоступна"):
            first.result(timeout=10)
        utterance = second.result(timeout=10)
    finally:
        queue.close()

    assert calls == 2
    assert utterance.text == "Вторая фраза"
    assert Utterance.objects.filter(room=room).count() == 1


@override_settings(ASR_TIMEOUT=20, LLM_PROVIDER="", LLM_MODEL="", LLM_API_KEY="")
def test_audio_job_uses_configured_asr_provider(room):
    calls: list[tuple[bytes, str]] = []

    class FakeProvider:
        def transcribe(self, audio: bytes, lang: str) -> AsrResult:
            calls.append((audio, lang))
            return AsrResult(text="Провайдер", duration_ms=500, language=lang)

    set_asr_provider(FakeProvider())
    queue = PipelineQueue(max_concurrency=1)
    try:
        utterance = queue.submit_audio(room.pk, b"RIFF-provider").result(timeout=10)
    finally:
        queue.close()
        reset_asr_service()

    assert calls == [(b"RIFF-provider", "ru")]
    assert utterance.text == "Провайдер"


def test_submit_audio_rejects_empty_payload():
    queue = PipelineQueue()
    try:
        with pytest.raises(ValueError, match="пустое"):
            queue.submit_audio(1, b"")
    finally:
        queue.close()
