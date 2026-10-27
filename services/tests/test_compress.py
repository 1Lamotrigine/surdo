"""Тесты сжатия длинной фразы F3 (``services.gloss.compress``)."""

from __future__ import annotations

import json

import pytest

from services.gloss import (
    GlossFormatError,
    GlossValidationError,
    build_compress_prompt,
    compress,
    compress_locally,
    compress_response_schema,
    parse_compress_response,
)

LONG_PHRASE = (
    "Итак, ребята, сегодня мы с вами, как вы знаете, поговорим о том, "
    "как устроен словарь жестов и зачем он нужен на лекции."
)


class FakeProvider:
    name = "fake"

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[dict] = []

    def complete(self, prompt, *, schema, timeout=None):
        self.calls.append({"prompt": prompt, "schema": schema, "timeout": timeout})
        return self.responder(prompt, schema=schema, timeout=timeout)


def json_responder(text: str):
    return lambda prompt, *, schema, timeout=None: json.dumps(
        {"text": text}, ensure_ascii=False
    )


# --- Схема, промпт и разбор ответа ------------------------------------------


def test_compress_schema_requires_single_text_field():
    schema = compress_response_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["text"]
    assert schema["properties"]["text"] == {"type": "string", "minLength": 1}


def test_compress_prompt_contains_text_target_and_rules():
    prompt = build_compress_prompt("  " + LONG_PHRASE + " ", 0.6)

    target = max(1, int(len(" ".join(LONG_PHRASE.split())) * 0.6))
    assert f"не более {target} символов" in prompt
    assert "около 60%" in prompt
    assert "Убери вводные слова" in prompt
    assert "JSON-схема ответа" in prompt
    assert 'Фраза: "Итак, ребята' in prompt


def test_parse_compress_response_accepts_fence_and_strips_text():
    raw = '```json\n{"text": "  Слушайте лекцию.  "}\n```'

    assert parse_compress_response(raw) == "Слушайте лекцию."


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("не json", "не является JSON"),
        ("[]", "JSON-объект"),
        ('{"text": ""}', "непустой"),
        ('{"other": "текст"}', "непустой"),
        ('{"text": 10}', "непустой"),
    ],
)
def test_parse_compress_response_rejects_broken_answers(raw, message):
    with pytest.raises(GlossFormatError, match=message):
        parse_compress_response(raw)


# --- LLM-сжатие -------------------------------------------------------------


def test_compress_uses_llm_and_returns_shorter_text():
    provider = FakeProvider(json_responder("Слушайте лекцию о словаре жестов."))

    result = compress(LONG_PHRASE, 0.6, provider=provider, timeout=8.0)

    assert result == "Слушайте лекцию о словаре жестов."
    assert len(result) < len(" ".join(LONG_PHRASE.split()))
    call = provider.calls[0]
    assert call["timeout"] == 8.0
    assert call["schema"] == compress_response_schema()
    assert "Целевая длина" in call["prompt"]


def test_compress_accepts_fenced_llm_answer():
    provider = FakeProvider(
        lambda prompt, **kwargs: '```json\n{"text": "Слушайте лекцию."}\n```'
    )

    assert compress(LONG_PHRASE, 0.5, provider=provider) == "Слушайте лекцию."


def test_compress_falls_back_locally_when_llm_returns_long_text():
    provider = FakeProvider(json_responder(LONG_PHRASE + " И ещё немного слов."))

    result = compress(LONG_PHRASE, 0.6, provider=provider)

    assert len(result) < len(" ".join(LONG_PHRASE.split()))
    assert "И ещё немного слов" not in result


def test_compress_falls_back_locally_when_llm_fails_or_returns_garbage():
    def broken(prompt, **kwargs):
        raise TimeoutError("LLM не ответила")

    for responder in (broken, lambda prompt, **kwargs: "не json"):
        provider = FakeProvider(responder)

        result = compress(LONG_PHRASE, 0.6, provider=provider)

        assert 0 < len(result) < len(" ".join(LONG_PHRASE.split()))


def test_compress_works_without_provider():
    result = compress(LONG_PHRASE, 0.6)

    assert len(result) < len(" ".join(LONG_PHRASE.split()))
    assert "Итак" not in result
    assert "как вы знаете" not in result


# --- Локальное сжатие -------------------------------------------------------


def test_local_compress_removes_fillers_and_keeps_meaning_words():
    result = compress_locally(LONG_PHRASE, 0.9)

    assert len(result) < len(LONG_PHRASE)
    assert "Итак" not in result
    assert "ребята" not in result
    assert "как вы знаете" not in result
    assert "словарь жестов" in result
    assert result[0].isupper()


def test_local_compress_trims_long_phrase_to_target_at_word_boundary():
    phrase = (
        "Преподаватель подробно объясняет студентам новую тему лекции, "
        "показывает примеры на доске и отвечает на вопросы аудитории."
    )
    target = max(1, int(len(phrase) * 0.5))

    result = compress_locally(phrase, 0.5)

    assert 0 < len(result) <= target
    assert len(result) < len(phrase)
    assert not result.endswith(",")
    assert phrase.startswith(result)


def test_local_compress_leaves_single_short_word_unchanged():
    assert compress_locally("Дом", 0.5) == "Дом"
    assert compress("Дом", 0.5) == "Дом"


@pytest.mark.parametrize(
    "phrase",
    [
        LONG_PHRASE,
        (
            "Сегодня на лекции мы подробно разберём, как работает словарь "
            "жестов, почему версии словаря важны и как редактор записывает клипы."
        ),
        (
            "Пожалуйста, обратите внимание на то, что на странице десять "
            "находится пример, который мы сейчас разберём вместе с вами."
        ),
        (
            "В общем, если можно, давайте сначала посмотрим на доску, "
            "а потом я расскажу, как устроен конвейер обработки фразы."
        ),
    ],
)
def test_compress_result_is_shorter_for_long_phrases(phrase):
    for ratio in (0.4, 0.6, 0.8):
        result = compress(phrase, ratio)
        assert 0 < len(result) < len(phrase)


# --- Проверка входа ---------------------------------------------------------


@pytest.mark.parametrize("ratio", [0, 1, 1.2, -0.5, True, "0.6", None])
def test_compress_rejects_invalid_target_ratio(ratio):
    with pytest.raises(GlossValidationError, match="target_ratio"):
        compress(LONG_PHRASE, ratio)
    with pytest.raises(GlossValidationError, match="target_ratio"):
        compress_locally(LONG_PHRASE, ratio)
    with pytest.raises(GlossValidationError, match="target_ratio"):
        build_compress_prompt(LONG_PHRASE, ratio)


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_compress_rejects_empty_phrase(text):
    with pytest.raises(GlossValidationError, match="пустой"):
        compress(text, 0.6)
    with pytest.raises(GlossValidationError, match="пустой"):
        compress_locally(text, 0.6)
    with pytest.raises(GlossValidationError, match="пустой"):
        build_compress_prompt(text, 0.6)


def test_compress_does_not_call_llm_for_invalid_ratio():
    provider = FakeProvider(json_responder("Слушайте."))

    with pytest.raises(GlossValidationError):
        compress(LONG_PHRASE, 1.5, provider=provider)

    assert provider.calls == []
