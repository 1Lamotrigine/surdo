"""Распознавание речи: faster-whisper за интерфейсом и пул потоков (F5).

ТЗ 7.1 задаёт контракт ``services.asr.transcribe(audio, lang) -> AsrResult``:
на вход байты одной фразы (WAV/Opus, 16 кГц, mono), на выход текст и
длительность аудио. Реализация по умолчанию — `faster-whisper`, но интерфейс
``AsrProvider`` позволяет подменить её внешним API или моком в тестах.

Тяжёлая модель загружается **лениво и один раз** на процесс. Вызовы идут через
отдельный ``ThreadPoolExecutor`` с ``BoundedSemaphore``: цикл событий не
блокируется, а одновременно распознаётся не больше ``ASR_MAX_CONCURRENCY`` фраз.
Аудио живёт только в памяти и никуда не сохраняется.
"""

from __future__ import annotations

import asyncio
import io
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings


class AsrError(RuntimeError):
    """Базовая ошибка распознавания речи."""


class AsrValidationError(AsrError, ValueError):
    """Аудио или язык не подходят для распознавания."""


class AsrUnavailableError(AsrError):
    """faster-whisper не установлен или модель не загрузилась."""


class AsrTimeoutError(AsrError):
    """Распознавание не уложилось в отведённое время."""


@dataclass(frozen=True)
class AsrResult:
    """Результат распознавания одной фразы.

    ``duration_ms`` — длительность исходного аудио, а не время работы модели;
    время распознавания измеряет конвейер (``Utterance.asr_ms``).
    """

    text: str
    duration_ms: int
    language: str = ""


class AsrProvider(Protocol):
    """Контракт распознавателя: байты аудио и язык → текст."""

    def transcribe(self, audio: bytes, lang: str) -> AsrResult:
        """Распознать одну фразу."""


# Язык комнаты/жестов → язык речи для Whisper. В комнате хранится ``ru``/``kk``,
# но сервис принимает и обозначения языков жестов, чтобы F6 не дублировал
# преобразование.
_SPOKEN_LANG_BY_CODE = {
    "ru": "ru",
    "kk": "kk",
    "rsl": "ru",
    "ksl": "kk",
}
_SPOKEN_LANGUAGES = frozenset({"ru", "kk"})


def normalize_language(lang: str) -> str:
    """Привести язык к коду Whisper (``ru``/``kk``) или отказать."""
    code = (lang or "").strip().lower()
    code = _SPOKEN_LANG_BY_CODE.get(code, code)
    if code not in _SPOKEN_LANGUAGES:
        raise AsrValidationError(f"Язык распознавания не поддерживается: {lang!r}.")
    return code


