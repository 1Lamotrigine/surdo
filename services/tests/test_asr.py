"""F5: faster-whisper за интерфейсом, WAV в памяти, пул потоков и семафор."""

from __future__ import annotations

import asyncio
import io
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest

from services.asr import (
    AsrError,
    AsrResult,
    AsrService,
    AsrValidationError,
    FasterWhisperProvider,
    reset_asr_service,
    set_asr_provider,
    transcribe,
)


def short_wav(duration_ms: int = 120, framerate: int = 16_000) -> bytes:
    """Валидный короткий WAV 16 кГц mono: тишина нужной длительности."""
    frames = round(framerate * duration_ms / 1000)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(framerate)
        writer.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


@dataclass
class FakeSegment:
    text: str


@dataclass
class FakeInfo:
    duration: float
    language: str = "ru"


class FakeWhisperModel:
    def __init__(self, *, duration: float = 0.12, texts: tuple[str, ...] = ("Привет", "мир.")):
        self.duration = duration
        self.texts = texts
        self.calls: list[dict] = []

    def transcribe(self, audio, **kwargs):
        self.calls.append({"audio": audio.read(), **kwargs})
        segments = [FakeSegment(text) for text in self.texts]
        return iter(segments), FakeInfo(self.duration)


def factory_for(model: FakeWhisperModel):
    created: list[dict] = []

    def factory(name: str, **kwargs):
        created.append({"name": name, **kwargs})
        return model

    return factory, created


def test_short_wav_is_transcribed_and_model_is_loaded_once():
    wav = short_wav()
    model = FakeWhisperModel()
    factory, created = factory_for(model)
    provider = FasterWhisperProvider(
        model_size="tiny",
        device="cpu",
        model_factory=factory,
    )

    first = provider.transcribe(wav, "ru")
    second = provider.transcribe(wav, "rsl")

    assert first == AsrResult(text="Привет мир.", duration_ms=120, language="ru")
    assert second == first
    assert provider.model_loaded is True
    assert len(created) == 1
    # `cpu_threads` передаётся всегда: CTranslate2 иначе берёт один поток.
    assert created[0] == {
        "name": "tiny",
        "device": "cpu",
        "compute_type": "int8",
        "cpu_threads": provider.cpu_threads,
    }
    assert len(model.calls) == 2
    assert model.calls[0]["audio"] == wav
    assert model.calls[0]["language"] == "ru"
    assert model.calls[1]["language"] == "ru"
    assert model.calls[0]["vad_filter"] is False
    assert model.calls[0]["condition_on_previous_text"] is False
    # Жадное декодирование: задержка важнее доли процента точности.
    assert model.calls[0]["beam_size"] == 1


def test_model_factory_is_called_once_under_parallel_first_calls():
    model = FakeWhisperModel()
    created = []

    def factory(name: str, **kwargs):
        created.append(name)
        time.sleep(0.05)
        return model

    provider = FasterWhisperProvider(
        model_size="tiny",
        device="cpu",
        model_factory=factory,
    )
    wav = short_wav()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: provider.transcribe(wav, "ru"), range(4)))

    assert len(created) == 1
    assert all(result.text == "Привет мир." for result in results)


def test_cuda_uses_float16_and_auto_uses_default_compute_type():
    cuda_factory, cuda_created = factory_for(FakeWhisperModel())
    auto_factory, auto_created = factory_for(FakeWhisperModel())
    FasterWhisperProvider(
        model_size="small", device="cuda", model_factory=cuda_factory
    ).transcribe(short_wav(), "ru")
    FasterWhisperProvider(
        model_size="small", device="auto", model_factory=auto_factory
    ).transcribe(short_wav(), "ru")

    assert cuda_created[0]["compute_type"] == "float16"
    assert auto_created[0]["compute_type"] == "default"


@pytest.mark.parametrize("audio", [b"", bytearray(), memoryview(b"")])
def test_empty_audio_is_rejected(audio):
    provider = FasterWhisperProvider(
        model_size="tiny", model_factory=factory_for(FakeWhisperModel())[0]
    )

    with pytest.raises(AsrValidationError, match="пустое"):
        provider.transcribe(audio, "ru")


