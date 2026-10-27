"""Лемматизация русского текста для запасного режима глосс (этап F2).

``pymorphy3`` грузится лениво: модуль импортируется без словарей, а первый
вызов ``word_forms`` загружает анализатор один раз на процесс. Результаты
анализа кэшируются — в лекции одни и те же слова повторяются часто.

Модуль чистый: не зависит от Django и от словаря жестов. Он отдаёт нормальные
формы и часть речи, а решение «есть ли жест» принимает ``services.gloss``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# Служебные части речи: в жестовой фразе они обычно опускаются. Словарь
# проверяется раньше этого фильтра, поэтому жест для служебного слова всё же
# покажется, если редактор его записал.
FUNCTION_POS = frozenset({"PREP", "CONJ", "PRCL", "INTJ"})

_WORD_RE = re.compile(r"\d+|[^\W\d_]+", re.UNICODE)


@dataclass(frozen=True)
class WordForm:
    """Разбор одного слова: нормальная форма и часть речи."""

    normal_form: str
    pos: str | None


@lru_cache(maxsize=1)
def _analyzer():
    # Импорт внутри функции: без pymorphy3 не нужен весь словарь в памяти.
    from pymorphy3 import MorphAnalyzer

    return MorphAnalyzer()


def clean_word(value: str) -> str:
    """Слово для анализа: нижний регистр, ё→е, только буквы."""
    return re.sub(r"[^\w]+", "", (value or "").lower().replace("ё", "е"))


@lru_cache(maxsize=8192)
def word_forms(value: str) -> tuple[WordForm, ...]:
    """Все разборы слова по порядку уверенности ``pymorphy3``.

    Пустая строка или строка без букв даёт пустой кортеж. Для незнакомого слова
    анализатор возвращает саму форму — это нормальный случай для имён.
    """
    cleaned = clean_word(value)
    if not cleaned:
        return ()
    parsed = _analyzer().parse(cleaned)
    forms: list[WordForm] = []
    for item in parsed:
        pos = str(item.tag.POS) if item.tag.POS else None
        form = WordForm(normal_form=item.normal_form, pos=pos)
        if form not in forms:
            forms.append(form)
    return tuple(forms)


def lemmatize_word(value: str) -> str:
    """Нормальная форма слова (самый вероятный разбор) или само слово."""
    forms = word_forms(value)
    return forms[0].normal_form if forms else clean_word(value)


def lemmatize_words(words) -> list[str]:
    """Нормальные формы списка слов по порядку."""
    return [lemmatize_word(word) for word in words]


def split_words(text: str) -> list[str]:
    """Слова текста (буквы и цифры) по порядку, без пунктуации."""
    return [match.group(0) for match in _WORD_RE.finditer(text or "")]


def is_function_word(value: str) -> bool:
    """Служебное ли слово (предлог, союз, частица, междометие)."""
    return any(form.pos in FUNCTION_POS for form in word_forms(value))