def _load_whisper_model(
    model_size: str,
    *,
    device: str,
    compute_type: str,
) -> Any:
    """Импортировать faster-whisper только при первой реальной фразе."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover — зависит от окружения
        raise AsrUnavailableError(
            "faster-whisper не установлен: выполните pip install -r requirements.txt."
        ) from exc
    return WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
    )


class FasterWhisperProvider:
    """Ленивая реализация ``AsrProvider`` поверх faster-whisper.

    ``model_factory`` существует для тестов и внешних адаптеров: по умолчанию
    импортируется ``faster_whisper.WhisperModel``. Модель создаётся под замком
    ровно один раз, поэтому параллельные первые фразы не загрузят её дважды.
    """

    def __init__(
        self,
        *,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.model_size = (
            model_size if model_size is not None else settings.WHISPER_MODEL
        ).strip()
        if not self.model_size:
            raise AsrValidationError("WHISPER_MODEL не может быть пустым.")
        self.device = (
            device if device is not None else settings.WHISPER_DEVICE
        ).strip().lower()
        if self.device not in {"cpu", "cuda", "auto"}:
            raise AsrValidationError(
                f"WHISPER_DEVICE должен быть cpu, cuda или auto, а не {self.device!r}."
            )
        self.compute_type = (
            compute_type
            if compute_type is not None
            else self._default_compute_type(self.device)
        )
        self._model_factory = model_factory or _load_whisper_model
        self._model: Any | None = None
        self._model_lock = threading.Lock()

    @staticmethod
    def _default_compute_type(device: str) -> str:
        if device == "cpu":
            return "int8"
        if device == "cuda":
            return "float16"
        return "default"

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is None:
                try:
                    self._model = self._model_factory(
                        self.model_size,
                        device=self.device,
                        compute_type=self.compute_type,
                    )
                except AsrError:
                    raise
                except Exception as exc:
                    raise AsrUnavailableError(
                        f"Не удалось загрузить модель распознавания {self.model_size!r}."
                    ) from exc
        return self._model

    def transcribe(self, audio: bytes, lang: str) -> AsrResult:
        """Распознать WAV/Opus в памяти; модель загрузится при первом вызове."""
        if not isinstance(audio, (bytes, bytearray, memoryview)):
            raise AsrValidationError("Аудио должно быть байтами.")
        payload = bytes(audio)
        if not payload:
            raise AsrValidationError("Аудио фразы пустое.")
        language = normalize_language(lang)
        model = self._get_model()

        try:
            segments, info = model.transcribe(
                io.BytesIO(payload),
                language=language,
                task="transcribe",
                beam_size=5,
                best_of=5,
                vad_filter=False,
                condition_on_previous_text=False,
                without_timestamps=True,
            )
            text = " ".join(
                part
                for segment in segments
                if (part := str(getattr(segment, "text", "")).strip())
            )
        except AsrError:
            raise
        except Exception as exc:
            raise AsrError("Не удалось распознать аудио фразы.") from exc

        duration = getattr(info, "duration", 0.0)
        try:
            duration_ms = max(0, round(float(duration or 0.0) * 1000))
        except (TypeError, ValueError):
            duration_ms = 0
        detected = getattr(info, "language", None) or language
        return AsrResult(
            text=text,
            duration_ms=duration_ms,
            language=str(detected),
        )


class AsrService:
    """Пул потоков и семафор вокруг ``AsrProvider``.

    Свой executor нужен, чтобы ограничение ASR не смешивалось с другими
    ``asyncio.to_thread`` задачами. ``transcribe_async`` удобен конвейеру F6,
    синхронный ``transcribe`` — тестам и скриптам.
    """

    def __init__(
        self,
        *,
        provider: AsrProvider | None = None,
        max_concurrency: int | None = None,
    ) -> None:
        self.provider = provider or FasterWhisperProvider()
        limit = (
            max_concurrency
            if max_concurrency is not None
            else getattr(settings, "ASR_MAX_CONCURRENCY", 1)
        )
        self.max_concurrency = max(1, int(limit))
        self._semaphore = threading.BoundedSemaphore(self.max_concurrency)
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrency,
            thread_name_prefix="asr",
        )
        self._closed = False
        self._close_lock = threading.Lock()

    def _validate(self, audio: bytes, lang: str) -> tuple[bytes, str]:
        if not isinstance(audio, (bytes, bytearray, memoryview)):
            raise AsrValidationError("Аудио должно быть байтами.")
        payload = bytes(audio)
        if not payload:
            raise AsrValidationError("Аудио фразы пустое.")
        return payload, normalize_language(lang)

    def _run(self, audio: bytes, language: str) -> AsrResult:
        with self._semaphore:
            try:
                result = self.provider.transcribe(audio, language)
            except AsrError:
                raise
            except Exception as exc:
                raise AsrError("Распознавание речи завершилось ошибкой.") from exc
        if not isinstance(result, AsrResult):
            raise AsrError("Провайдер ASR вернул не AsrResult.")
        return result

    def submit(self, audio: bytes, lang: str) -> Future[AsrResult]:
        """Поставить фразу в пул и вернуть ``Future`` без ожидания."""
        payload, language = self._validate(audio, lang)
        if self._closed:
            raise AsrUnavailableError("Пул распознавания уже остановлен.")
        return self._executor.submit(self._run, payload, language)

    def transcribe(
        self,
        audio: bytes,
        lang: str,
        *,
        timeout: float | None = None,
    ) -> AsrResult:
        """Синхронно распознать фразу через пул."""
        future = self.submit(audio, lang)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise AsrTimeoutError(
                f"Распознавание не уложилось в {timeout} с."
            ) from exc

    async def transcribe_async(
        self,
        audio: bytes,
        lang: str,
        *,
        timeout: float | None = None,
    ) -> AsrResult:
        """Распознать фразу, не блокируя цикл событий."""
        future = self.submit(audio, lang)
        wrapped = asyncio.wrap_future(future)
        try:
            if timeout is None:
                return await wrapped
            return await asyncio.wait_for(wrapped, timeout)
        except TimeoutError as exc:
            future.cancel()
            raise AsrTimeoutError(
                f"Распознавание не уложилось в {timeout} с."
            ) from exc
        except asyncio.CancelledError:
            future.cancel()
            raise

    def close(self, *, wait: bool = True) -> None:
        """Остановить пул. Повторный вызов безопасен."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._executor.shutdown(wait=wait, cancel_futures=True)

    def __enter__(self) -> AsrService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


_default_service: AsrService | None = None
_default_lock = threading.Lock()


def get_asr_service() -> AsrService:
    """Ленивый общий сервис распознавания на процесс."""
    global _default_service
    if _default_service is None:
        with _default_lock:
            if _default_service is None:
                _default_service = AsrService()
    return _default_service


def set_asr_provider(provider: AsrProvider) -> AsrService:
    """Подменить провайдера по умолчанию (тесты, внешний ASR)."""
    global _default_service
    with _default_lock:
        previous = _default_service
        _default_service = AsrService(provider=provider)
        service = _default_service
    if previous is not None:
        previous.close(wait=False)
    return service


def reset_asr_service() -> None:
    """Забыть общий сервис; следующий вызов создаст его заново."""
    global _default_service
    with _default_lock:
        previous = _default_service
        _default_service = None
    if previous is not None:
        previous.close(wait=False)


def transcribe(
    audio: bytes,
    lang: str,
    *,
    timeout: float | None = None,
) -> AsrResult:
    """Контракт ТЗ 7.1: распознать фразу общим сервисом."""
    return get_asr_service().transcribe(audio, lang, timeout=timeout)


async def transcribe_async(
    audio: bytes,
    lang: str,
    *,
    timeout: float | None = None,
) -> AsrResult:
    """Асинхронный вариант ``transcribe`` для конвейера фраз."""
    return await get_asr_service().transcribe_async(audio, lang, timeout=timeout)
