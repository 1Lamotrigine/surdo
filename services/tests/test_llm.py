"""F4: HTTP-провайдеры LLM и выбор провайдера из настроек."""

from __future__ import annotations

import json
from urllib.error import URLError

import pytest
from django.test import override_settings

from services.llm import HttpLLMProvider, LLMRequestError, provider_from_settings


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def read(self) -> bytes:
        return self.body.encode("utf-8")


@override_settings(
    LLM_PROVIDER="openai",
    LLM_MODEL="",
    LLM_API_KEY="",
    LLM_API_URL="",
    LLM_TIMEOUT=8,
)
def test_provider_is_not_created_without_model():
    assert provider_from_settings() is None


@override_settings(
    LLM_PROVIDER="openai",
    LLM_MODEL="gpt-test",
    LLM_API_KEY="",
    LLM_API_URL="",
    LLM_TIMEOUT=8,
)
def test_openai_provider_requires_api_key():
    assert provider_from_settings() is None


@override_settings(
    LLM_PROVIDER="openai",
    LLM_MODEL="gpt-test",
    LLM_API_KEY="secret",
    LLM_API_URL="https://llm.example/v1/chat/completions",
    LLM_TIMEOUT=2.5,
)
def test_openai_provider_is_built_from_settings():
    provider = provider_from_settings()

    assert provider is not None
    assert provider.provider == "openai"
    assert provider.model == "gpt-test"
    assert provider.api_key == "secret"
    assert provider.api_url == "https://llm.example/v1/chat/completions"
    assert provider.timeout == 2.5


@override_settings(
    LLM_PROVIDER="ollama",
    LLM_MODEL="qwen-test",
    LLM_API_KEY="",
    LLM_API_URL="",
    LLM_TIMEOUT=4,
)
def test_ollama_provider_does_not_require_key_and_uses_local_url():
    provider = provider_from_settings()

    assert provider is not None
    assert provider.provider == "ollama"
    assert provider.api_url == "http://127.0.0.1:11434/api/chat"


@override_settings(
    LLM_PROVIDER="unknown",
    LLM_MODEL="model",
    LLM_API_KEY="key",
    LLM_API_URL="",
    LLM_TIMEOUT=8,
)
def test_unknown_provider_disables_llm():
    assert provider_from_settings() is None


def test_openai_request_contains_prompt_schema_and_auth(monkeypatch):
    calls: dict = {}

    def fake_urlopen(request, timeout=None):
        calls["request"] = request
        calls["timeout"] = timeout
        return FakeResponse(
            json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]})
        )

    monkeypatch.setattr("services.llm.urlopen", fake_urlopen)
    provider = HttpLLMProvider(
        "openai",
        model="gpt-test",
        api_key="secret",
        api_url="https://llm.example/chat",
        timeout=7,
    )

    result = provider.complete("Верни JSON", schema={"type": "object"}, timeout=3.5)

    assert result == '{"ok": true}'
    assert calls["timeout"] == 3.5
    request = calls["request"]
    assert request.full_url == "https://llm.example/chat"
    assert request.get_header("Authorization") == "Bearer secret"
    payload = json.loads(request.data)
    assert payload["messages"] == [{"role": "user", "content": "Верни JSON"}]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["model"] == "gpt-test"


def test_ollama_request_passes_json_schema(monkeypatch):
    calls: dict = {}

    def fake_urlopen(request, timeout=None):
        calls["request"] = request
        return FakeResponse(json.dumps({"message": {"content": '{"ok": true}'}}))

    monkeypatch.setattr("services.llm.urlopen", fake_urlopen)
    provider = HttpLLMProvider("ollama", model="qwen-test", timeout=7)
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}

    result = provider.complete("Верни JSON", schema=schema)

    assert result == '{"ok": true}'
    payload = json.loads(calls["request"].data)
    assert payload["format"] == schema
    assert payload["stream"] is False
    assert "response_format" not in payload


@pytest.mark.parametrize(
    "body",
    [
        "не json",
        "[]",
        '{"choices": []}',
        '{"choices": [{"message": {"content": ""}}]}',
    ],
)
def test_openai_broken_response_raises(monkeypatch, body):
    monkeypatch.setattr(
        "services.llm.urlopen", lambda request, timeout=None: FakeResponse(body)
    )
    provider = HttpLLMProvider("openai", model="m", api_key="k")

    with pytest.raises(LLMRequestError):
        provider.complete("prompt", schema={"type": "object"})


def test_http_failure_is_wrapped(monkeypatch):
    def broken(request, timeout=None):
        raise URLError("нет сети")

    monkeypatch.setattr("services.llm.urlopen", broken)
    provider = HttpLLMProvider("openai", model="m", api_key="k")

    with pytest.raises(LLMRequestError, match="недоступна"):
        provider.complete("prompt", schema={"type": "object"})
