"""Движок глосс конвейера F4: словарь из БД, LLM, таймаут и деградация.

Здесь заканчивается чистая часть ``services.gloss`` и начинается интеграция:

1. Собираем ``GlossDictionary`` только из проверенных жестов текущей версии
   словаря языка (FR-19).
2. Если LLM настроена, вызываем ``to_glosses``; блокирующий HTTP-запрос уходит
   в ``asyncio.to_thread``, а общий предел ожидания задаёт ``LLM_TIMEOUT``.
3. Если LLM не настроена — честно переходим в упрощённый режим F2
   (``fallback_glosses``) и помечаем фразу ``degraded``.
4. Если настроенная LLM упала, вернула мусор или не уложилась в таймаут —
   оставляем только субтитры: пустые ``tokens`` и ``degraded=True`` (ТЗ 5.7).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import perf_counter

from channels.db import database_sync_to_async
from django.conf import settings
from django.db import connections

from dictionary.models import DictionaryVersion, Language, Sign, SignStatus
from pipeline.glosses import sentence_type
from services.gloss import (
    GlossDictionary,
    GlossError,
    GlossValidationError,
    LLMProvider,
    fallback_glosses,
    get_default_provider,
    to_glosses,
)
from services.llm import provider_from_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GlossOutcome:
    """Результат получения глосс и причина возможной деградации.

    ``source``: ``llm`` — ответ модели; ``fallback`` — упрощённый режим F2;
    ``subtitles`` — ошибка/битый ответ настроенной LLM; ``timeout`` —
    превышен ``LLM_TIMEOUT``. ``error`` нужен для логов и тестов, в событие
    ``utterance`` он не попадает.
    """

    glosses: dict
    degraded: bool
    source: str
    elapsed_ms: int
    error: str | None = None


def get_llm_provider() -> LLMProvider | None:
    """Провайдер из тестов/настроек или ``None`` для упрощённого режима."""
    return get_default_provider() or provider_from_settings()


def verified_gloss_dictionary(lang: str) -> GlossDictionary:
    """Текущий словарь проверенных жестов языка для промпта LLM."""
    if lang not in Language.values:
        raise GlossValidationError(f"Неизвестный язык жестов: {lang}.")
    version = DictionaryVersion.current(lang)
    glosses = Sign.objects.filter(
        lang=lang,
        status=SignStatus.VERIFIED,
    ).values_list("gloss", flat=True)
    return GlossDictionary.from_glosses(
        list(glosses),
        lang=lang,
        version=version.number if version is not None else 0,
    )


def subtitle_only_glosses(text: str, lang: str) -> dict:
    """Объект глосс без жестов: клиент покажет только субтитры."""
    return {
        "lang": lang,
        "text": text,
        "sentence_type": sentence_type(text),
        "tokens": [],
        "unknown": [],
    }


def _clean_text(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise GlossValidationError("Фраза для глосс не может быть пустой.")
    return cleaned


def _resolve_timeout(timeout: float | None) -> float:
    value = getattr(settings, "LLM_TIMEOUT", 8.0) if timeout is None else timeout
    return max(0.001, float(value))


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _compute_with_dictionary(
    clean_text: str,
    lang: str,
    dictionary: GlossDictionary,
    provider: LLMProvider | None,
    timeout: float | None,
) -> GlossOutcome:
    """Часть без БД: LLM, F2-резерв или только субтитры.

    Выполняется в ``asyncio.to_thread`` в async-пути, поэтому не трогает ORM и
    не оставляет соединений с БД в потоке пула.
    """
    started = perf_counter()

    if provider is None:
        try:
            glosses = fallback_glosses(clean_text, lang, dictionary)
        except Exception as exc:  # noqa: BLE001 — субтитры лучше падения конвейера
            logger.exception("fallback glosses failed: lang=%s", lang)
            return GlossOutcome(
                subtitle_only_glosses(clean_text, lang),
                degraded=True,
                source="subtitles",
                elapsed_ms=_elapsed_ms(started),
                error=str(exc),
            )
        return GlossOutcome(
            glosses,
            degraded=True,
            source="fallback",
            elapsed_ms=_elapsed_ms(started),
        )

    try:
        glosses = to_glosses(
            clean_text,
            lang,
            dictionary,
            provider=provider,
            timeout=_resolve_timeout(timeout),
        )
    except GlossError as exc:
        logger.warning("LLM glosses degraded: %s", exc)
        return GlossOutcome(
            subtitle_only_glosses(clean_text, lang),
            degraded=True,
            source="subtitles",
            elapsed_ms=_elapsed_ms(started),
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — ошибка LLM не должна ронять очередь
        logger.exception("LLM glosses failed: lang=%s", lang)
        return GlossOutcome(
            subtitle_only_glosses(clean_text, lang),
            degraded=True,
            source="subtitles",
            elapsed_ms=_elapsed_ms(started),
            error=str(exc),
        )

    return GlossOutcome(
        glosses,
        degraded=False,
        source="llm",
        elapsed_ms=_elapsed_ms(started),
    )


def compute_glosses(
    text: str,
    lang: str,
    *,
    provider: LLMProvider | None = None,
    timeout: float | None = None,
) -> GlossOutcome:
    """Синхронно получить глоссы: словарь из БД, LLM, F2 или субтитры.

    Функция блокирующая (ходит в сеть и БД), поэтому в async-коде её вызывает
    только ``compute_glosses_async``, причём БД читается отдельно.
    """
    clean_text = _clean_text(text)
    dictionary = verified_gloss_dictionary(lang)
    provider = provider or get_llm_provider()
    return _compute_with_dictionary(clean_text, lang, dictionary, provider, timeout)


async def compute_glosses_async(
    text: str,
    lang: str,
    *,
    provider: LLMProvider | None = None,
    timeout: float | None = None,
) -> GlossOutcome:
    """Получить глоссы, не блокируя цикл событий, с жёстким таймаутом.

    Словарь читается через ``database_sync_to_async``, а блокирующий
    HTTP-запрос LLM уходит в ``asyncio.to_thread``. ``asyncio.wait_for``
    гарантирует, что фраза будет показана субтитрами даже если провайдер
    завис. Просроченный поток доработает в фоне, его результат отброшен.
    """
    clean_text = _clean_text(text)
    effective_timeout = _resolve_timeout(timeout)
    started = perf_counter()
    try:
        dictionary = await database_sync_to_async(verified_gloss_dictionary)(lang)
        effective_provider = provider or get_llm_provider()
        return await asyncio.wait_for(
            asyncio.to_thread(
                _compute_with_dictionary,
                clean_text,
                lang,
                dictionary,
                effective_provider,
                effective_timeout,
            ),
            effective_timeout,
        )
    except TimeoutError:
        logger.warning(
            "LLM glosses timeout: lang=%s timeout=%.3fs", lang, effective_timeout
        )
        return GlossOutcome(
            subtitle_only_glosses(clean_text, lang),
            degraded=True,
            source="timeout",
            elapsed_ms=_elapsed_ms(started),
            error=f"LLM не ответила за {effective_timeout:.3f} с",
        )
    except Exception as exc:  # noqa: BLE001 — конвейер не должен падать из-за LLM
        logger.exception("gloss computation failed: lang=%s", lang)
        return GlossOutcome(
            subtitle_only_glosses(clean_text, lang),
            degraded=True,
            source="subtitles",
            elapsed_ms=_elapsed_ms(started),
            error=str(exc),
        )
    finally:
        # Словарь читался в потоке asgiref; не оставляем там соединение
        # висеть между фразами.
        await database_sync_to_async(connections.close_all)()
