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

Запасной режим без LLM (pymorphy3) — этап F2, сжатие фраз — F3, подключение к
конвейеру — F4. Здесь только интерфейс и проверка ответа.
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
