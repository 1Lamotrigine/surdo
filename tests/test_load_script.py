"""Тесты скрипта нагрузки G3: пороги, перцентили и разбор URL.

Сам прогон требует запущенного сервера, поэтому проверяется чистая часть:
подсчёт перцентилей, оценка порогов, формат адреса и поиск PID. Импорт скрипта
не поднимает Django — `django.setup()` вызывается только при подготовке данных.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "load_test.py"


@pytest.fixture(scope="module")
def load_test():
    """Загрузить модуль скрипта по пути (scripts/ не пакет)."""
    spec = importlib.util.spec_from_file_location("load_test_script", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_percentile_nearest_rank(load_test):
    report = load_test.LoadReport(clients=0)
    values = [10.0, 20.0, 30.0, 40.0, 50.0]

    assert report.percentile(values, 0.0) == 10.0
    assert report.percentile(values, 0.5) == 30.0
    assert report.percentile(values, 1.0) == 50.0


def test_percentile_empty_is_zero(load_test):
    assert load_test.LoadReport(clients=0).percentile([], 0.95) == 0.0


def test_evaluate_passes_within_thresholds(load_test):
    report = load_test.LoadReport(clients=3, connected=3)
    report.connect_ms = [10.0, 12.0, 15.0]
    report.chat_ms = [100.0, 120.0, 150.0]

    assert load_test.evaluate(report) == []


def test_evaluate_flags_missing_clients(load_test):
    report = load_test.LoadReport(clients=30, connected=28)

    problems = load_test.evaluate(report)

    assert any("28 из 30" in problem for problem in problems)


def test_evaluate_flags_slow_chat_delivery(load_test):
    report = load_test.LoadReport(clients=3, connected=3)
    report.connect_ms = [10.0] * 3
    # Медиана выше 4 с.
    report.chat_ms = [5_000.0, 5_100.0, 6_000.0]

    problems = load_test.evaluate(report)

    assert any("медиана доставки" in problem for problem in problems)


def test_evaluate_flags_slow_connect(load_test):
    report = load_test.LoadReport(clients=2, connected=2)
    report.connect_ms = [3_500.0, 3_600.0]
    report.chat_ms = [50.0, 60.0]

    problems = load_test.evaluate(report)

    assert any("p95 подключения" in problem for problem in problems)


def test_websocket_url_scheme_and_host(load_test):
    assert load_test.websocket_url("http://localhost:8000", "ABC234") == (
        "ws://localhost:8000/ws/rooms/ABC234/"
    )
    assert load_test.websocket_url("https://lecture.example", "XYZ999") == (
        "wss://lecture.example/ws/rooms/XYZ999/"
    )


def test_host_from_url_strips_scheme_and_port(load_test):
    assert load_test.host_from_url("http://localhost:8000") == "localhost"
    assert load_test.host_from_url("https://example.org/") == "example.org"


def test_human_bytes(load_test):
    assert load_test.human_bytes(0) == "0.0 Б"
    assert load_test.human_bytes(1024) == "1.0 КиБ"
    assert load_test.human_bytes(1024 * 1024) == "1.0 МиБ"


def test_process_rss_bytes_for_current_process(load_test):
    size = load_test.process_rss_bytes(os.getpid())

    assert size is not None and size > 0


def test_memory_watcher_prefers_host_pid(load_test, monkeypatch):
    monkeypatch.setattr(load_test, "process_rss_bytes", lambda pid: 111)
    monkeypatch.setattr(load_test, "container_rss_bytes", lambda name: 222)

    watcher = load_test.MemoryWatcher(pid=1, container="web")

    assert watcher.read() == 111


def test_memory_watcher_falls_back_to_container(load_test, monkeypatch):
    monkeypatch.setattr(load_test, "process_rss_bytes", lambda pid: None)
    monkeypatch.setattr(load_test, "container_rss_bytes", lambda name: 222)

    watcher = load_test.MemoryWatcher(pid=1, container="web")

    assert watcher.read() == 222


def test_memory_watcher_returns_none_without_sources(load_test):
    assert load_test.MemoryWatcher(pid=None, container=None).read() is None


def test_rss_growth_from_report(load_test):
    report = load_test.LoadReport(clients=1, connected=1)
    report.rss_start_bytes = 10_000
    report.rss_peak_bytes = 12_500

    assert report.rss_growth_bytes == 2_500
    assert report.summary()["rss_growth_bytes"] == 2_500


def test_evaluate_flags_memory_growth(load_test):
    report = load_test.LoadReport(clients=1, connected=1)
    report.connect_ms = [10.0]
    report.chat_ms = [20.0]
    report.rss_start_bytes = 50 * 1024 * 1024
    report.rss_peak_bytes = 120 * 1024 * 1024

    problems = load_test.evaluate(report, max_rss_growth_bytes=64 * 1024 * 1024)

    assert any("рост памяти" in problem for problem in problems)


def test_evaluate_ignores_memory_when_no_limit(load_test):
    report = load_test.LoadReport(clients=1, connected=1)
    report.connect_ms = [10.0]
    report.chat_ms = [20.0]
    report.rss_start_bytes = 10
    report.rss_peak_bytes = 10_000_000

    assert load_test.evaluate(report) == []
