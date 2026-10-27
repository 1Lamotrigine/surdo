"""Очередь фраз E2: порядок комнаты, параллелизм и переполнение."""

import threading
import time

import pytest

from pipeline.queue import PipelineQueue, RoomQueueFullError


@pytest.fixture
def make_queue():
    queues: list[PipelineQueue] = []

    def factory(**kwargs):
        queue = PipelineQueue(**kwargs)
        queues.append(queue)
        return queue

    yield factory

    for queue in queues:
        queue.close()


def test_one_room_runs_jobs_in_order(make_queue):
    processed: list[str] = []

    def processor(job):
        time.sleep(0.01)
        processed.append(job.text)
        return job.text

    queue = make_queue(processor=processor, max_concurrency=2)
    futures = [queue.submit(1, f"фраза-{i}") for i in range(5)]

    assert [future.result(timeout=5) for future in futures] == [
        "фраза-0",
        "фраза-1",
        "фраза-2",
        "фраза-3",
        "фраза-4",
    ]
    assert processed == ["фраза-0", "фраза-1", "фраза-2", "фраза-3", "фраза-4"]


def test_rooms_run_in_parallel_when_limit_allows(make_queue):
    barrier = threading.Barrier(2, timeout=5)

    def processor(job):
        barrier.wait()
        return job.room_id

    queue = make_queue(processor=processor, max_concurrency=2)
    first = queue.submit(1, "первая")
    second = queue.submit(2, "вторая")

    assert first.result(timeout=5) == 1
    assert second.result(timeout=5) == 2


def test_global_concurrency_limit(make_queue):
    state = {"active": 0, "max": 0}
    lock = threading.Lock()

    def processor(job):
        with lock:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        time.sleep(0.05)
        with lock:
            state["active"] -= 1
        return job.text

    queue = make_queue(processor=processor, max_concurrency=1)
    futures = [queue.submit(room, f"фраза-{room}") for room in range(3)]

    for future in futures:
        future.result(timeout=5)

    assert state["max"] == 1


def test_full_room_queue_drops_oldest_waiting_job(make_queue):
    started = threading.Event()
    release = threading.Event()
    processed: list[str] = []

    def processor(job):
        if job.text == "первая":
            started.set()
            release.wait(timeout=5)
        processed.append(job.text)
        return job.text

    queue = make_queue(processor=processor, max_concurrency=1, room_queue_max=2)
    first = queue.submit(1, "первая")
    assert started.wait(timeout=5)

    second = queue.submit(1, "вторая")
    third = queue.submit(1, "третья")
    fourth = queue.submit(1, "четвёртая")
    release.set()

    assert first.result(timeout=5) == "первая"
    assert third.result(timeout=5) == "третья"
    assert fourth.result(timeout=5) == "четвёртая"
    with pytest.raises(RoomQueueFullError):
        second.result(timeout=5)
    assert processed == ["первая", "третья", "четвёртая"]


def test_failed_job_does_not_stop_room_worker(make_queue):
    def processor(job):
        if job.text == "плохая":
            raise ValueError("сломалось")
        return job.text

    queue = make_queue(processor=processor)
    bad = queue.submit(1, "плохая")
    good = queue.submit(1, "хорошая")

    with pytest.raises(ValueError):
        bad.result(timeout=5)
    assert good.result(timeout=5) == "хорошая"


def test_wait_for_idle_returns_after_processing(make_queue):
    processed = threading.Event()

    def processor(job):
        time.sleep(0.02)
        processed.set()
        return job.text

    queue = make_queue(processor=processor)
    queue.submit(1, "фраза")

    queue.wait_for_idle(timeout=5)

    assert processed.is_set()
