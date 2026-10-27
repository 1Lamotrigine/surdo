"""Тесты запасного режима F2: лемматизация и пословные глоссы без LLM."""

from __future__ import annotations

import pytest

from services.gloss import (
    GlossDictionary,
    GlossFormatError,
    GlossValidationError,
    LLMUnavailableError,
    fallback_glosses,
    to_glosses,
    validate_glosses,
)
from services.morphology import (
    FUNCTION_POS,
    clean_word,
    is_function_word,
    lemmatize_word,
    lemmatize_words,
    split_words,
    word_forms,
)

GLOSSES = (
    "ОТКРЫТЬ",
    "УЧЕБНИК",
    "СТРАНИЦА",
    "ЛЕКЦИЯ",
    "ЧИТАТЬ",
    "ПИСАТЬ",
    "СТОЛ",
    "ДОМ",
    "СТУДЕНТ",
)

DICTIONARY = GlossDictionary.from_glosses(GLOSSES, lang="rsl", version=1)


def test_lemmatize_known_word_forms():
    assert lemmatize_word("учебнике") == "учебник"
    assert lemmatize_word("странице") == "страница"
    assert lemmatize_word("Откройте") == "открыть"
    assert lemmatize_word("лекции") == "лекция"
    assert lemmatize_words(["учебнике", "странице"]) == ["учебник", "страница"]


def test_lemmatize_unknown_name_keeps_reasonable_form():
    assert lemmatize_word("Иванове") == "иванов"
    assert lemmatize_word("") == ""
    assert clean_word("  Ёлка! ") == "елка"


def test_word_forms_returns_pos_and_empty_for_noise():
    forms = word_forms("учебнике")

    assert forms
    assert forms[0].normal_form == "учебник"
    assert forms[0].pos in {"NOUN", "ADJF"}
    assert word_forms("!!!") == ()


def test_function_words_are_recognized_by_pos():
    assert {"PREP", "CONJ", "PRCL"} <= FUNCTION_POS
    assert is_function_word("на")
    assert is_function_word("и")
    assert not is_function_word("учебник")


def test_split_words_keeps_letters_and_digits_only():
    assert split_words("Страница 10, учебник!") == ["Страница", "10", "учебник"]
    assert split_words("") == []


def test_fallback_translates_lemma_forms_and_skips_prepositions():
    result = fallback_glosses(
        "Откройте учебник на странице десять",
        "rsl",
        DICTIONARY,
    )

    assert result["sentence_type"] == "statement"
    assert result["tokens"] == [
        {"type": "sign", "gloss": "ОТКРЫТЬ", "src": "Откройте", "markers": []},
        {"type": "sign", "gloss": "УЧЕБНИК", "src": "учебник", "markers": []},
        {"type": "sign", "gloss": "СТРАНИЦА", "src": "странице", "markers": []},
        {"type": "number", "value": 10, "src": "десять", "markers": []},
    ]
    assert result["unknown"] == []


def test_fallback_fingerspells_unknown_content_words_and_deduplicates():
    result = fallback_glosses("Иванов читает лекцию Иванов", "rsl", DICTIONARY)

    assert [token["type"] for token in result["tokens"]] == [
        "fingerspell",
        "sign",
        "sign",
        "fingerspell",
    ]
    assert result["tokens"][0]["letters"] == ["И", "В", "А", "Н", "О", "В"]
    assert result["tokens"][1]["gloss"] == "ЧИТАТЬ"
    assert result["tokens"][2]["gloss"] == "ЛЕКЦИЯ"
    assert result["unknown"] == ["Иванов"]


def test_fallback_uses_dictionary_sign_for_function_word_if_recorded():
    dictionary = GlossDictionary.from_glosses([*GLOSSES, "НА"], lang="rsl", version=1)

    result = fallback_glosses("На столе", "rsl", dictionary)

    assert [token["type"] for token in result["tokens"]] == ["sign", "sign"]
    assert result["tokens"][0]["gloss"] == "НА"
    assert result["tokens"][1]["gloss"] == "СТОЛ"


