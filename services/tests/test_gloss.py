"""Тесты LLM-глосс F1: интерфейс, промпт, схема, словарь и кэш."""

from __future__ import annotations

import json
import re

import pytest

from services.gloss import (
    DEFAULT_CACHE_SIZE,
    MARKERS,
    SENTENCE_TYPES,
    CallableProvider,
    GlossCache,
    GlossDictionary,
    GlossExample,
    GlossFormatError,
    GlossValidationError,
    LLMUnavailableError,
    build_gloss_prompt,
    gloss_cache_key,
    gloss_response_schema,
    normalize_gloss,
    parse_gloss_response,
    restrict_to_dictionary,
    to_glosses,
    validate_glosses,
)

GLOSSES = (
    "ОТКРЫТЬ",
    "УЧЕБНИК",
    "СТРАНИЦА",
    "СТУДЕНТ",
    "ПРЕПОДАВАТЕЛЬ",
    "ЛЕКЦИЯ",
    "ВОПРОС",
    "ОТВЕТ",
    "ЧИТАТЬ",
    "ПИСАТЬ",
    "СЛУШАТЬ",
    "ЗАДАЧА",
    "ПРИМЕР",
    "ДОСКА",
    "ТЕТРАДЬ",
    "РУЧКА",
    "СТОЛ",
    "ОКНО",
    "ДВЕРЬ",
    "ДОМ",
)

DICTIONARY = GlossDictionary.from_glosses(GLOSSES, lang="rsl", version=3)


def payload(text: str, tokens: list[dict], *, sentence_type: str = "statement") -> dict:
    fingerspelled = [token["src"] for token in tokens if token["type"] == "fingerspell"]
    return {
        "lang": "rsl",
        "text": text,
        "sentence_type": sentence_type,
        "tokens": tokens,
        "unknown": fingerspelled,
    }


def sign(gloss: str, src: str, markers: list[str] | None = None) -> dict:
    return {"type": "sign", "gloss": gloss, "src": src, "markers": markers or []}


def number(value: int, src: str) -> dict:
    return {"type": "number", "value": value, "src": src, "markers": []}


def fingerspell(letters: list[str], src: str) -> dict:
    return {"type": "fingerspell", "letters": letters, "src": src, "markers": []}


class FakeProvider:
    """Мок LLM: запоминает промпты и отвечает заранее заданной функцией."""

    name = "fake"

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[dict] = []

    def complete(self, prompt, *, schema, timeout=None):
        self.calls.append({"prompt": prompt, "schema": schema, "timeout": timeout})
        return self.responder(prompt, schema=schema, timeout=timeout)


def json_responder(response: dict | str):
    def responder(prompt, *, schema, timeout=None):
        return response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)

    return responder


# --- JSON-схема и промпт -----------------------------------------------------


def test_schema_is_strict_json_contract_of_gloss_format():
    schema = gloss_response_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"lang", "text", "sentence_type", "tokens", "unknown"}
    assert schema["properties"]["sentence_type"]["enum"] == list(SENTENCE_TYPES)
    token_schemas = schema["properties"]["tokens"]["items"]["oneOf"]
    assert [item["properties"]["type"]["const"] for item in token_schemas] == [
        "sign",
        "number",
        "fingerspell",
    ]
    assert all(item["additionalProperties"] is False for item in token_schemas)
    assert token_schemas[0]["properties"]["markers"]["items"]["enum"] == list(MARKERS)
    assert token_schemas[1]["properties"]["value"]["type"] == "integer"
    assert token_schemas[2]["properties"]["letters"]["minItems"] == 1


def test_prompt_contains_rules_dictionary_examples_and_schema():
    examples = (
        GlossExample(
            text="Откройте учебник",
            response=payload(
                "Откройте учебник",
                [sign("ОТКРЫТЬ", "Откройте"), sign("УЧЕБНИК", "учебник")],
                sentence_type="imperative",
            ),
        ),
    )
    prompt = build_gloss_prompt(
        "  Откройте   учебник! ",
        dictionary=DICTIONARY,
        examples=examples,
    )

    assert 'Фраза: "Откройте учебник!"' in prompt
    assert "Ты — переводчик русской письменной речи" in prompt
    assert "ТОЛЬКО из списка проверенных глосс" in prompt
    assert "- УЧЕБНИК" in prompt
    assert "Версия словаря: 3" in prompt
    assert '"sentence_type"' in prompt
    assert "Фраза: \"Откройте учебник\"" in prompt
    assert "Ответ: " in prompt


