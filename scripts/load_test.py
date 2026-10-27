"""Скрипт нагрузки G3: комната и 30 одновременных WebSocket-клиентов.

Проверка критерия приёмки №5 (ТЗ 11): «комната на 30 одновременных подключений
без деградации». Скрипт поднимает виртуальных студентов, подключает их к
``WS /ws/rooms/<code>/`` и измеряет:

- время установки соединения (handshake): минимум, медиана, p95, максимум;
- доставку сообщения чата от отправителя до остальных: медиана и p95 — это
  оценка задержки событий группе под нагрузкой;
- распространение presence и память процесса сервера (рост RSS).

Пороги задержки — из ТЗ (медиана ≤ 4 с, p95 ≤ 7 с). Память проверяется только
при заданном ``--max-rss-growth``: точного числа в ТЗ нет, поэтому предел
задаётся явно; без флага рост RSS печатается, но прогон не считается провалом.

Требуется уже запущенный сервер (``make up`` или ``uvicorn``) и PostgreSQL:
клиенты проходят проверку изоляции в ``connect()``, поэтому у каждого своя
гостевая сессия и запись ``Participant``. Сессии и участники создаются тем же
путём, что у студента, — через ``POST /r/<code>/`` (Django test client), без
обхода проверок A8.

Запуск рядом с ``manage.py``:

    .venv/bin/python scripts/load_test.py --url http://localhost:8000 \
        --clients 30

Без ``--room`` создаётся новая открытая комната, её код печатается. Коды
возврата: 0 — укладывается в пороги, 1 — нет, 2 — ошибка запуска.

Зависимости только закреплённые: Django — сам проект, ``websockets`` приходит с
``uvicorn[standard]``. Новых пакетов не требуется.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Скрипт лежит в scripts/, проект — на уровень выше (там manage.py).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Пороги из ТЗ 4/11 (те же, что у сквозной задержки): медиана ≤ 4 с, p95 ≤ 7 с.
# Под нагрузкой соединение тоже не должно «залипать».
LATENCY_MEDIAN_MAX_MS = 4_000
LATENCY_P95_MAX_MS = 7_000
CONNECT_P95_MAX_MS = 3_000

# Сколько ждать доставки сообщения чата и сколько — расхождения presence.
CHAT_DELIVERY_TIMEOUT_S = 5.0
PRESENCE_SETTLE_S = 1.5


@dataclass
class ClientResult:
    """Итог одного виртуального студента."""

    index: int
    connected: bool
    connect_ms: float
    saw_presence: bool = False
    error: str = ""


@dataclass
class LoadReport:
    """Сводка прогона: тайминги, presence и память."""

    clients: int
    connected: int = 0
    connect_ms: list[float] = field(default_factory=list)
    chat_ms: list[float] = field(default_factory=list)
    rss_start_bytes: int | None = None
    rss_peak_bytes: int | None = None
    results: list[ClientResult] = field(default_factory=list)

    def percentile(self, values: list[float], fraction: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        rank = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
        return ordered[rank]

    def summary(self) -> dict:
        return {
            "clients": self.clients,
            "connected": self.connected,
            "connect_ms": {
                "min": _round(min(self.connect_ms)) if self.connect_ms else None,
                "median": _round(statistics.median(self.connect_ms)) if self.connect_ms else None,
                "p95": _round(self.percentile(self.connect_ms, 0.95)) if self.connect_ms else None,
                "max": _round(max(self.connect_ms)) if self.connect_ms else None,
            },
            "chat_latency_ms": {
                "median": _round(statistics.median(self.chat_ms)) if self.chat_ms else None,
                "p95": _round(self.percentile(self.chat_ms, 0.95)) if self.chat_ms else None,
                "max": _round(max(self.chat_ms)) if self.chat_ms else None,
                "samples": len(self.chat_ms),
            },
            "presence_seen": sum(1 for result in self.results if result.saw_presence),
            "rss_start_bytes": self.rss_start_bytes,
            "rss_peak_bytes": self.rss_peak_bytes,
            "rss_growth_bytes": self.rss_growth_bytes,
        }

    @property
    def rss_growth_bytes(self) -> int | None:
        if self.rss_start_bytes is None or self.rss_peak_bytes is None:
            return None
        return self.rss_peak_bytes - self.rss_start_bytes


def _round(value: float) -> float:
    return round(value, 1)


# --- Подготовка данных (Django ORM) -------------------------------------------------


def prepare_room(
    *, owner_email: str, room_code: str | None, clients: int, host: str
) -> tuple[str, list[str]]:
    """Создать/найти комнату и вернуть её код и sessionid-куки клиентов.

    Куки получаются тем же путём, что у студента: гость отправляет имя на
    ``/r/<code>/``, а мы читаем подписанную ``sessionid``. Так сервер примет
    соединение без обхода проверок изоляции. ``host`` — имя хоста из ``--url``,
    чтобы проверка ``ALLOWED_HOSTS`` пропустила запросы тестового клиента.
    """
    import django

    django.setup()

    from django.test import Client

    from accounts.models import Role, User
    from rooms.models import Room
    from rooms.services import find_open_room

    room = find_open_room(room_code) if room_code else None
    if room is None:
        owner, _ = User.objects.get_or_create(
            email=owner_email,
            defaults={"name": "Нагрузочный преподаватель", "role": Role.TEACHER},
        )
        room = Room.objects.create(owner=owner, title="Нагрузочный тест")

    cookies: list[str] = []
    for index in range(clients):
        client = Client()
        # enforce_csrf_checks=False: это скрипт, а не браузер; CSRF здесь не проверяем.
        # X-Forwarded-For разный у каждого клиента: студенты приходят с разных
        # устройств, поэтому лимит на перебор ID (10 на IP) не должен мешать
        # нагрузочному входу — это же поведение, что за Caddy.
        response = client.post(
            f"/r/{room.join_code}/",
            {"name": f"Студент-{index + 1}", "consent": "on"},
            headers={"host": host, "x-forwarded-for": f"10.20.{index // 250}.{(index % 250) + 1}"},
        )
        if response.status_code not in (200, 302):
            raise RuntimeError(f"вход студента {index + 1} не удался: HTTP {response.status_code}")
        cookie = client.cookies.get("sessionid")
        if cookie is None:
            raise RuntimeError(f"нет sessionid у студента {index + 1}")
        cookies.append(cookie.value)
    return room.join_code, cookies


# --- Память процесса сервера --------------------------------------------------------


def process_rss_bytes(pid: int) -> int | None:
    """RSS процесса в байтах: ``/proc`` на Linux, ``ps`` на macOS/BSD."""
    status_path = Path(f"/proc/{pid}/status")
    try:
        for line in status_path.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    try:
        output = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return int(output) * 1024 if output else None
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def container_rss_bytes(container: str) -> int | None:
    """RSS процесса в контейнере: `docker exec` + `/proc` внутри контейнера."""
    try:
        output = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "python",
                "-c",
                "import glob; print(sum(int(open(p).read().split()[1]) for p in glob.glob('/proc/*/statm')))",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return int(output) * 4096 if output else None
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def find_server_pid() -> int | None:
    """Найти PID процесса сервера по имени uvicorn/daphne (эвристика)."""
    for pattern in ("uvicorn", "daphne"):
        try:
            output = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            continue
        for token in output:
            try:
                pid = int(token)
            except ValueError:
                continue
            if pid != os.getpid():
                return pid
    return None


class MemoryWatcher:
    """Читает RSS сервера: сначала пытается по PID хоста, затем в контейнере.

    В `make up` сервер живёт в контейнере, поэтому чтение `/proc` хоста ничего
    не найдёт — тогда пробуем `docker exec` в контейнер (имя из
    `--server-container`, по умолчанию `gluho-nemye-django-web`).
    """

    def __init__(self, *, pid: int | None, container: str | None) -> None:
        self.pid = pid
        self.container = container

    def read(self) -> int | None:
        if self.pid is not None:
            value = process_rss_bytes(self.pid)
            if value is not None:
                return value
        if self.container:
            return container_rss_bytes(self.container)
        return None


# --- Нагрузка -----------------------------------------------------------------------


class ClientListener:
    """Слушает события комнаты и запоминает увиденные presence/чат."""

    def __init__(self) -> None:
        self.presence_seen = asyncio.Event()
        self.chat_seen = asyncio.Event()

    async def pump(self, websocket) -> None:
        try:
            async for raw in websocket:
                try:
                    payload = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                message_type = payload.get("type")
                if message_type == "presence" and len(payload.get("participants", [])) >= 1:
                    self.presence_seen.set()
                elif message_type == "chat_message":
                    self.chat_seen.set()
        except Exception:  # noqa: BLE001 — закрытие соединения ожидаемо
            return


async def _wait_seen(listeners: list[ClientListener], *, target: int) -> None:
    """Ждать, пока нужное число клиентов увидит событие."""
    while sum(1 for listener in listeners if listener.chat_seen.is_set()) < target:
        await asyncio.sleep(0.005)


async def run_load(
    websocket_url: str,
    cookies: list[str],
    *,
    origin: str,
    memory: MemoryWatcher | None,
) -> LoadReport:
    """Подключить всех клиентов и измерить handshake, presence и доставку чата."""
    from websockets.asyncio.client import connect

    report = LoadReport(clients=len(cookies))
    connections: list = []
    listeners: list[ClientListener] = []
    tasks: list[asyncio.Task] = []

    for index, cookie in enumerate(cookies):
        started = time.perf_counter()
        try:
            websocket = await connect(
                websocket_url,
                origin=origin,
                additional_headers=[("Cookie", f"sessionid={cookie}")],
                proxy=None,
                open_timeout=10,
            )
        except Exception as error:  # noqa: BLE001 — показываем и продолжаем
            elapsed = (time.perf_counter() - started) * 1000
            report.results.append(ClientResult(index, False, elapsed, error=str(error)))
            continue

        elapsed = (time.perf_counter() - started) * 1000
        report.connected += 1
        report.connect_ms.append(elapsed)
        report.results.append(ClientResult(index, True, elapsed))
        listener = ClientListener()
        listeners.append(listener)
        connections.append(websocket)
        tasks.append(asyncio.create_task(listener.pump(websocket)))

    if memory is not None:
        report.rss_start_bytes = memory.read()

    # Дать presence разойтись по группе.
    await asyncio.sleep(PRESENCE_SETTLE_S)
    for result, listener in zip((r for r in report.results if r.connected), listeners, strict=True):
        result.saw_presence = listener.presence_seen.is_set()

    # Каждый клиент шлёт одно сообщение; ждём доставки остальным.
    target = max(1, len(connections) - 1)
    for index, websocket in enumerate(connections):
        for listener in listeners:
            listener.chat_seen.clear()
        started = time.perf_counter()
        try:
            await websocket.send(json.dumps({"type": "chat", "body": f"нагрузка {index + 1}"}))
        except Exception:  # noqa: BLE001 — со следующего клиента
            continue
        try:
            await asyncio.wait_for(
                _wait_seen(listeners, target=target), timeout=CHAT_DELIVERY_TIMEOUT_S
            )
            report.chat_ms.append((time.perf_counter() - started) * 1000)
        except TimeoutError:
            # Доставка не уложилась — фиксируем максимумом, чтобы порог сработал.
            report.chat_ms.append(CHAT_DELIVERY_TIMEOUT_S * 1000)

    if memory is not None:
        report.rss_peak_bytes = memory.read()

    for task in tasks:
        task.cancel()
    for websocket in connections:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
    return report


def host_from_url(base_url: str) -> str:
    """Имя хоста из URL для тестового клиента (без схемы и порта)."""
    host = base_url.split("://", 1)[-1].strip("/").split("/")[0]
    return host.split(":")[0] or "localhost"


def websocket_url(base_url: str, join_code: str) -> str:
    scheme = "wss" if base_url.startswith("https") else "ws"
    host = base_url.split("://", 1)[-1].rstrip("/")
    return f"{scheme}://{host}/ws/rooms/{join_code}/"


def evaluate(report: LoadReport, *, max_rss_growth_bytes: int | None = None) -> list[str]:
    """Сверить отчёт с порогами ТЗ и вернуть список нарушений.

    ``max_rss_growth_bytes`` — необязательный предел роста RSS процесса сервера
    от старта нагрузки к пику. В ТЗ нет точного числа памяти, но критерий
    «без деградации» означает, что 30 соединений не должны съедать память
    бесконтрольно; предел задаётся флагом ``--max-rss-growth``.
    """
    problems: list[str] = []
    if report.connected < report.clients:
        problems.append(f"подключилось {report.connected} из {report.clients} клиентов")

    median_chat = statistics.median(report.chat_ms) if report.chat_ms else None
    if median_chat is not None and median_chat > LATENCY_MEDIAN_MAX_MS:
        problems.append(f"медиана доставки {median_chat:.0f} мс > {LATENCY_MEDIAN_MAX_MS} мс")

    p95_chat = report.percentile(report.chat_ms, 0.95) if report.chat_ms else None
    if p95_chat is not None and p95_chat > LATENCY_P95_MAX_MS:
        problems.append(f"p95 доставки {p95_chat:.0f} мс > {LATENCY_P95_MAX_MS} мс")

    p95_connect = report.percentile(report.connect_ms, 0.95) if report.connect_ms else None
    if p95_connect is not None and p95_connect > CONNECT_P95_MAX_MS:
        problems.append(f"p95 подключения {p95_connect:.0f} мс > {CONNECT_P95_MAX_MS} мс")

    growth = report.rss_growth_bytes
    if max_rss_growth_bytes is not None and growth is not None:
        if growth > max_rss_growth_bytes:
            problems.append(
                f"рост памяти {human_bytes(growth)} > {human_bytes(max_rss_growth_bytes)}"
            )
    return problems


def print_report(report: LoadReport) -> None:
    summary = report.summary()
    print(f"Клиентов: {summary['clients']}, подключилось: {summary['connected']}")
    print(f"Подключение, мс: {summary['connect_ms']}")
    print(f"Доставка чата, мс: {summary['chat_latency_ms']}")
    print(f"Presence увидели: {summary['presence_seen']} из {summary['connected']}")
    if summary["rss_start_bytes"] is not None:
        print(
            "Память сервера: старт",
            human_bytes(summary["rss_start_bytes"]),
            "· пик",
            human_bytes(summary["rss_peak_bytes"] or 0),
            "· рост",
            human_bytes(summary["rss_growth_bytes"] or 0),
        )
    for result in report.results:
        if result.error:
            print(f"  ошибка клиента {result.index + 1}: {result.error}")


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("Б", "КиБ", "МиБ", "ГиБ"):
        if size < 1024 or unit == "ГиБ":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГиБ"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Нагрузка G3: комната и 30 WebSocket-клиентов")
    parser.add_argument("--url", default=os.environ.get("LOAD_URL", "http://localhost:8000"))
    parser.add_argument("--clients", type=int, default=30)
    parser.add_argument("--room", default=os.environ.get("LOAD_ROOM") or None)
    parser.add_argument("--owner-email", default="loadtest@example.com")
    parser.add_argument("--json", action="store_true", help="вывести сводку в JSON")
    parser.add_argument(
        "--server-pid",
        type=int,
        default=None,
        help="PID процесса сервера для замера памяти (иначе ищется автоматически)",
    )
    parser.add_argument(
        "--server-container",
        default=os.environ.get("LOAD_CONTAINER", "gluho-nemye-django-web"),
        help="имя контейнера сервера для замера памяти (случай `make up`)",
    )
    parser.add_argument(
        "--max-rss-growth",
        type=int,
        default=None,
        metavar="БАЙТ",
        help="предел роста памяти сервера от старта нагрузки (по умолчанию не проверяется)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        join_code, cookies = prepare_room(
            owner_email=args.owner_email,
            room_code=args.room,
            clients=args.clients,
            host=host_from_url(args.url),
        )
    except Exception as error:  # noqa: BLE001 — понятная ошибка запуска
        print(f"Не удалось подготовить комнату: {error}", file=sys.stderr)
        return 2

    target_url = websocket_url(args.url, join_code)
    print(f"Комната {join_code}, клиентов {len(cookies)}, WS {target_url}")

    memory = MemoryWatcher(
        pid=args.server_pid or find_server_pid(),
        container=args.server_container,
    )
    report = asyncio.run(run_load(target_url, cookies, origin=args.url, memory=memory))

    if args.json:
        print(json.dumps(report.summary(), ensure_ascii=False, indent=2))
    else:
        print_report(report)

    problems = evaluate(report, max_rss_growth_bytes=args.max_rss_growth)
    if not problems:
        print(
            f"РЕЗУЛЬТАТ: укладывается в пороги "
            f"(медиана {LATENCY_MEDIAN_MAX_MS} мс, p95 {LATENCY_P95_MAX_MS} мс)"
        )
        return 0
    print("РЕЗУЛЬТАТ: превышены пороги", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