@pytest.mark.parametrize("lang", ["", "en", "de", "xx"])
def test_unsupported_language_is_rejected(lang):
    provider = FasterWhisperProvider(
        model_size="tiny", model_factory=factory_for(FakeWhisperModel())[0]
    )

    with pytest.raises(AsrValidationError, match="не поддерживается"):
        provider.transcribe(short_wav(), lang)


def test_provider_warm_up_loads_model_once():
    """F5: прогрев загружает модель, но не распознаёт аудио."""
    model = FakeWhisperModel()
    factory, created = factory_for(model)
    provider = FasterWhisperProvider(model_size="tiny", model_factory=factory)

    provider.warm_up()
    provider.warm_up()

    assert provider.model_loaded is True
    assert len(created) == 1
    assert model.calls == []


def test_service_warm_up_uses_provider_and_tolerates_plain_provider():
    """Сервис прогревает провайдер, если тот это умеет."""

    class WarmProvider:
        def __init__(self) -> None:
            self.warmed = 0

        def warm_up(self) -> None:
            self.warmed += 1

        def transcribe(self, audio: bytes, lang: str) -> AsrResult:
            return AsrResult(text="", duration_ms=0, language=lang)

    provider = WarmProvider()
    service = AsrService(provider=provider, max_concurrency=1)
    try:
        assert service.warm_up(timeout=2) is True
        assert provider.warmed == 1
    finally:
        service.close()

    # Провайдер без warm_up не считается ошибкой: грузить нечего.
    plain = AsrService(provider=TrackingProvider(delay=0), max_concurrency=1)
    try:
        assert plain.warm_up(timeout=2) is False
    finally:
        plain.close()


def test_whisper_failure_is_wrapped_as_asr_error():
    class BrokenModel:
        def transcribe(self, audio, **kwargs):
            raise RuntimeError("ctranslate2 упал")

    provider = FasterWhisperProvider(
        model_size="tiny", model_factory=lambda *args, **kwargs: BrokenModel()
    )

    with pytest.raises(AsrError, match="распознать"):
        provider.transcribe(short_wav(), "ru")


class TrackingProvider:
    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = 0

    def transcribe(self, audio: bytes, lang: str) -> AsrResult:
        with self.lock:
            self.active += 1
            self.calls += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        return AsrResult(text="Учебник", duration_ms=100, language=lang)


def test_thread_pool_and_semaphore_limit_parallel_transcriptions():
    provider = TrackingProvider()
    service = AsrService(provider=provider, max_concurrency=2)
    try:
        futures = [service.submit(short_wav(), "ru") for _ in range(6)]
        results = [future.result(timeout=3) for future in futures]
    finally:
        service.close()

    assert len(results) == 6
    assert provider.calls == 6
    assert provider.max_active == 2


def test_async_transcription_does_not_block_event_loop():
    ticks = 0
    service = AsrService(provider=TrackingProvider(delay=0.15), max_concurrency=1)

    async def scenario():
        nonlocal ticks

        async def ticker():
            nonlocal ticks
            for _ in range(10):
                await asyncio.sleep(0.01)
                ticks += 1

        ticker_task = asyncio.create_task(ticker())
        result = await service.transcribe_async(short_wav(), "ru", timeout=2)
        await ticker_task
        return result

    try:
        result = asyncio.run(scenario())
    finally:
        service.close()

    assert result.text == "Учебник"
    assert ticks == 10


def test_module_transcribe_uses_configured_provider():
    class FakeProvider:
        def transcribe(self, audio: bytes, lang: str) -> AsrResult:
            return AsrResult(text="Лекция", duration_ms=90, language=lang)

    set_asr_provider(FakeProvider())
    try:
        result = transcribe(short_wav(), "ru", timeout=2)
    finally:
        reset_asr_service()

    assert result.text == "Лекция"
    assert result.duration_ms == 90


def test_service_rejects_audio_after_close():
    service = AsrService(
        provider=TrackingProvider(delay=0),
        max_concurrency=1,
    )
    service.close()

    with pytest.raises(AsrError, match="остановлен"):
        service.submit(short_wav(), "ru")