def test_prompt_reports_empty_dictionary():
    empty = GlossDictionary.from_glosses([], lang="rsl", version=1)
    prompt = build_gloss_prompt("Иванов", dictionary=empty)

    assert "словарь пуст" in prompt


def test_prompt_rejects_empty_phrase():
    with pytest.raises(GlossValidationError):
        build_gloss_prompt("   ", dictionary=DICTIONARY)


# --- Разбор ответа LLM -------------------------------------------------------


def test_parse_accepts_json_in_markdown_fence():
    raw = "```json\n" + json.dumps(
        payload("Учебник", [sign("УЧЕБНИК", "Учебник")]), ensure_ascii=False
    ) + "\n```"

    result = parse_gloss_response(raw, text="Учебник", lang="rsl")

    assert result["tokens"] == [
        {"type": "sign", "gloss": "УЧЕБНИК", "src": "Учебник", "markers": []}
    ]


def test_parse_overrides_text_and_lang_with_request_values():
    raw = json.dumps(
        {
            "lang": "ksl",
            "text": "испорченный текст",
            "sentence_type": "question",
            "tokens": [],
            "unknown": [],
        }
    )

    result = parse_gloss_response(raw, text="Что это?", lang="rsl")

    assert result["lang"] == "rsl"
    assert result["text"] == "Что это?"
    assert result["sentence_type"] == "question"


def test_parse_coerces_number_forms_and_normalizes_markers_and_letters():
    raw = json.dumps(
        {
            "sentence_type": "statement",
            "tokens": [
                {"type": "number", "value": "10", "src": "10", "markers": []},
                {"type": "number", "value": 4.0, "src": "четыре"},
                {
                    "type": "fingerspell",
                    "letters": ["и", "в", "а", "н"],
                    "src": "Иван",
                    "markers": ["emph", "emph"],
                },
            ],
            "unknown": ["Иван", "Иван"],
        }
    )

    result = parse_gloss_response(raw, text="10 четыре Иван", lang="rsl")

    assert result["tokens"][0]["value"] == 10
    assert result["tokens"][1]["value"] == 4
    assert result["tokens"][2]["letters"] == ["И", "В", "А", "Н"]
    assert result["tokens"][2]["markers"] == ["emph"]
    assert result["unknown"] == ["Иван"]


def test_parse_derives_letters_when_model_omitted_them():
    raw = json.dumps(
        {
            "sentence_type": "statement",
            "tokens": [{"type": "fingerspell", "src": "CОКОЛ-2!"}],
            "unknown": ["CОКОЛ-2!"],
        }
    )

    result = parse_gloss_response(raw, text="CОКОЛ-2!", lang="rsl")

    assert result["tokens"][0]["letters"] == ["С", "О", "К", "О", "Л", "2"]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("не json", "не является JSON"),
        ("[1, 2]", "JSON-объект"),
        (json.dumps({"sentence_type": "unknown", "tokens": []}), "sentence_type"),
        (json.dumps({"sentence_type": "statement", "tokens": {}}), "tokens"),
        (
            json.dumps(
                {
                    "sentence_type": "statement",
                    "tokens": [{"type": "gesture", "src": "дом"}],
                }
            ),
            "type",
        ),
        (
            json.dumps(
                {
                    "sentence_type": "statement",
                    "tokens": [{"type": "sign", "gloss": "", "src": "дом"}],
                }
            ),
            "gloss",
        ),
        (
            json.dumps(
                {
                    "sentence_type": "statement",
                    "tokens": [{"type": "sign", "gloss": "ДОМ"}],
                }
            ),
            "src",
        ),
        (
            json.dumps(
                {
                    "sentence_type": "statement",
                    "tokens": [
                        {"type": "number", "value": True, "src": "1", "markers": []}
                    ],
                }
            ),
            "целым",
        ),
        (
            json.dumps(
                {
                    "sentence_type": "statement",
                    "tokens": [
                        {"type": "number", "value": 1.5, "src": "полтора", "markers": []}
                    ],
                }
            ),
            "целым",
        ),
        (
            json.dumps(
                {
                    "sentence_type": "statement",
                    "tokens": [
                        {
                            "type": "sign",
                            "gloss": "ДОМ",
                            "src": "дом",
                            "markers": ["angry"],
                        }
                    ],
                }
            ),
            "маркер",
        ),
        (
            json.dumps(
                {
                    "sentence_type": "statement",
                    "tokens": [],
                    "unknown": "Иван",
                }
            ),
            "unknown",
        ),
    ],
)
def test_parse_rejects_broken_responses(raw, message):
    with pytest.raises(GlossFormatError, match=message):
        parse_gloss_response(raw, text="фраза", lang="rsl")


