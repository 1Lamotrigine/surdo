"""Упрощённые глоссы для этапа E1: жест из словаря или дактиль.

Здесь живёт **чистая** часть конвейера: разбор текста на слова, выбор глоссы
словаря и раскладка незнакомого слова по буквам. Модуль не обращается к базе и
не зависит от Django, поэтому проверяется обычными тестами. Словарь передаётся
как отображение «нормализованная глосса → глосса из БД» — его готовит
``pipeline.services``.

Формат результата повторяет ТЗ 7.2 (``tokens``, ``unknown``, ``sentence_type``).
Это упрощённый режим блока E: LLM, лемматизация и грамматические маркеры
появятся в блоке F, поэтому здесь нет морфологии — слово ищется в словаре по
точной форме, а всё остальное показывается дактилем (FR-9).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from services.morphology import gloss_text_units

# Русский алфавит дактиля — совпадает с frontend/dactyl.ts (33 буквы).
DACTYL_ALPHABET = (
    "А", "Б", "В", "Г", "Д", "Е", "Ё", "Ж", "З", "И", "Й", "К", "Л", "М", "Н",
    "О", "П", "Р", "С", "Т", "У", "Ф", "Х", "Ц", "Ч", "Ш", "Щ", "Ъ", "Ы", "Ь",
    "Э", "Ю", "Я",
)

# Латинские буквы, похожие на кириллические: ввод и раскладка их часто путают.
LATIN_TO_CYRILLIC = {
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
}

_ALPHABET = frozenset(DACTYL_ALPHABET)
_WORD_RE = re.compile(r"\d+|[^\W\d_]+", re.UNICODE)


def normalize_word(value: str) -> str:
    """Привести слово к сравнимому виду: нижний регистр, ё→е, без пунктуации."""
    return re.sub(r"[^\w]+", "", (value or "").lower().replace("ё", "е"))


def word_letters(value: str) -> list[str]:
    """Буквы/цифры слова для дактиля (верхний регистр, латиница → кириллица).

    Пунктуация и пробелы отбрасываются, неподдерживаемые символы пропускаются —
    так же, как ``splitWord`` на клиенте (C5). Цифры попадают в ``letters``:
    у дактиля есть клипы цифр (``ЦИФРА_5``).
    """
    letters: list[str] = []
    for raw in value:
        char = raw.upper()
        char = LATIN_TO_CYRILLIC.get(char, char)
        if char in _ALPHABET or char.isdigit():
            letters.append(char)
    return letters


def split_words(text: str) -> list[str]:
    """Слова и числа текста по порядку (пунктуация не входит)."""
    return [match.group(0) for match in _WORD_RE.finditer(text or "")]


def sentence_type(text: str) -> str:
    """Простой тип предложения: вопрос, восклицание или повествование.

    Точная классификация (в том числе повелительное наклонение из ТЗ 7.2) —
    задача LLM/лемматизации блока F; здесь достаточно пунктуации.
    """
    stripped = (text or "").rstrip()
    if "?" in stripped:
        return "question"
    if stripped.endswith("!"):
        return "exclamation"
    return "statement"


def build_simplified_glosses(
    text: str,
    *,
    lang: str,
    signs: Mapping[str, str] | None = None,
) -> dict:
    """Построить объект глосс: слово словаря или дактиль (FR-8, FR-9).

    ``signs`` — отображение нормализованной глоссы в каноническую запись из
    словаря. Если слова нет, токен становится ``fingerspell`` и попадает в
    ``unknown`` (сервис затем добавит его в очередь нераспознанных слов).
    """
    dictionary = signs or {}
    tokens: list[dict] = []
    unknown: list[str] = []

    for word, phrase in gloss_text_units(text, dictionary.values()):
        if phrase is None and word.isdigit():
            tokens.append({"type": "number", "value": int(word), "src": word})
            continue

        gloss = phrase or dictionary.get(normalize_word(word))
        if gloss is not None:
            tokens.append(
                {
                    "type": "sign",
                    "gloss": gloss,
                    "src": word,
                    "markers": [],
                }
            )
            continue

        tokens.append(
            {
                "type": "fingerspell",
                "letters": word_letters(word),
                "src": word,
            }
        )
        # В объекте глосс слово не дублируется; очередь слов считает каждое
        # вхождение отдельно (это делает сервис).
        if word not in unknown:
            unknown.append(word)

    return {
        "lang": lang,
        "text": text,
        "sentence_type": sentence_type(text),
        "tokens": tokens,
        "unknown": unknown,
    }