def test_fallback_keeps_unknown_function_words_out_of_queue():
    result = fallback_glosses("Дом и окно", "rsl", DICTIONARY)

    assert [token["type"] for token in result["tokens"]] == ["sign", "fingerspell"]
    assert result["tokens"][0]["gloss"] == "ДОМ"
    assert result["unknown"] == ["окно"]


@pytest.mark.parametrize(
    ("word", "value"),
    [
        ("ноль", 0),
        ("две", 2),
        ("десять", 10),
        ("двадцать", 20),
        ("сто", 100),
        ("тысяча", 1000),
    ],
)
def test_fallback_converts_number_words(word, value):
    result = fallback_glosses(word, "rsl", DICTIONARY)

    assert result["tokens"] == [
        {"type": "number", "value": value, "src": word, "markers": []}
    ]


def test_fallback_converts_digits_and_detects_sentence_type():
    question = fallback_glosses("Страница 12?", "rsl", DICTIONARY)
    exclamation = fallback_glosses("Откройте учебник!", "rsl", DICTIONARY)

    assert question["tokens"][1] == {
        "type": "number",
        "value": 12,
        "src": "12",
        "markers": [],
    }
    assert question["sentence_type"] == "question"
    assert exclamation["sentence_type"] == "exclamation"


def test_fallback_for_ksl_uses_exact_forms_without_russian_morphology():
    dictionary = GlossDictionary.from_glosses(["УЧЕБНИК"], lang="ksl", version=1)

    exact = fallback_glosses("Учебник", "ksl", dictionary)
    inflected = fallback_glosses("учебнике", "ksl", dictionary)

    assert exact["tokens"][0]["type"] == "sign"
    assert inflected["tokens"][0]["type"] == "fingerspell"
    assert inflected["unknown"] == ["учебнике"]


def test_fallback_result_passes_same_validation_as_llm():
    result = fallback_glosses("Откройте учебник на странице 10!", "rsl", DICTIONARY)

    validated = validate_glosses(result, text="Откройте учебник на странице 10!", lang="rsl")

    assert validated == result


def test_fallback_works_when_llm_is_not_available():
    # Провайдер не настроен: LLM-путь падает, запасной режим продолжает работать.
    with pytest.raises(LLMUnavailableError):
        to_glosses("Откройте учебник", "rsl", DICTIONARY)

    result = fallback_glosses("Откройте учебник", "rsl", DICTIONARY)

    assert [token["gloss"] for token in result["tokens"]] == ["ОТКРЫТЬ", "УЧЕБНИК"]


def test_fallback_rejects_empty_text_and_other_dictionary_language():
    with pytest.raises(GlossValidationError, match="пустой"):
        fallback_glosses("   ", "rsl", DICTIONARY)

    with pytest.raises(GlossValidationError, match="Язык"):
        fallback_glosses("Дом", "ksl", DICTIONARY)


PHRASES = [
    "Откройте учебник",
    "Студент читает лекцию",
    "Напишите номер 25",
    "Что такое лекция?",
    "Посмотрите на доску!",
    "Иванов отвечает у стола",
    "Петрова пишет в тетради",
    "Закройте дверь, пожалуйста",
    "Страница десять, пример четыре",
    "Слушайте внимательно",
    "Лекция закончена",
    "Кто готов ответить?",
]


@pytest.mark.parametrize("phrase", PHRASES)
def test_fallback_phrases_without_llm_are_valid(phrase):
    result = fallback_glosses(phrase, "rsl", DICTIONARY)

    validate_glosses(result, text=phrase, lang="rsl")
    assert result["text"] == phrase
    assert all(
        token["gloss"] in GLOSSES for token in result["tokens"] if token["type"] == "sign"
    )
    assert result["unknown"] == [
        token["src"] for token in result["tokens"] if token["type"] == "fingerspell"
    ]
    assert all(token["letters"] for token in result["tokens"] if token["type"] == "fingerspell")


def test_fallback_rejects_unsupported_gloss_shape_via_validation():
    result = fallback_glosses("Дом", "rsl", DICTIONARY)
    result["sentence_type"] = "unknown"

    with pytest.raises(GlossFormatError, match="sentence_type"):
        validate_glosses(result)