def test_validate_requires_lang_and_text_when_not_supplied():
    with pytest.raises(GlossFormatError, match="lang"):
        validate_glosses({"sentence_type": "statement", "tokens": [], "unknown": []})


# --- Ограничение словарём ----------------------------------------------------


def test_restrict_keeps_dictionary_gloss_and_canonicalizes_case_and_yo():
    dictionary = GlossDictionary.from_glosses(["ЁЛКА", "ДОМ"], lang="rsl", version=1)
    glosses = payload("Елка дом", [sign("елка", "Елка"), sign("дом", "дом")])

    result = restrict_to_dictionary(glosses, dictionary)

    assert [token["gloss"] for token in result["tokens"]] == ["ЁЛКА", "ДОМ"]
    assert result["unknown"] == []


def test_restrict_turns_invented_gloss_into_fingerspell_and_rebuilds_unknown():
    glosses = payload(
        "Иванов открывает",
        [sign("ИВАНОВ", "Иванов"), sign("ОТКРЫТЬ", "открывает")],
    )
    glosses["unknown"] = ["что-то из LLM"]

    result = restrict_to_dictionary(glosses, DICTIONARY)

    assert result["tokens"][0] == {
        "type": "fingerspell",
        "letters": ["И", "В", "А", "Н", "О", "В"],
        "src": "Иванов",
        "markers": [],
    }
    assert result["tokens"][1]["gloss"] == "ОТКРЫТЬ"
    assert result["unknown"] == ["Иванов"]


def test_restrict_does_not_duplicate_unknown_words():
    glosses = payload(
        "Иванов Иванов",
        [fingerspell(["И", "В", "А", "Н", "О", "В"], "Иванов")] * 2,
    )

    result = restrict_to_dictionary(glosses, DICTIONARY)

    assert len(result["tokens"]) == 2
    assert result["unknown"] == ["Иванов"]


def test_restrict_checks_dictionary_language():
    glosses = payload("Дом", [sign("ДОМ", "Дом")])

    with pytest.raises(GlossValidationError, match="Язык"):
        restrict_to_dictionary(glosses, GlossDictionary.from_glosses(["ДОМ"], lang="ksl", version=1))


# --- Кэш по хэшу фразы -------------------------------------------------------


def test_cache_key_ignores_whitespace_but_tracks_dictionary_version():
    key = gloss_cache_key("  Откройте   учебник ", "rsl", DICTIONARY)
    same = gloss_cache_key("Откройте учебник", "rsl", DICTIONARY)
    another_version = GlossDictionary.from_glosses(GLOSSES, lang="rsl", version=4)

    assert key == same
    assert key != gloss_cache_key("Откройте учебник", "ksl", DICTIONARY)
    assert key != gloss_cache_key("Откройте учебник", "rsl", another_version)


