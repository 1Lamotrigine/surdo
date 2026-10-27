"""LLM-глоссы: провайдер, промпт, JSON-схема, словарь и кэш (этап F1).

Модуль чистый (без Django): его можно вызывать из фонового потока конвейера,
тестировать с моком LLM и позже вынести в отдельный воркер. Формат результата —
ТЗ 7.2 (``lang``, ``text``, ``sentence_type``, ``tokens``, ``unknown``).

Главные правила ТЗ 5.3, которые здесь закреплены:

* вывод модели ограничен JSON-схемой (:func:`gloss_response_schema`), поэтому
  клиент получает предсказуемый объект;
* глоссы берутся **только** из проверенного словаря
  (:class:`GlossDictionary`), всё остальное :func:`restrict_to_dictionary`
  превращает в ``fingerspell`` и добавляет в ``unknown``;
* повторы фраз бесплатны: результат кэшируется по хэшу фразы, языка и версии
  словаря (:class:`GlossCache`).

Запасной режим без LLM (pymorphy3) — этап F2, сжатие фраз — F3. Подключение к
конвейеру (`pipeline.gloss_engine`, F4) находится снаружи: этот модуль остаётся
чистым и не знает Django, БД и очередей.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from services.morphology import FUNCTION_POS, split_words, word_forms

# Типы предложения и маркеры из ТЗ 7.2. Маркеры управляют мимикой и поворотом
# головы аватара, поэтому неизвестные значения не пропускаются.
SENTENCE_TYPES = ("statement", "question", "exclamation", "imperative")
MARKERS = ("neg", "q-yn", "q-wh", "cond", "emph")
TOKEN_TYPES = ("sign", "number", "fingerspell")

# Сколько фраз держит кэш по умолчанию. Повторяющиеся фразы лекции («откройте
# учебник») не требуют нового обращения к LLM, а память ограничена.
DEFAULT_CACHE_SIZE = 512

# Дактиль: те же буквы, что в ``pipeline.glosses`` и ``frontend/dactyl.ts``.
_DACTYL_LETTERS = frozenset(
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
)
_LATIN_TO_CYRILLIC = {
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
}

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)
_NUMBER_RE = re.compile(r"^-?\d+$")

# Вводные обороты и слова-заполнители для сжатия без LLM (FR-16). Убираем
# только явный «мусор» устной речи, а не смысловые слова: «сегодня» и
# «теперь» могут быть важны для лекции и остаются.
_FILLER_PHRASES_RE = re.compile(
    r"(?<!\w)(?:"
    r"как (?:вы|все) знаете|"
    r"как известно|"
    r"на самом деле|"
    r"в общем(?:-то)?|"
    r"в принципе|"
    r"так сказать|"
    r"если можно|"
    r"будьте добры|"
    r"с вашего позволения|"
    r"обратите внимание|"
    r"хочу сказать|"
    r"хотелось бы отметить"
    r")(?!\w)",
    re.IGNORECASE,
)
_FILLER_WORDS_RE = re.compile(
    r"(?<!\w)(?:"
    r"ну|вот|итак|значит|короче|собственно|пожалуйста|ребята|друзья|"
    r"давайте|вроде|типа|кстати|во-первых|во-вторых|в-третьих|"
    r"просто"
    r")(?!\w)",
    re.IGNORECASE,
)


# Числительные словами: в глоссах число должно быть токеном ``number``, а не
# дактилем (ТЗ 7.2, пример «странице десять»). Формы даны как в тексте, включая
# родовые («одна», «две») и падежные варианты тысяч.
_NUMBER_WORDS = {
    "ноль": 0,
    "нуль": 0,
    "один": 1,
    "одна": 1,
    "одно": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "шестнадцать": 16,
    "семнадцать": 17,
    "восемнадцать": 18,
    "девятнадцать": 19,
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
    "сто": 100,
    "двести": 200,
    "триста": 300,
    "четыреста": 400,
    "пятьсот": 500,
    "шестьсот": 600,
    "семьсот": 700,
    "восемьсот": 800,
    "девятьсот": 900,
    "тысяча": 1000,
    "тысячи": 1000,
    "тысяч": 1000,
}



class GlossError(Exception):
    """Базовая ошибка модуля глосс."""


class GlossValidationError(GlossError, ValueError):
    """Входные данные или словарь не позволяют построить глоссы."""


class GlossFormatError(GlossError, ValueError):
    """Ответ LLM не соответствует JSON-схеме ТЗ 7.2."""


class LLMUnavailableError(GlossError):
    """Провайдер LLM недоступен или вернул ошибку."""


@runtime_checkable
class LLMProvider(Protocol):
    """Интерфейс провайдера LLM.

    Реализация получает готовый промпт и JSON-схему ответа, а возвращает строку
    (обычно JSON). Блокирующий вызов: в async-коде его запускают через
    ``asyncio.to_thread`` (F4), чтобы не останавливать цикл событий и чат.
    """

    def complete(
        self,
        prompt: str,
        *,
        schema: Mapping[str, Any],
        timeout: float | None = None,
    ) -> str:
        """Вернуть ответ модели на промпт по заданной JSON-схеме."""


@dataclass(frozen=True)
class CallableProvider:
    """Адаптер функции к интерфейсу ``LLMProvider`` (удобно для тестов)."""

    responder: Callable[..., str]
    name: str = "callable"

    def complete(
        self,
        prompt: str,
        *,
        schema: Mapping[str, Any],
        timeout: float | None = None,
    ) -> str:
        return self.responder(prompt, schema=schema, timeout=timeout)


@dataclass(frozen=True)
class GlossExample:
    """Пример «фраза → готовый объект глосс» для few-shot промпта."""

    text: str
    response: Mapping[str, Any]


@dataclass(frozen=True)
class GlossDictionary:
    """Словарь проверенных глосс одного языка и версии.

    ``version`` — номер версии словаря (``DictionaryVersion`` или строка):
    изменение словаря делает кэш фраз недействительным. ``glosses`` — только
    проверенные глоссы (FR-19); ``examples`` — few-shot пары от эксперта.
    """

    lang: str
    version: str
    glosses: tuple[str, ...]
    examples: tuple[GlossExample, ...] = ()
    _index: Mapping[str, str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        index: dict[str, str] = {}
        for gloss in self.glosses:
            normalized = normalize_gloss(gloss)
            if normalized:
                index.setdefault(normalized, gloss)
        object.__setattr__(self, "_index", index)

    @classmethod
    def from_glosses(
        cls,
        glosses: Sequence[str] | Mapping[str, str],
        *,
        lang: str,
        version: str | int,
        examples: Sequence[GlossExample] = (),
    ) -> GlossDictionary:
        """Собрать словарь из глосс (списка или отображения «ключ → глосса»)."""
        values = glosses.values() if isinstance(glosses, Mapping) else glosses
        # Порядок влияет только на промпт, но не на смысл: сортируем для
        # стабильного хэша кэша при одинаковом наборе глосс.
        unique = tuple(sorted({gloss for gloss in values if gloss}))
        return cls(
            lang=lang,
            version=str(version),
            glosses=unique,
            examples=tuple(examples),
        )

    def canonical(self, gloss: str) -> str | None:
        """Вернуть каноническую глоссу словаря или ``None``."""
        return self._index.get(normalize_gloss(gloss))

    def fingerprint(self) -> str:
        """Хэш содержимого словаря и примеров (для ключа кэша)."""
        payload = {
            "lang": self.lang,
            "version": self.version,
            "glosses": list(self.glosses),
            "examples": [
                {"text": example.text, "response": example.response}
                for example in self.examples
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_gloss(value: str) -> str:
    """Сравнимая форма глоссы: регистр, ё→е, без пунктуации и пробелов."""
    return re.sub(r"[^\w]+", "", (value or "").lower().replace("ё", "е"))


def _letters_for_word(value: str) -> list[str]:
    """Буквы/цифры слова для дактиля (верхний регистр, латиница → кириллица)."""
    letters: list[str] = []
    for raw in value or "":
        char = _LATIN_TO_CYRILLIC.get(raw.upper(), raw.upper())
        if char in _DACTYL_LETTERS or char.isdigit():
            letters.append(char)
    return letters


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split())


def _sentence_type_from_text(text: str) -> str:
    stripped = text.rstrip()
    if "?" in stripped:
        return "question"
    if stripped.endswith("!"):
        return "exclamation"
    return "statement"


def gloss_response_schema() -> dict:
    """JSON-схема ответа LLM (ТЗ 7.2, без серверного ``utterance_id``)."""
    markers = {"type": "array", "items": {"enum": list(MARKERS)}}
    base = {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "src", "markers"],
    }
    sign = {
        **base,
        "properties": {
            "type": {"const": "sign"},
            "gloss": {"type": "string", "minLength": 1},
            "src": {"type": "string", "minLength": 1},
            "markers": markers,
        },
        "required": ["type", "gloss", "src", "markers"],
    }
    number = {
        **base,
        "properties": {
            "type": {"const": "number"},
            "value": {"type": "integer"},
            "src": {"type": "string", "minLength": 1},
            "markers": markers,
        },
        "required": ["type", "value", "src", "markers"],
    }
    fingerspell = {
        **base,
        "properties": {
            "type": {"const": "fingerspell"},
            "letters": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "src": {"type": "string", "minLength": 1},
            "markers": markers,
        },
        "required": ["type", "letters", "src", "markers"],
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "RussianSignLanguageGlosses",
        "type": "object",
        "additionalProperties": False,
        "required": ["lang", "text", "sentence_type", "tokens", "unknown"],
        "properties": {
            "lang": {"type": "string"},
            "text": {"type": "string"},
            "sentence_type": {"enum": list(SENTENCE_TYPES)},
            "tokens": {
                "type": "array",
                "items": {"oneOf": [sign, number, fingerspell]},
            },
            "unknown": {"type": "array", "items": {"type": "string"}},
        },
    }


_GLOSS_RULES = """\
Ты — переводчик русской письменной речи в глоссы русского жестового языка (РЖЯ).
Верни только один JSON-объект по заданной схеме, без пояснений и markdown.

