"""HTTP-провайдеры LLM для конвейера глосс (F4).

Модуль реализует интерфейс ``services.gloss.LLMProvider`` на стандартной
библиотеке: без новых зависимостей и без сетевых вызовов при импорте. Поддержаны
два варианта из ТЗ 5.3:

* ``openai`` — любой OpenAI-compatible endpoint chat completions;
* ``ollama`` — локальная Ollama (``/api/chat``).

Провайдер создаётся только если в настройках заданы модель и, для API, ключ.
Иначе ``provider_from_settings`` возвращает ``None``, и конвейер честно уходит
в упрощённый режим F2, не пытаясь ходить в сеть.
"""

from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OPENAI_PROVIDERS = frozenset({"openai", "openai-compatible", "api"})


class LLMRequestError(RuntimeError):
    """HTTP-запрос к LLM не удался или ответ не разобрался."""


class HttpLLMProvider:
    """Провайдер LLM через HTTP без сторонних библиотек.

    ``provider`` — ``openai`` (OpenAI-compatible chat completions) или
    ``ollama``. Блокирующий ``complete`` вызывается из ``asyncio.to_thread`` в
    ``pipeline.gloss_engine``; таймаут передаётся и в ``urlopen``, и в
    ``asyncio.wait_for`` на уровне конвейера.
    """

    def __init__(
        self,
        provider: str,
        *,
        model: str,
        api_key: str = "",
        api_url: str = "",
        timeout: float = 8.0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        if provider in OPENAI_PROVIDERS:
            self.api_url = api_url or OPENAI_URL
        else:
            self.api_url = api_url or OLLAMA_URL
        self.timeout = max(0.001, float(timeout))
        self.name = f"{provider}:{model}"

    def _payload(self, prompt: str, schema: dict) -> dict:
        if self.provider in OPENAI_PROVIDERS:
            return {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                # Схема уже в промпте; json_object включает строгий JSON-режим
                # у тех OpenAI-compatible моделей, которые его поддерживают.
                "response_format": {"type": "json_object"},
            }
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
        }

    def _extract_content(self, body: str) -> str:
        try:
            payload = json.loads(body)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LLMRequestError("LLM вернула не JSON.") from exc
        if not isinstance(payload, dict):
            raise LLMRequestError("LLM вернула JSON не-объект.")

        if self.provider in OPENAI_PROVIDERS:
            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices:
                raise LLMRequestError("В ответе LLM нет choices.")
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
        else:
            message = payload.get("message")
            content = message.get("content") if isinstance(message, dict) else None

        if not isinstance(content, str) or not content.strip():
            raise LLMRequestError("LLM вернула пустой ответ.")
        return content

    def complete(
        self,
        prompt: str,
        *,
        schema: dict,
        timeout: float | None = None,
    ) -> str:
        """Отправить промпт и вернуть текстовый JSON-ответ модели."""
        effective_timeout = self.timeout if timeout is None else max(0.001, float(timeout))
        data = json.dumps(
            self._payload(prompt, schema), ensure_ascii=False
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.api_url, data=data, headers=headers, method="POST")

        try:
            with urlopen(request, timeout=effective_timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(300).decode("utf-8", errors="replace").strip()
            except Exception:  # noqa: BLE001 — тело ошибки не обязательно доступно
                detail = ""
            message = f"LLM HTTP {exc.code}"
            if detail:
                message = f"{message}: {detail}"
            raise LLMRequestError(message) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise LLMRequestError(f"LLM недоступна: {exc}") from exc

        return self._extract_content(body)


def provider_from_settings() -> HttpLLMProvider | None:
    """Собрать провайдера из Django-настроек или вернуть ``None``.

    Без модели провайдер бесполезен, а для OpenAI-compatible API нужен ещё и
    ключ. Неизвестный ``LLM_PROVIDER`` также выключает LLM, чтобы опечатка в
    конфигурации не приводила к запросам на чужой endpoint.
    """
    from django.conf import settings

    provider = str(getattr(settings, "LLM_PROVIDER", "") or "").strip().lower()
    model = str(getattr(settings, "LLM_MODEL", "") or "").strip()
    api_key = str(getattr(settings, "LLM_API_KEY", "") or "").strip()
    api_url = str(getattr(settings, "LLM_API_URL", "") or "").strip()
    timeout = float(getattr(settings, "LLM_TIMEOUT", 8.0) or 8.0)

    if not provider or not model:
        return None
    if provider in OPENAI_PROVIDERS:
        if not api_key:
            logger.info("LLM_PROVIDER=%s задан без LLM_API_KEY: упрощённый режим", provider)
            return None
        return HttpLLMProvider(
            provider,
            model=model,
            api_key=api_key,
            api_url=api_url,
            timeout=timeout,
        )
    if provider == "ollama":
        return HttpLLMProvider(
            "ollama",
            model=model,
            api_key=api_key,
            api_url=api_url,
            timeout=timeout,
        )

    logger.warning("Неизвестный LLM_PROVIDER=%r: упрощённый режим", provider)
    return None