def test_to_glosses_uses_cache_and_returns_independent_copies():
    response = payload("Откройте учебник", [sign("ОТКРЫТЬ", "Откройте"), sign("УЧЕБНИК", "учебник")])
    provider = FakeProvider(json_responder(response))
    cache = GlossCache()

    first = to_glosses(
        "Откройте  учебник", "rsl", DICTIONARY, provider=provider, cache=cache
    )
    first["tokens"][0]["gloss"] = "ИСПОРЧЕНО"
    second = to_glosses("Откройте учебник", "rsl", DICTIONARY, provider=provider, cache=cache)

    assert len(provider.calls) == 1
    assert len(cache) == 1
    assert second["tokens"][0]["gloss"] == "ОТКРЫТЬ"


def test_to_glosses_does_not_cache_invalid_response():
    answers = iter(
        [
            "не json",
            json.dumps(payload("Дом", [sign("ДОМ", "Дом")])),
        ]
    )
    provider = FakeProvider(lambda prompt, **kwargs: next(answers))
    cache = GlossCache()

    with pytest.raises(GlossFormatError):
        to_glosses("Дом", "rsl", DICTIONARY, provider=provider, cache=cache)

    result = to_glosses("Дом", "rsl", DICTIONARY, provider=provider, cache=cache)

    assert result["tokens"][0]["gloss"] == "ДОМ"
    assert len(provider.calls) == 2
    assert len(cache) == 1


def test_to_glosses_wraps_provider_errors_and_does_not_cache():
    def broken(prompt, **kwargs):
        raise TimeoutError("LLM не ответила за 8 секунд")

    provider = FakeProvider(broken)
    cache = GlossCache()

    with pytest.raises(LLMUnavailableError, match="8 секунд"):
        to_glosses("Дом", "rsl", DICTIONARY, provider=provider, cache=cache)

    assert len(cache) == 0


def test_cache_evicts_least_recently_used_entry():
    cache = GlossCache(maxsize=2)
    cache.set("a", {"value": 1})
    cache.set("b", {"value": 2})
    cache.get("a")  # "a" снова свежий, "b" — самый старый
    cache.set("c", {"value": 3})

    assert cache.get("a") == {"value": 1}
    assert cache.get("b") is None
    assert cache.get("c") == {"value": 3}


def test_default_cache_size_is_positive():
    assert DEFAULT_CACHE_SIZE >= 1
    assert len(GlossCache()) == 0


# --- Вход в to_glosses -------------------------------------------------------


def test_to_glosses_requires_provider():
    with pytest.raises(LLMUnavailableError, match="не настроен"):
        to_glosses("Дом", "rsl", DICTIONARY, cache=GlossCache())


def test_to_glosses_checks_empty_text_and_language():
    provider = FakeProvider(json_responder(payload("Дом", [sign("ДОМ", "Дом")])))

    with pytest.raises(GlossValidationError, match="пустой"):
        to_glosses("   ", "rsl", DICTIONARY, provider=provider, cache=GlossCache())

    with pytest.raises(GlossValidationError, match="язык"):
        to_glosses("Дом", "ksl", DICTIONARY, provider=provider, cache=GlossCache())

    assert provider.calls == []


def test_to_glosses_passes_timeout_and_schema_to_provider():
    provider = FakeProvider(
        json_responder(payload("Дом", [sign("ДОМ", "Дом")]))
    )

    to_glosses(
        "Дом",
        "rsl",
        DICTIONARY,
        provider=provider,
        cache=GlossCache(),
        timeout=8.0,
    )

    call = provider.calls[0]
    assert call["timeout"] == 8.0
    assert call["schema"] == gloss_response_schema()
    assert "- ДОМ" in call["prompt"]
    assert 'Фраза: "Дом"' in call["prompt"]


def test_callable_provider_adapts_a_function():
    provider = CallableProvider(
        lambda prompt, *, schema, timeout=None: json.dumps(
            payload("Дом", [sign("ДОМ", "Дом")]), ensure_ascii=False
        )
    )

    result = to_glosses("Дом", "rsl", DICTIONARY, provider=provider, cache=GlossCache())

    assert result["tokens"][0]["gloss"] == "ДОМ"


