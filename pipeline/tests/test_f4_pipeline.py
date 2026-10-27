"""F4: конвейер очереди использует LLM-глоссы, таймаут и упрощённый режим."""

from __future__ import annotations

import json
import threading
import time

import pytest
from django.test import override_settings

from dictionary.models import Language, Sign, SignStatus, UnknownWord
from pipeline.models import Utterance
from pipeline.queue import PipelineQueue
from rooms.models import Room
from services.gloss import DEFAULT_CACHE, CallableProvider, set_default_provider

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
def clean_gloss_state():
    DEFAULT_CACHE.clear()
    set_default_provider(None)
    yield
    set_default_provider(None)
    DEFAULT_CACHE.clear()


def llm_response(text: str, gloss: str = "УЧЕБНИК") -> str:
    return json.dumps(
        {
            "lang": "rsl",
            "text": text,
            "sentence_type": "statement",
            "tokens": [
                {"type": "sign", "gloss": gloss, "src": "Учебник", "markers": []}
            ],
            "unknown": [],
        },
        ensure_ascii=False,
    )


def run_default_queue(room: Room, text: str, *, timeout: float = 5):
    queue = PipelineQueue(max_concurrency=1)
    try:
        return queue.submit(room.pk, text).result(timeout=timeout)
    finally:
        queue.close()


def test_default_queue_saves_llm_glosses_without_degradation(room):
    Sign.objects.create(
        gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.VERIFIED
    )
    provider = CallableProvider(lambda prompt, **kwargs: llm_response("Учебник"))
    set_default_provider(provider)

    utterance = run_default_queue(room, "Учебник")

    assert utterance.degraded is False
    assert utterance.gloss_ms is not None
    assert utterance.glosses["tokens"][0]["gloss"] == "УЧЕБНИК"
    assert Utterance.objects.get(pk=utterance.pk).degraded is False


def test_llm_fingerspell_goes_to_unknown_queue(room):
    response = json.dumps(
        {
            "lang": "rsl",
            "text": "Иванов",
            "sentence_type": "statement",
            "tokens": [
                {
                    "type": "fingerspell",
                    "letters": ["И", "В", "А", "Н", "О", "В"],
                    "src": "Иванов",
                    "markers": [],
                }
            ],
            "unknown": ["Иванов"],
        },
        ensure_ascii=False,
    )
    set_default_provider(CallableProvider(lambda prompt, **kwargs: response))

    utterance = run_default_queue(room, "Иванов")

    assert utterance.degraded is False
    assert utterance.glosses["unknown"] == ["Иванов"]
    word = UnknownWord.objects.get(lemma="Иванов", lang=Language.RSL)
    assert word.count == 1


def test_default_queue_without_provider_uses_fallback_and_degraded(room):
    Sign.objects.create(
        gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.VERIFIED
    )

    with override_settings(LLM_PROVIDER="", LLM_MODEL="", LLM_API_KEY=""):
        utterance = run_default_queue(room, "Учебник")

    assert utterance.degraded is True
    assert utterance.glosses["tokens"][0]["gloss"] == "УЧЕБНИК"


@override_settings(LLM_TIMEOUT=0.05)
def test_llm_timeout_does_not_block_queue_and_saves_subtitles(room):
    release = threading.Event()

    def stuck(prompt, **kwargs):
        release.wait(timeout=5)
        return llm_response("Учебник")

    set_default_provider(CallableProvider(stuck))
    queue = PipelineQueue(max_concurrency=1)
    started = time.perf_counter()
    try:
        future = queue.submit(room.pk, "Учебник")
        utterance = future.result(timeout=3)
    finally:
        elapsed = time.perf_counter() - started
        release.set()
        queue.close()

    assert elapsed < 0.9
    assert utterance.degraded is True
    assert utterance.glosses["text"] == "Учебник"
    assert utterance.glosses["tokens"] == []
    assert utterance.glosses["unknown"] == []
