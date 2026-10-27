"""F8: сжатие фразы в конвейере по последнему известному отставанию."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from pipeline.models import Utterance
from pipeline.queue import PipelineQueue
from rooms.models import Room
from services.gloss import DEFAULT_CACHE, set_default_provider

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


@pytest.fixture(autouse=True)
def clean_provider():
    DEFAULT_CACHE.clear()
    set_default_provider(None)
    yield
    set_default_provider(None)
    DEFAULT_CACHE.clear()


def add_previous_lag(room: Room, lag_ms: int) -> Utterance:
    return Utterance.objects.create(
        room=room,
        seq=1,
        text="Предыдущая фраза",
        display_lag_ms=lag_ms,
        started_at=timezone.now() - timedelta(seconds=lag_ms / 1000),
    )


def run_queue(room: Room, text: str) -> Utterance:
    queue = PipelineQueue(max_concurrency=1)
    try:
        return queue.submit(room.pk, text).result(timeout=5)
    finally:
        queue.close()


LONG_PHRASE = (
    "Итак, как вы знаете, ребята, сегодня мы подробно разбираем новую тему "
    "и открываем учебник на странице десять"
)


@override_settings(LLM_PROVIDER="", LLM_MODEL="", LLM_API_KEY="")
def test_red_lag_compresses_phrase_and_skips_pauses(room):
    add_previous_lag(room, 12_000)

    utterance = run_queue(room, LONG_PHRASE)

    saved = Utterance.objects.get(pk=utterance.pk)
    assert saved.text != LONG_PHRASE
    assert len(saved.text) < len(LONG_PHRASE)
    assert saved.glosses["text"] == saved.text
    assert saved.playback["level"] == "red"
    assert saved.playback["compressed"] is True
    assert saved.playback["speed"] == 1.3
    assert saved.playback["gap_ms"] == 0


@override_settings(LLM_PROVIDER="", LLM_MODEL="", LLM_API_KEY="")
def test_green_lag_keeps_phrase_and_normal_pauses(room):
    add_previous_lag(room, 2_000)

    utterance = run_queue(room, LONG_PHRASE)

    saved = Utterance.objects.get(pk=utterance.pk)
    assert saved.text == " ".join(LONG_PHRASE.split())
    assert saved.playback["level"] == "green"
    assert saved.playback["compressed"] is False
    assert saved.playback["speed"] is None
    assert saved.playback["gap_ms"] == 120


@override_settings(LLM_PROVIDER="", LLM_MODEL="", LLM_API_KEY="")
def test_yellow_lag_uses_intermediate_policy(room):
    add_previous_lag(room, 7_000)

    utterance = run_queue(room, LONG_PHRASE)

    saved = Utterance.objects.get(pk=utterance.pk)
    assert saved.playback["level"] == "yellow"
    assert saved.playback["speed"] == 1.15
    assert saved.playback["compressed"] is True
    assert len(saved.text) < len(LONG_PHRASE)


@override_settings(LLM_PROVIDER="", LLM_MODEL="", LLM_API_KEY="")
def test_latest_lag_of_other_room_does_not_leak(room, owner):
    other_room = Room.objects.create(owner=owner)
    add_previous_lag(other_room, 12_000)

    utterance = run_queue(room, LONG_PHRASE)

    assert utterance.playback["level"] == "green"
    assert utterance.text == " ".join(LONG_PHRASE.split())