def test_examples_take_part_in_cache_key_and_prompt():
    provider = FakeProvider(json_responder(payload("Дом", [sign("ДОМ", "Дом")])))
    cache = GlossCache()
    example = GlossExample(
        text="Дом",
        response=payload("Дом", [sign("ДОМ", "Дом")]),
    )

    to_glosses("Дом", "rsl", DICTIONARY, provider=provider, cache=cache)
    to_glosses(
        "Дом",
        "rsl",
        DICTIONARY,
        provider=provider,
        cache=cache,
        examples=(example,),
    )

    assert len(provider.calls) == 2
    assert "Примеры:\nФраза: \"Дом\"" in provider.calls[1]["prompt"]


# --- 30 фраз: формат ответа корректен ---------------------------------------


PHRASES = [
    "Откройте учебник",
    "Страница десять",
    "Студент читает текст",
    "Преподаватель задаёт вопрос",
    "Ответьте на вопрос!",
    "Что такое лекция?",
    "Запишите домашнее задание",
    "Посмотрите на доску",
    "Тетрадь и ручка на столе",
    "Закройте окно, пожалуйста",
    "Откройте дверь",
    "Дом находится рядом",
    "Иванов отвечает у доски",
    "Петрова читает пример",
    "Слушайте внимательно",
    "Напишите число 25",
    "Сегодня нет лекции",
    "Вопрос первый: что это?",
    "Студент не понял задачу",
    "Повторите, пожалуйста",
    "Возьмите тетрадь и ручку",
    "Страница 12, пример 4",
    "Преподаватель объясняет тему",
    "Сидоров задаёт вопрос",
    "Ответ правильный!",
    "Откройте учебник на странице десять",
    "Кто готов ответить?",
    "Слушайте и записывайте",
    "На доске три примера",
    "Лекция закончена, спасибо",
]


def generate_response(prompt: str, *, schema=None, timeout=None) -> str:
    """Мок LLM: строит ответ по фразе, включая выдуманную глоссу и дактиль."""
    raw_text = prompt.rsplit("Фраза: ", 1)[1]
    text = json.loads(raw_text)
    words = re.findall(r"\d+|[^\W\d_]+", text, re.UNICODE)

    tokens: list[dict] = []
    for index, word in enumerate(words):
        if word.isdigit():
            tokens.append(number(int(word), word))
        elif index % 3 == 0:
            # Выдуманная моделью глосса: словарь должен заменить её дактилем.
            tokens.append(sign(f"НЕИЗВЕСТНО_{index}", word))
        elif index % 3 == 1:
            gloss = GLOSSES[index % len(GLOSSES)]
            tokens.append(sign(gloss, word, markers=[]))
        else:
            tokens.append(fingerspell([letter.upper() for letter in word], word))

    if "?" in text:
        sentence_type = "question"
    elif text.rstrip().endswith("!"):
        sentence_type = "exclamation"
    elif words and words[0].lower() in {"откройте", "закройте", "запишите", "посмотрите",
                                        "ответьте", "возьмите", "повторите", "напишите",
                                        "слушайте"}:
        sentence_type = "imperative"
    else:
        sentence_type = "statement"

    return json.dumps(
        {
            "lang": "rsl",
            "text": text,
            "sentence_type": sentence_type,
            "tokens": tokens,
            "unknown": [],
        },
        ensure_ascii=False,
    )


def test_thirty_phrases_produce_valid_dictionary_restricted_glosses():
    assert len(PHRASES) == 30
    cache = GlossCache()

    for phrase in PHRASES:
        provider = FakeProvider(generate_response)
        result = to_glosses(phrase, "rsl", DICTIONARY, provider=provider, cache=cache)

        # Ответ снова проходит ту же проверку, которой встречаем LLM.
        validate_glosses(result, text=phrase, lang="rsl")
        assert result["lang"] == "rsl"
        assert result["text"] == phrase
        assert result["sentence_type"] in SENTENCE_TYPES
        assert isinstance(result["tokens"], list)
        assert all(token["type"] in {"sign", "number", "fingerspell"} for token in result["tokens"])
        assert all(
            token["gloss"] in GLOSSES for token in result["tokens"] if token["type"] == "sign"
        )
        assert result["unknown"] == [
            token["src"] for token in result["tokens"] if token["type"] == "fingerspell"
        ]
        assert normalize_gloss(result["text"]) == normalize_gloss(phrase)
