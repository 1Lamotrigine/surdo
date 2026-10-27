"""Упрощённые глоссы E1: слово из словаря, дактиль и числа."""

from pipeline.glosses import (
    DACTYL_ALPHABET,
    build_simplified_glosses,
    normalize_word,
    sentence_type,
    split_words,
    word_letters,
)

SIGNS = {
    "открыть": "ОТКРЫТЬ",
    "учебник": "УЧЕБНИК",
    "страница": "СТРАНИЦА",
}


def test_known_words_become_sign_tokens():
    glosses = build_simplified_glosses(
        "Откройте учебник",
        lang="rsl",
        signs={**SIGNS, "откройте": "ОТКРЫТЬ"},
    )

    assert glosses["lang"] == "rsl"
    assert glosses["text"] == "Откройте учебник"
    assert glosses["tokens"] == [
        {"type": "sign", "gloss": "ОТКРЫТЬ", "src": "Откройте", "markers": []},
        {"type": "sign", "gloss": "УЧЕБНИК", "src": "учебник", "markers": []},
    ]
    assert glosses["unknown"] == []


def test_unknown_word_is_fingerspelled_and_listed():
    glosses = build_simplified_glosses("Иванов", lang="rsl", signs=SIGNS)

    assert glosses["tokens"] == [
        {
            "type": "fingerspell",
            "letters": ["И", "В", "А", "Н", "О", "В"],
            "src": "Иванов",
        }
    ]
    assert glosses["unknown"] == ["Иванов"]


def test_mixed_phrase_keeps_order():
    glosses = build_simplified_glosses(
        "Учебник Иванов страница",
        lang="rsl",
        signs=SIGNS,
    )

    kinds = [token["type"] for token in glosses["tokens"]]
    assert kinds == ["sign", "fingerspell", "sign"]
    assert glosses["tokens"][1]["letters"] == ["И", "В", "А", "Н", "О", "В"]
    assert glosses["unknown"] == ["Иванов"]


def test_lookup_ignores_case_and_yo():
    glosses = build_simplified_glosses(
        "УЧЕБНИК Ёлка",
        lang="rsl",
        signs={"учебник": "УЧЕБНИК", "елка": "ЁЛКА"},
    )

    assert glosses["tokens"][0]["gloss"] == "УЧЕБНИК"
    assert glosses["tokens"][1]["gloss"] == "ЁЛКА"
    assert normalize_word("Ёлка!") == "елка"


def test_digits_become_number_tokens():
    glosses = build_simplified_glosses("страница 10", lang="rsl", signs=SIGNS)

    assert glosses["tokens"][1] == {"type": "number", "value": 10, "src": "10"}
    assert glosses["unknown"] == []


def test_punctuation_is_not_a_word_and_sentence_type_is_detected():
    assert split_words("Откройте, учебник!") == ["Откройте", "учебник"]
    assert sentence_type("Откройте учебник?") == "question"
    assert sentence_type("Откройте учебник!") == "exclamation"
    assert sentence_type("Откройте учебник.") == "statement"


def test_unknown_words_appear_once_in_glosses_but_once_per_token():
    glosses = build_simplified_glosses("Иванов Иванов", lang="rsl")

    assert [token["type"] for token in glosses["tokens"]] == ["fingerspell", "fingerspell"]
    # В объекте глосс слово не дублируется; счётчик очереди ведёт сервис.
    assert glosses["unknown"] == ["Иванов"]


def test_word_letters_normalizes_latin_lookalikes_and_skips_punctuation():
    assert word_letters("CОКОЛ-2!") == ["С", "О", "К", "О", "Л", "2"]
    assert word_letters("abc") == ["А", "В", "С"]
    assert set(word_letters("".join(DACTYL_ALPHABET))) == set(DACTYL_ALPHABET)


def test_empty_text_gives_empty_tokens():
    glosses = build_simplified_glosses("", lang="rsl")

    assert glosses["tokens"] == []
    assert glosses["unknown"] == []
    assert glosses["sentence_type"] == "statement"
