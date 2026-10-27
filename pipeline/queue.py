"""Фоновые очереди фраз: одна очередь и один обработчик на комнату.

E2: HTTP-запрос принимает текст и ставит его в очередь, не выполняя обработку в
цикле событий ASGI. Требования ТЗ 5.7:

- фразы одной комнаты обрабатываются строго по порядку — у комнаты один
  ``asyncio.Queue`` и одна задача-обработчик;
- разные комнаты обрабатываются параллельно, но число одновременно работающих
  тяжёлых задач ограничено глобальным семафором (``ASR_MAX_CONCURRENCY``);
- очередь комнаты ограничена (``ROOM_QUEUE_MAX``): при переполнении самые старые
  ещё не начатые фразы пропускаются.

Очереди хранятся в памяти процесса, поэтому в проде запускается один процесс
uvicorn. Цикл событий очереди живёт в отдельном daemon-потоке: Django-вью —
синхронная функция и не может создать долгоживущую задачу в цикле запроса
(в тестах и у WSGI-сервера такой цикл закрывается вместе с запросом). Так
обработка не зависит от того, кто и когда вызвал ``submit``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime

from channels.db import database_sync_to_async
from django.conf import settings
from django.db import connections
from django.utils import timezone

from pipeline.events import broadcast_asr_text, broadcast_utterance
from pipeline.gloss_engine import compute_glosses_async
from pipeline.models import Utterance
from pipeline.services import (
    create_utterance,
    normalize_text,
    sign_language_for_utterance,
)

logger = logging.getLogger(__name__)


class RoomQueueFullError(RuntimeError):
    """Самая старая необработанная фраза комнаты выброшена из очереди."""


@dataclass(frozen=True)
class TextJob:
    """Задание на обработку одной текстовой фразы."""

    room_id: int
    text: str
    lang: str | None = None
    asr_ms: int | None = None
    started_at: datetime | None = None
    # Результат для тестов и диагностики; в HTTP-ответе не используется.
    future: concurrent.futures.Future = field(
        default_factory=concurrent.futures.Future,
        compare=False,
        repr=False,
    )


def _prepare_job(job: TextJob):
    """Синхронная часть перед LLM: комната, текст, язык и время старта."""
    from rooms.models import Room

    room = Room.objects.get(pk=job.room_id)
    return (
        room,
        normalize_text(job.text),
        sign_language_for_utterance(room, job.lang),
        job.started_at or timezone.now(),
    )


async def process_text_job_async(job: TextJob) -> Utterance:
    """Обработать фразу без блокировки цикла очереди (F4).

    E3: сначала в комнату уходит распознанный текст (``asr_text``), затем —
    сохранённая фраза с глоссами и ссылками на клипы (``utterance``). Глоссы
    получает ``pipeline.gloss_engine``: LLM вызывается в ``asyncio.to_thread``
    с таймаутом ``LLM_TIMEOUT``. Если LLM настроена и упала/зависла, сохраняем
    только субтитры с ``degraded=True``; если не настроена — работает F2.
    """
    broadcast_asr_text(job.room_id, job.text)
    try:
        room, clean_text, sign_lang, started_at = await database_sync_to_async(
            _prepare_job
        )(job)
        outcome = await compute_glosses_async(clean_text, sign_lang)
        utterance = await database_sync_to_async(create_utterance)(
            room,
            clean_text,
            lang=sign_lang,
            asr_ms=job.asr_ms,
            started_at=started_at,
            glosses=outcome.glosses,
            gloss_ms=outcome.elapsed_ms,
            degraded=outcome.degraded,
        )
        # Сборка клипов и рассылка обращаются к БД, поэтому тоже уходят из loop.
        await database_sync_to_async(broadcast_utterance)(utterance)
        return utterance
    finally:
        # Цикл очереди живёт всё время работы процесса; не держим соединение
        # фонового потока открытым между редкими фразами.
        await database_sync_to_async(connections.close_all)()


def process_text_job(job: TextJob) -> Utterance:
    """Синхронная обёртка F4 для прямых вызовов и старых обработчиков.

    Очередь по умолчанию использует :func:`process_text_job_async`, чтобы
    таймаут LLM не ждал завершения зависшего потока. Эта обёртка нужна тестам и
    коду, который исторически вызывает обработчик из своего потока.
    """
    return asyncio.run(process_text_job_async(job))


class PipelineQueue:
    """Очереди фраз по комнатам поверх одного фонового цикла событий."""

    def __init__(
        self,
        *,
        processor=process_text_job_async,
        max_concurrency: int | None = None,
        room_queue_max: int | None = None,
    ) -> None:
        self._processor = processor
        self._max_concurrency = max(
            1,
            max_concurrency if max_concurrency is not None else settings.ASR_MAX_CONCURRENCY,
        )
        self._room_queue_max = max(
            1,
            room_queue_max if room_queue_max is not None else settings.ROOM_QUEUE_MAX,
        )
        self._queues: dict[int, asyncio.Queue[TextJob]] = {}
        self._workers: dict[int, asyncio.Task] = {}
        self._semaphore: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    @property
    def room_queue_max(self) -> int:
        return self._room_queue_max

    def submit(
        self,
        room_id: int,
        text: str,
        *,
        lang: str | None = None,
        asr_ms: int | None = None,
        started_at: datetime | None = None,
    ) -> concurrent.futures.Future:
        """Поставить фразу в очередь комнаты и сразу вернуть управление.

        Возвращается ``Future``: он завершится сохранённой ``Utterance`` или
        ошибкой. HTTP-вью результат не ждёт; future нужен тестам и логам.
        """
        job = TextJob(
            room_id=room_id,
            text=text,
            lang=lang,
            asr_ms=asr_ms,
            started_at=started_at,
        )
        loop = self._ensure_loop()
        loop.call_soon_threadsafe(self._enqueue, job)
        return job.future

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run_loop,
                args=(loop,),
                daemon=True,
                name="pipeline-queue",
            )
            self._loop = loop
            self._thread = thread
            thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Не удалось запустить цикл обработки фраз.")
        return loop

    def _run_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _enqueue(self, job: TextJob) -> None:
        """Выполняется в фоновом цикле: создать очередь комнаты или дополнить её."""
        queue = self._queues.get(job.room_id)
        if queue is None:
            queue = asyncio.Queue(maxsize=self._room_queue_max)
            self._queues[job.room_id] = queue
            self._workers[job.room_id] = asyncio.create_task(
                self._worker(job.room_id, queue),
                name=f"pipeline-room-{job.room_id}",
            )

        if queue.full():
            dropped = queue.get_nowait()
            queue.task_done()
            dropped.future.set_exception(
                RoomQueueFullError("Очередь комнаты переполнена: фраза пропущена.")
            )
            logger.warning(
                "phrase queue full: room=%s dropped=%r", job.room_id, dropped.text[:80]
            )

        queue.put_nowait(job)

    async def _worker(self, room_id: int, queue: asyncio.Queue[TextJob]) -> None:
        """Последовательно обрабатывать фразы одной комнаты."""
        assert self._semaphore is not None
        try:
            while True:
                job = await queue.get()
                try:
                    async with self._semaphore:
                        if inspect.iscoroutinefunction(self._processor):
                            result = await self._processor(job)
                        else:
                            # Старые синхронные обработчики и тестовые функции
                            # по-прежнему уходят в пул потоков.
                            result = await asyncio.to_thread(self._processor, job)
                            if inspect.isawaitable(result):
                                result = await result
                    job.future.set_result(result)
                except Exception as exc:  # обработчик не должен убивать воркер
                    if not job.future.done():
                        job.future.set_exception(exc)
                    logger.exception("phrase processing failed: room=%s", room_id)
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            self._queues.pop(room_id, None)
            self._workers.pop(room_id, None)

    def close(self) -> None:
        """Остановить фоновый цикл (тесты, завершение процесса)."""
        with self._lock:
            loop = self._loop
            thread = self._thread
            self._loop = None
            self._thread = None
        if loop is None or thread is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)

    def wait_for_idle(self, timeout: float = 5) -> None:
        """Дождаться, пока все комнаты опустеют (тесты, диагностика)."""
        loop = self._loop
        if loop is None:
            return
        # Проверяем через фоновый цикл, чтобы не читать asyncio.Queue из чужого
        # потока: join() у каждой очереди дождётся task_done().
        done = threading.Event()
        loop.call_soon_threadsafe(self._wait_queues, done)
        done.wait(timeout)

    def _wait_queues(self, done: threading.Event) -> None:
        async def waiter() -> None:
            try:
                await asyncio.gather(*(queue.join() for queue in self._queues.values()))
            finally:
                done.set()

        asyncio.create_task(waiter())


_default_queue: PipelineQueue | None = None
_default_lock = threading.Lock()


def get_pipeline_queue() -> PipelineQueue:
    """Общая очередь процесса (лениво, чтобы импорт не запускал поток)."""
    global _default_queue
    with _default_lock:
        if _default_queue is None:
            _default_queue = PipelineQueue()
        return _default_queue


def submit_text(
    room_id: int,
    text: str,
    *,
    lang: str | None = None,
    asr_ms: int | None = None,
    started_at: datetime | None = None,
) -> concurrent.futures.Future:
    """Поставить текстовую фразу в общую очередь процесса."""
    return get_pipeline_queue().submit(
        room_id,
        text,
        lang=lang,
        asr_ms=asr_ms,
        started_at=started_at,
    )