Правила:
1. Порядок токенов — порядок показа жестов; служебные слова (предлоги, союзы,
   частицы) можно опускать, если они не несут смысла.
2. Глоссы в токенах type="sign" выбирай ТОЛЬКО из списка проверенных глосс ниже.
   Если подходящей глоссы нет, сделай токен type="fingerspell" и перечисли буквы
   слова в letters (заглавные, без пробелов и пунктуации).
3. Числа, записанные цифрами или словами, дают токен type="number" с целым value.
4. Для каждого токена src — исходное слово фразы без изменений.
5. markers — только из списка: neg (отрицание), q-yn (общий вопрос),
   q-wh (вопрос с вопросительным словом), cond (условие), emph (акцент).
   У утвердительного токена markers — пустой список.
6. sentence_type — statement, question, exclamation или imperative.
7. unknown — слова без жеста (те же src, что у fingerspell), без повторов.
8. Поля lang и text повтори ровно как во входной фразе.
"""


def build_gloss_prompt(
    text: str,
    *,
    dictionary: GlossDictionary,
    examples: Sequence[GlossExample] | None = None,
) -> str:
    """Собрать промпт: правила, словарь, few-shot примеры и JSON-схему."""
    clean_text = _normalize_text(text)
    if not clean_text:
        raise GlossValidationError("Фраза для глосс не может быть пустой.")

    glosses = "\n".join(f"- {gloss}" for gloss in dictionary.glosses)
    if not glosses:
        glosses = "(словарь пуст: все значимые слова показывай дактилем)"

    example_items = dictionary.examples if examples is None else tuple(examples)
    blocks: list[str] = []
    for example in example_items:
        blocks.append(
            "Фраза: "
            + json.dumps(example.text, ensure_ascii=False)
            + "\nОтвет: "
            + json.dumps(example.response, ensure_ascii=False)
        )
    examples_block = "\n\n".join(blocks) if blocks else "(примеров нет)"

    schema = json.dumps(gloss_response_schema(), ensure_ascii=False, indent=2)
    return (
        f"{_GLOSS_RULES}\n"
        f"Язык жестов: {dictionary.lang}\n"
        f"Версия словаря: {dictionary.version}\n"
        f"Проверенные глоссы:\n{glosses}\n\n"
        f"Примеры:\n{examples_block}\n\n"
        f"JSON-схема ответа:\n{schema}\n\n"
        f"Фраза: {json.dumps(clean_text, ensure_ascii=False)}"
    )


def _strip_code_fences(raw: str) -> str:
    match = _FENCE_RE.match(raw or "")
    return match.group(1) if match else raw


def _normalize_markers(value: Any, *, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise GlossFormatError(f"{where}: markers должен быть списком.")
    result: list[str] = []
    for marker in value:
        if not isinstance(marker, str) or marker not in MARKERS:
            raise GlossFormatError(f"{where}: недопустимый маркер {marker!r}.")
        if marker not in result:
            result.append(marker)
    return result


def _normalize_number(value: Any, *, where: str) -> int:
    if isinstance(value, bool):
        raise GlossFormatError(f"{where}: value должен быть целым числом.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and _NUMBER_RE.match(value.strip()):
        return int(value.strip())
    raise GlossFormatError(f"{where}: value должен быть целым числом.")


def _normalize_token(raw: Any, *, index: int) -> dict:
    where = f"tokens[{index}]"
    if not isinstance(raw, dict):
        raise GlossFormatError(f"{where}: ожидался объект.")
    token_type = raw.get("type")
    if token_type not in TOKEN_TYPES:
        raise GlossFormatError(f"{where}: неизвестный type {token_type!r}.")

    src = raw.get("src")
    if not isinstance(src, str) or not src:
        raise GlossFormatError(f"{where}: src должен быть непустой строкой.")
    markers = _normalize_markers(raw.get("markers"), where=where)

    if token_type == "sign":
        gloss = raw.get("gloss")
        if not isinstance(gloss, str) or not gloss.strip():
            raise GlossFormatError(f"{where}: gloss должен быть непустой строкой.")
        return {"type": "sign", "gloss": gloss.strip(), "src": src, "markers": markers}

    if token_type == "number":
        return {
            "type": "number",
            "value": _normalize_number(raw.get("value"), where=where),
            "src": src,
            "markers": markers,
        }

    letters = raw.get("letters")
    if letters is None:
        # Модель может забыть letters: слово всё равно показывается дактилем.
        letters = _letters_for_word(src)
    if not isinstance(letters, list) or not letters:
        raise GlossFormatError(f"{where}: letters должен быть непустым списком.")
    normalized_letters: list[str] = []
    for letter in letters:
        if not isinstance(letter, str) or not letter.strip():
            raise GlossFormatError(f"{where}: буквы должны быть непустыми строками.")
        normalized_letters.append(letter.strip().upper())
    return {
        "type": "fingerspell",
        "letters": normalized_letters,
        "src": src,
        "markers": markers,
    }


def validate_glosses(
    payload: Any,
    *,
    text: str | None = None,
    lang: str | None = None,
) -> dict:
    """Проверить уже разобранный объект глосс и привести токены к норме.

    ``text``/``lang`` (если заданы) подставляются в результат: модель не должна
    менять исходную фразу, сервер ей доверяет только в глоссах.
    """
    if not isinstance(payload, dict):
        raise GlossFormatError("Ожидался JSON-объект глосс.")

    sentence_type = payload.get("sentence_type")
    if sentence_type not in SENTENCE_TYPES:
        raise GlossFormatError(
            f"Неизвестный sentence_type {sentence_type!r}: ожидается один из {SENTENCE_TYPES}."
        )

    raw_tokens = payload.get("tokens")
    if not isinstance(raw_tokens, list):
        raise GlossFormatError("Поле tokens должно быть списком.")
    tokens = [_normalize_token(item, index=index) for index, item in enumerate(raw_tokens)]

    raw_unknown = payload.get("unknown", [])
    if not isinstance(raw_unknown, list) or any(
        not isinstance(item, str) for item in raw_unknown
    ):
        raise GlossFormatError("Поле unknown должно быть списком строк.")
    unknown: list[str] = []
    for item in raw_unknown:
        if item and item not in unknown:
            unknown.append(item)

    result_lang = lang if lang is not None else payload.get("lang")
    if not isinstance(result_lang, str) or not result_lang:
        raise GlossFormatError("Поле lang должно быть непустой строкой.")
    result_text = text if text is not None else payload.get("text")
    if not isinstance(result_text, str) or not result_text:
        raise GlossFormatError("Поле text должно быть непустой строкой.")

    return {
        "lang": result_lang,
        "text": result_text,
        "sentence_type": sentence_type,
        "tokens": tokens,
        "unknown": unknown,
    }


def parse_gloss_response(raw: str, *, text: str, lang: str) -> dict:
    """Разобрать ответ LLM: допускается JSON в ```-блоке, но не «текст вокруг»."""
    if not isinstance(raw, str):
        raise GlossFormatError("Ответ LLM должен быть строкой JSON.")
    stripped = _strip_code_fences(raw).strip()
    try:
        payload = json.loads(stripped)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GlossFormatError("Ответ LLM не является JSON.") from exc
    return validate_glosses(payload, text=text, lang=lang)


def restrict_to_dictionary(glosses: Mapping[str, Any], dictionary: GlossDictionary) -> dict:
    """Оставить только глоссы словаря, остальные слова — дактиль (ТЗ 5.3).

    Модель может «придумать» глоссу или вернуть её в другом регистре. Здесь
    единственная точка правды — ``GlossDictionary``: неизвестная глосса
    превращается в ``fingerspell`` по ``src`` и попадает в ``unknown``.
    ``unknown`` пересобирается из токенов, а не берётся на веру из ответа LLM.
    """
    if glosses.get("lang") != dictionary.lang:
        raise GlossValidationError(
            f"Язык глосс {glosses.get('lang')!r} не совпадает со словарём "
            f"{dictionary.lang!r}."
        )

    tokens: list[dict] = []
    unknown: list[str] = []
    for token in glosses.get("tokens", []):
        if token["type"] == "sign":
            canonical = dictionary.canonical(token["gloss"])
            if canonical is not None:
                tokens.append({**token, "gloss": canonical})
                continue
            token = {
                "type": "fingerspell",
                "letters": _letters_for_word(token["src"]),
                "src": token["src"],
                "markers": token.get("markers", []),
            }

        tokens.append(token)
        if token["type"] == "fingerspell" and token["src"] not in unknown:
            unknown.append(token["src"])

    return {
        "lang": glosses["lang"],
        "text": glosses["text"],
        "sentence_type": glosses["sentence_type"],
        "tokens": tokens,
        "unknown": unknown,
    }


def fallback_glosses(
    text: str,
    lang: str,
    dictionary_version: GlossDictionary,
) -> dict:
    """Запасной режим без LLM: лемматизация и пословный перевод (F2).

    Слово ищется в словаре сначала в исходной форме, затем по нормальным формам
    ``pymorphy3`` («учебнике» → «учебник»). Числительные словами становятся
    токеном ``number``, остальные значимые слова — ``fingerspell`` и попадают в
    ``unknown``. Служебные части речи (предлоги, союзы, частицы, междометия)
    без жеста опускаются: в жестовой фразе они не показываются. Для казахского
    жестового языка русская морфология не применяется — только точная форма.
    """
    clean_text = _normalize_text(text)
    if not clean_text:
        raise GlossValidationError("Фраза для глосс не может быть пустой.")
    if lang != dictionary_version.lang:
        raise GlossValidationError(
            f"Язык {lang!r} не совпадает с языком словаря {dictionary_version.lang!r}."
        )

    tokens: list[dict] = []
    unknown: list[str] = []
    for word in split_words(clean_text):
        if word.isdigit():
            tokens.append({"type": "number", "value": int(word), "src": word, "markers": []})
            continue
        numeral = _NUMBER_WORDS.get(normalize_gloss(word))
        if numeral is not None:
            tokens.append(
                {"type": "number", "value": numeral, "src": word, "markers": []}
            )
            continue

        forms = word_forms(word) if dictionary_version.lang == "rsl" else ()
        canonical = dictionary_version.canonical(word)
        if canonical is None:
            for form in forms:
                canonical = dictionary_version.canonical(form.normal_form)
                if canonical is not None:
                    break

        if canonical is not None:
            tokens.append(
                {"type": "sign", "gloss": canonical, "src": word, "markers": []}
            )
            continue
        if any(form.pos in FUNCTION_POS for form in forms):
            continue

        tokens.append(
            {
                "type": "fingerspell",
                "letters": _letters_for_word(word),
                "src": word,
                "markers": [],
            }
        )
        if word not in unknown:
            unknown.append(word)

    return {
        "lang": lang,
        "text": clean_text,
        "sentence_type": _sentence_type_from_text(clean_text),
        "tokens": tokens,
        "unknown": unknown,
    }


def compress_response_schema() -> dict:
    """JSON-схема ответа LLM для сжатия фразы (FR-16)."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "CompressedUtterance",
        "type": "object",
        "additionalProperties": False,
        "required": ["text"],
        "properties": {"text": {"type": "string", "minLength": 1}},
    }


def _validate_compress_ratio(target_ratio: float) -> float:
    if isinstance(target_ratio, bool) or not isinstance(target_ratio, (int, float)):
        raise GlossValidationError("target_ratio должен быть числом от 0 до 1.")
    ratio = float(target_ratio)
    if not 0 < ratio < 1:
        raise GlossValidationError("target_ratio должен быть больше 0 и меньше 1.")
    return ratio


def _target_length(length: int, target_ratio: float) -> int:
    return max(1, int(length * target_ratio))


def _clean_fillers(text: str) -> str:
    """Убрать вводные обороты, слова-заполнители и лишние пробелы."""
    result = _FILLER_PHRASES_RE.sub(" ", text)
    result = _FILLER_WORDS_RE.sub(" ", result)
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"\s+([,.;:!?])", r"\1", result)
    result = re.sub(r"([,.;:!?])(?:\s*[,.;:!?])+", r"\1", result)
    result = result.strip(" ,;:—-")
    if result:
        result = result[0].upper() + result[1:]
    return result


def build_compress_prompt(text: str, target_ratio: float) -> str:
    """Собрать промпт для LLM: сократить фразу до целевой длины."""
    clean_text = _normalize_text(text)
    if not clean_text:
        raise GlossValidationError("Фраза для сжатия не может быть пустой.")
    ratio = _validate_compress_ratio(target_ratio)
    target = _target_length(len(clean_text), ratio)
    schema = json.dumps(compress_response_schema(), ensure_ascii=False, indent=2)
    return (
        "Ты сокращаешь фразу преподавателя для перевода на русский жестовый язык.\n"
        "Убери вводные слова, повторы, обращения, вежливые обороты и пояснения, "
        "которые не меняют смысл. Сохрани порядок мыслей, числа и ключевые слова. "
        "Не добавляй новую информацию и не пересказывай другими словами без нужды.\n"
        f"Целевая длина — не более {target} символов "
        f"(около {ratio:.0%} исходной фразы).\n"
        "Верни только JSON-объект с полем text, без markdown и пояснений.\n\n"
        f"JSON-схема ответа:\n{schema}\n\n"
        f"Фраза: {json.dumps(clean_text, ensure_ascii=False)}"
    )


def parse_compress_response(raw: str) -> str:
    """Разобрать ответ LLM: JSON ``{"text": "..."}``, допускается ```-блок."""
    if not isinstance(raw, str):
        raise GlossFormatError("Ответ LLM для сжатия должен быть строкой JSON.")
    stripped = _strip_code_fences(raw).strip()
    try:
        payload = json.loads(stripped)
    except (json.JSONDecodeError, TypeError) as exc:
        raise GlossFormatError("Ответ LLM для сжатия не является JSON.") from exc
    if not isinstance(payload, dict):
        raise GlossFormatError("Ожидался JSON-объект с полем text.")
    result = payload.get("text")
    if not isinstance(result, str) or not result.strip():
        raise GlossFormatError("Поле text должно быть непустой строкой.")
    return result.strip()


def _trim_to_target(text: str, target: int) -> str:
    """Обрезать текст по границе слова, не длиннее ``target`` (если возможно)."""
    words = text.split()
    selected: list[str] = []
    for word in words:
        candidate = " ".join([*selected, word])
        if selected and len(candidate) > target:
            break
        selected.append(word)
    trimmed = " ".join(selected).strip(" ,;:—-")
    return trimmed or (words[0][:target] if words else "")


def compress_locally(text: str, target_ratio: float) -> str:
    """Детерминированное сжатие без LLM: вводные слова и обрезка по цели.

    Используется как резерв, если LLM недоступна, ответила ошибкой или вернула
    текст не короче исходного. Для фразы из одного короткого слова сжимать
    нечего — возвращается она же.
    """
    clean_text = _normalize_text(text)
    if not clean_text:
        raise GlossValidationError("Фраза для сжатия не может быть пустой.")
    ratio = _validate_compress_ratio(target_ratio)
    target = _target_length(len(clean_text), ratio)

    reduced = _clean_fillers(clean_text)
    if not reduced:
        reduced = clean_text
    if len(reduced) <= target:
        return reduced if len(reduced) < len(clean_text) else clean_text

    trimmed = _trim_to_target(reduced, target)
    return trimmed if 0 < len(trimmed) < len(clean_text) else clean_text


def compress(
    text: str,
    target_ratio: float,
    *,
    provider: LLMProvider | None = None,
    timeout: float | None = None,
) -> str:
    """Сжать длинную фразу (FR-16, ``services.gloss.compress``).

    Сначала пробует LLM с промптом «убери вводные». Если провайдер не настроен,
    упал или вернул текст не короче исходного, используется детерминированное
    локальное сжатие. Для непустой длинной фразы результат всегда короче
    исходной; короткую фразу из одного слова сжать невозможно — она остаётся
    как есть.
    """
    clean_text = _normalize_text(text)
    if not clean_text:
        raise GlossValidationError("Фраза для сжатия не может быть пустой.")
    ratio = _validate_compress_ratio(target_ratio)
    provider = provider or _default_provider

    if provider is not None:
        prompt = build_compress_prompt(clean_text, ratio)
        try:
            raw = provider.complete(
                prompt, schema=compress_response_schema(), timeout=timeout
            )
            candidate = parse_compress_response(raw)
        except Exception:  # noqa: BLE001 — сбой LLM не должен ломать управление отставанием
            candidate = ""
        if 0 < len(candidate) < len(clean_text):
            return candidate

    return compress_locally(clean_text, ratio)


class GlossCache:
    """Потокобезопасный LRU-кэш результатов по хэшу фразы.

    В памяти процесса, как и очереди конвейера (ТЗ 5.7: один процесс uvicorn).
    Это дёшево и не требует Redis; если позже понадобится общий кэш между
    процессами, интерфейс ``get``/``set`` можно реализовать поверх
    ``django.core.cache``, не меняя ``to_glosses``.
    """

    def __init__(self, maxsize: int = DEFAULT_CACHE_SIZE) -> None:
        self.maxsize = max(1, maxsize)
        self._items: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            value = self._items.get(key)
            if value is None:
                return None
            self._items.move_to_end(key)
            return copy.deepcopy(value)

    def set(self, key: str, value: Mapping[str, Any]) -> None:
        with self._lock:
            self._items[key] = copy.deepcopy(dict(value))
            self._items.move_to_end(key)
            while len(self._items) > self.maxsize:
                self._items.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


DEFAULT_CACHE = GlossCache()


def gloss_cache_key(
    text: str,
    lang: str,
    dictionary: GlossDictionary,
    *,
    examples: Sequence[GlossExample] | None = None,
) -> str:
    """Хэш фразы для кэша: текст + язык + версия/содержимое словаря."""
    example_items = dictionary.examples if examples is None else tuple(examples)
    payload = {
        "text": _normalize_text(text),
        "lang": lang,
        "dictionary": dictionary.fingerprint(),
        "examples": [
            {"text": example.text, "response": example.response}
            for example in example_items
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_default_provider: LLMProvider | None = None


def set_default_provider(provider: LLMProvider | None) -> None:
    """Задать провайдера по умолчанию (его настраивает интеграция F4)."""
    global _default_provider
    _default_provider = provider


def get_default_provider() -> LLMProvider | None:
    return _default_provider


def to_glosses(
    text: str,
    lang: str,
    dictionary_version: GlossDictionary,
    *,
    provider: LLMProvider | None = None,
    cache: GlossCache | None = None,
    timeout: float | None = None,
    examples: Sequence[GlossExample] | None = None,
) -> dict:
    """Фраза → объект глосс через LLM (ТЗ 7.1, 5.3).

    ``dictionary_version`` — :class:`GlossDictionary` с проверенными глоссами и
    версией. Результат проверяется схемой и ограничивается словарём; валидный
    ответ кэшируется по хэшу фразы (включая язык, словарь и примеры). Ошибка
    провайдера или формата не кэшируется — следующий вызов попробует снова.
    """
    clean_text = _normalize_text(text)
    if not clean_text:
        raise GlossValidationError("Фраза для глосс не может быть пустой.")
    if lang != dictionary_version.lang:
        raise GlossValidationError(
            f"Язык {lang!r} не совпадает с языком словаря {dictionary_version.lang!r}."
        )

    provider = provider or _default_provider
    if provider is None:
        raise LLMUnavailableError("Провайдер LLM не настроен.")

    cache = cache if cache is not None else DEFAULT_CACHE
    key = gloss_cache_key(clean_text, lang, dictionary_version, examples=examples)
    cached = cache.get(key)
    if cached is not None:
        return cached

    prompt = build_gloss_prompt(clean_text, dictionary=dictionary_version, examples=examples)
    try:
        raw = provider.complete(prompt, schema=gloss_response_schema(), timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — любую ошибку провайдера показываем единообразно
        raise LLMUnavailableError(f"LLM недоступна: {exc}") from exc

    parsed = parse_gloss_response(raw, text=clean_text, lang=lang)
    result = restrict_to_dictionary(parsed, dictionary_version)
    cache.set(key, result)
    return copy.deepcopy(result)
