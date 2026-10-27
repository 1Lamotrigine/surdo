"""F4: движок глосс — словарь из БД, LLM, F2 и деградация до субтитров."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from dictionary.models import DictionaryVersion, Language, Sign, SignStatus
from pipeline.gloss_engine import (
    compute_glosses,
    compute_glosses_async,
    subtitle_only_glosses,
    verified_gloss_dictionary,
)
from services.gloss import DEFAULT_CACHE, CallableProvider, set_default_provider

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def clean_gloss_state():
    DEFAULT_CACHE.clear()
    set_default_provider(None)
    yield
    set_default_provider(None)
    DEFAULT_CACHE.clear()


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )


@pytest.fixture
def rsl_signs():
    for gloss in ("ОТКРЫТЬ", "УЧЕБНИК"):
        Sign.objects.create(gloss=gloss, lang=Language.RSL, status=SignStatus.VERIFIED)
    Sign.objects.create(gloss="ЧЕРНОВИК", lang=Language.RSL, status=SignStatus.DRAFT)


def llm_response(text: str, gloss: str = "УЧЕБНИК", *, src: str = "Учебник") -> str:
    return json.dumps(
        {
            "lang": "rsl",
            "text": text,
            "sentence_type": "statement",
            "tokens": [
                {"type": "sign", "gloss": gloss, "src": src, "markers": []}
            ],
            "unknown": [],
        },
        ensure_ascii=False,
    )


class RecordingProvider:
    name = "recording"

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[dict] = []

    def complete(self, prompt, *, schema, timeout=None):
        self.calls.append({"prompt": prompt, "schema": schema, "timeout": timeout})
        return self.responder(prompt, schema=schema, timeout=timeout)


# --- Словарь -----------------------------------------------------------------


def test_dictionary_uses_only_verified_signs_and_current_version(rsl_signs):
    DictionaryVersion.objects.create(lang=Language.RSL, number=4)
    DictionaryVersion.objects.create(lang=Language.RSL, number=2)

    dictionary = verified_gloss_dictionary(Language.RSL)

    assert dictionary.lang == "rsl"
    assert dictionary.version == "4"
    assert dictionary.glosses == ("ОТКРЫТЬ", "УЧЕБНИК")
    assert dictionary.canonical("учебник") == "УЧЕБНИК"


def test_dictionary_without_version_starts_from_zero(rsl_signs):
    assert verified_gloss_dictionary(Language.RSL).version == "0"


def test_subtitle_only_glosses_have_text_and_no_tokens():
    glosses = subtitle_only_glosses("Учебник?", "rsl")

    assert glosses == {
        "lang": "rsl",
        "text": "Учебник?",
        "sentence_type": "question",
        "tokens": [],
        "unknown": [],
    }


# --- LLM / F2 / деградация ---------------------------------------------------


def test_llm_glosses_are_used_and_not_degraded(rsl_signs):
    provider = RecordingProvider(lambda prompt, **kwargs: llm_response("Учебник"))

    outcome = compute_glosses("Учебник", Language.RSL, provider=provider, timeout=3)

    assert outcome.source == "llm"
    assert outcome.degraded is False
    assert outcome.error is None
    assert outcome.glosses["tokens"][0]["gloss"] == "УЧЕБНИК"
    assert outcome.glosses["unknown"] == []
    assert provider.calls[0]["timeout"] == 3
    assert "Проверенные глоссы" in provider.calls[0]["prompt"]
    assert provider.calls[0]["schema"]["title"] == "RussianSignLanguageGlosses"


def test_no_provider_uses_f2_fallback_and_marks_degraded(rsl_signs):
    outcome = compute_glosses("Откройте учебник Иванов", Language.RSL)

    assert outcome.source == "fallback"
    assert outcome.degraded is True
    assert [token["type"] for token in outcome.glosses["tokens"]] == [
        "sign",
        "sign",
        "fingerspell",
    ]
    assert outcome.glosses["tokens"][0]["gloss"] == "ОТКРЫТЬ"
    assert outcome.glosses["tokens"][2]["letters"] == [
        "И",
        "В",
        "А",
        "Н",
        "О",
        "В",
    ]
    assert outcome.glosses["unknown"] == ["Иванов"]


def test_provider_error_leaves_only_subtitles(rsl_signs):
    def broken(prompt, **kwargs):
        raise RuntimeError("API недоступен")

    outcome = compute_glosses(
        "Учебник", Language.RSL, provider=CallableProvider(broken)
    )

    assert outcome.source == "subtitles"
    assert outcome.degraded is True
    assert outcome.glosses["text"] == "Учебник"
    assert outcome.glosses["tokens"] == []
    assert outcome.glosses["unknown"] == []
    assert "API недоступен" in (outcome.error or "")


def test_invalid_json_leaves_only_subtitles(rsl_signs):
    provider = CallableProvider(lambda prompt, **kwargs: "не JSON")

    outcome = compute_glosses("Учебник", Language.RSL, provider=provider)

    assert outcome.source == "subtitles"
    assert outcome.degraded is True
    assert outcome.glosses["tokens"] == []


def test_hallucinated_gloss_is_restricted_to_fingerspell(rsl_signs):
    provider = CallableProvider(
        lambda prompt, **kwargs: llm_response(
            "Учебник", "ВЫДУМАННЫЙ_ЖЕСТ", src="Учебник"
        )
    )

    outcome = compute_glosses("Учебник", Language.RSL, provider=provider)

    assert outcome.source == "llm"
    assert outcome.degraded is False
    assert outcome.glosses["tokens"][0]["type"] == "fingerspell"
    assert outcome.glosses["unknown"] == ["Учебник"]


# --- Async и таймаут ---------------------------------------------------------


def test_async_without_provider_returns_fallback(rsl_signs):
    outcome = asyncio.run(compute_glosses_async("Учебник", Language.RSL))

    assert outcome.source == "fallback"
    assert outcome.degraded is True
    assert outcome.glosses["tokens"][0]["type"] == "sign"


def test_async_timeout_returns_subtitles_and_does_not_block_loop(rsl_signs):
    ticks = 0

    def slow(prompt, **kwargs):
        time.sleep(0.3)
        return llm_response("Учебник")

    async def scenario():
        nonlocal ticks

        async def ticker():
            nonlocal ticks
            for _ in range(10):
                await asyncio.sleep(0.01)
                ticks += 1

        ticker_task = asyncio.create_task(ticker())
        started = time.perf_counter()
        outcome = await compute_glosses_async(
            "Учебник",
            Language.RSL,
            provider=CallableProvider(slow),
            timeout=0.05,
        )
        elapsed = time.perf_counter() - started
        await ticker_task
        return outcome, elapsed

    outcome, elapsed = asyncio.run(scenario())

    assert outcome.source == "timeout"
    assert outcome.degraded is True
    assert outcome.glosses["tokens"] == []
    assert elapsed < 0.25
    # Пока ждали LLM, цикл успел выполнить тикер: to_thread не заблокировал loop.
    assert ticks == 10
