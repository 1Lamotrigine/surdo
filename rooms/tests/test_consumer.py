"""RoomConsumer: изоляция комнат, presence и проверка доступа.

Тесты синхронные: сценарий целиком выполняется в `asyncio.run`, чтобы обе
стороны WebSocket жили в одном event loop и in-memory channel layer работал
предсказуемо.
"""

import asyncio

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.db import connections

from config.asgi import application
from rooms import presence
from rooms.models import Participant, Room
from rooms.services import GUEST_ROOMS_SESSION_KEY, GUEST_SESSION_KEY_SESSION_KEY

pytestmark = pytest.mark.django_db(transaction=True)

ORIGIN = [(b"origin", b"http://localhost")]
IN_MEMORY_CHANNEL_LAYER = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}


@pytest.fixture(autouse=True)
def clean_state():
    cache.clear()
    yield
    cache.clear()
    # consumer открывает соединения в потоках пула; закрываем их, иначе
    # тестовая БД не удаляется после прогона.
    connections.close_all()


async def run_scenario(coro_func) -> None:
    """Выполнить сценарий и закрыть соединения пула потоков внутри loop."""
    try:
        await coro_func()
    finally:
        await database_sync_to_async(connections.close_all)()


@pytest.fixture
def websocket_settings(settings):
    settings.CHANNEL_LAYERS = IN_MEMORY_CHANNEL_LAYER


def make_guest_session_cookie(room: Room, name: str = "Айгуль") -> bytes:
    session = SessionStore()
    session[GUEST_SESSION_KEY_SESSION_KEY] = session.session_key
    session[GUEST_ROOMS_SESSION_KEY] = {
        room.join_code: {"name": name, "participant_id": None, "room_id": room.pk}
    }
    session.create()
    Participant.objects.create(room=room, guest_name=name, session_key=session.session_key)
    return f"sessionid={session.session_key}".encode()


def make_staff_session_cookie(user) -> bytes:
    session = SessionStore()
    session["_auth_user_id"] = str(user.pk)
    session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    session["_auth_user_hash"] = user.get_session_auth_hash()
    session.create()
    return f"sessionid={session.session_key}".encode()


def make_communicator(join_code: str, cookie: bytes | None = None) -> WebsocketCommunicator:
    headers = list(ORIGIN)
    if cookie:
        headers.append((b"cookie", cookie))
    return WebsocketCommunicator(application, f"/ws/rooms/{join_code}/", headers=headers)


async def receive_type(
    client: WebsocketCommunicator,
    expected: str,
    *,
    timeout: float = 1.0,
    attempts: int = 5,
) -> dict:
    """Читать события, пока не придёт ожидаемого типа (пропуская presence и др.)."""
    for _ in range(attempts):
        event = await client.receive_json_from(timeout=timeout)
        if event["type"] == expected:
            return event
    raise AssertionError(f"не дождались события {expected!r}")


async def connect_guest(client: WebsocketCommunicator, *, timeout: float = 1.0) -> dict:
    """Подключиться и вернуть первое событие presence.

    При подключении consumer сначала присылает `chat_history`, затем `presence`.
    """
    connected, _ = await client.connect()
    assert connected is True, "соединение должно установиться"
    first = await client.receive_json_from(timeout=timeout)
    if first["type"] == "presence":
        return first
    assert first["type"] == "chat_history"
    return await client.receive_json_from(timeout=timeout)


@pytest.fixture
def open_room(owner):
    return Room.objects.create(owner=owner, title="Алгебра", join_code="ABC234")


def test_guest_with_session_connects_and_gets_presence(websocket_settings, open_room):
    cookie = make_guest_session_cookie(open_room)

    async def scenario() -> None:
        client = make_communicator(open_room.join_code, cookie)
        event = await connect_guest(client)
        assert event["type"] == "presence"
        names = [p["name"] for p in event["participants"]]
        assert "Айгуль" in names

        await client.disconnect()

    asyncio.run(run_scenario(scenario))


def test_guest_without_session_is_rejected(websocket_settings, open_room):
    async def scenario() -> None:
        client = make_communicator(open_room.join_code)
        connected, code = await client.connect()
        assert (connected, code) == (False, 4401)

    asyncio.run(run_scenario(scenario))


def test_unknown_room_is_rejected(websocket_settings, owner):
    cookie = make_guest_session_cookie(Room.objects.create(owner=owner, join_code="OTHER1"))

    async def scenario() -> None:
        client = make_communicator("ZZZZZZ", cookie)
        connected, code = await client.connect()
        assert (connected, code) == (False, 4403)

    asyncio.run(run_scenario(scenario))


def test_closed_room_is_rejected(websocket_settings, owner):
    room = Room.objects.create(owner=owner, join_code="CLOSED")
    cookie = make_guest_session_cookie(room)
    room.close()

    async def scenario() -> None:
        client = make_communicator(room.join_code, cookie)
        connected, code = await client.connect()
        assert (connected, code) == (False, 4403)

    asyncio.run(run_scenario(scenario))


def test_two_guests_see_each_other(websocket_settings, open_room):
    first_cookie = make_guest_session_cookie(open_room, "Первый")
    second_cookie = make_guest_session_cookie(open_room, "Второй")

    async def scenario() -> None:
        first = make_communicator(open_room.join_code, first_cookie)
        await connect_guest(first)

        second = make_communicator(open_room.join_code, second_cookie)
        event = await connect_guest(second)
        names = {p["name"] for p in event["participants"]}
        assert {"Первый", "Второй"} <= names

        # первый тоже узнал о подключении второго
        update = await first.receive_json_from()
        names = {p["name"] for p in update["participants"]}
        assert {"Первый", "Второй"} <= names

        await first.disconnect()
        await second.disconnect()

    asyncio.run(run_scenario(scenario))


def test_owner_connects_as_non_guest(websocket_settings, open_room, owner):
    cookie = make_staff_session_cookie(owner)

    async def scenario() -> None:
        client = make_communicator(open_room.join_code, cookie)
        event = await connect_guest(client)
        assert event["type"] == "presence"
        entry = event["participants"][0]
        assert entry["guest"] is False
        assert entry["name"] == owner.name
        await client.disconnect()

    asyncio.run(run_scenario(scenario))


def test_presence_removed_after_disconnect(websocket_settings, open_room):
    cookie = make_guest_session_cookie(open_room)

    async def scenario() -> None:
        first = make_communicator(open_room.join_code, cookie)
        await connect_guest(first)

        second = make_communicator(open_room.join_code, cookie)
        await connect_guest(second)

        await second.disconnect()
        await first.disconnect()

    asyncio.run(run_scenario(scenario))

    # после закрытия всех соединений presence пуст (одна вкладка count=1)
    assert presence.list_participants(open_room.pk) == []


def test_ping_gets_pong(websocket_settings, open_room):
    cookie = make_guest_session_cookie(open_room)

    async def scenario() -> None:
        client = make_communicator(open_room.join_code, cookie)
        await connect_guest(client)

        await client.send_json_to({"type": "ping"})
        assert await client.receive_json_from() == {"type": "pong"}

        await client.disconnect()

    asyncio.run(run_scenario(scenario))


def test_foreign_room_is_not_reachable(websocket_settings, owner):
    """Гость одной комнаты не проходит в другую."""
    room_a = Room.objects.create(owner=owner, join_code="ROOMAA")
    room_b = Room.objects.create(owner=owner, join_code="ROOMBB")
    cookie = make_guest_session_cookie(room_a)

    async def scenario() -> None:
        client = make_communicator(room_b.join_code, cookie)
        connected, code = await client.connect()
        assert (connected, code) == (False, 4401)

    asyncio.run(run_scenario(scenario))


def test_chat_history_sent_on_connect(websocket_settings, open_room):
    from rooms.models import Message

    Message.objects.create(room=open_room, author_name="Гость", body="старое")
    cookie = make_guest_session_cookie(open_room)

    async def scenario() -> None:
        client = make_communicator(open_room.join_code, cookie)
        connected, _ = await client.connect()
        assert connected is True

        history = await client.receive_json_from()
        assert history["type"] == "chat_history"
        assert [m["body"] for m in history["messages"]] == ["старое"]

        await client.disconnect()

    asyncio.run(run_scenario(scenario))


def test_guest_message_is_broadcast_to_all(websocket_settings, open_room):
    first_cookie = make_guest_session_cookie(open_room, "Первый")
    second_cookie = make_guest_session_cookie(open_room, "Второй")

    async def scenario() -> None:
        first = make_communicator(open_room.join_code, first_cookie)
        await connect_guest(first)
        second = make_communicator(open_room.join_code, second_cookie)
        await connect_guest(second)

        await first.send_json_to({"type": "chat", "body": "  Привет   всем "})

        event = await receive_type(first, "chat_message")
        assert event["message"]["body"] == "Привет всем"
        assert event["message"]["user"] == "Первый"
        assert event["message"]["is_teacher"] is False

        echo = await receive_type(second, "chat_message")
        assert echo == event

        await first.disconnect()
        await second.disconnect()

    asyncio.run(run_scenario(scenario))


def test_teacher_message_is_marked(websocket_settings, open_room, owner):
    cookie = make_staff_session_cookie(owner)
    guest_cookie = make_guest_session_cookie(open_room)

    async def scenario() -> None:
        teacher = make_communicator(open_room.join_code, cookie)
        await connect_guest(teacher)
        guest = make_communicator(open_room.join_code, guest_cookie)
        await connect_guest(guest)

        await teacher.send_json_to({"type": "chat", "body": "Ответ преподавателя"})
        event = await receive_type(guest, "chat_message")

        assert event["message"]["is_teacher"] is True
        assert event["message"]["user"] == owner.name

        await teacher.disconnect()
        await guest.disconnect()

    asyncio.run(run_scenario(scenario))


def test_empty_message_returns_chat_error(websocket_settings, open_room):
    cookie = make_guest_session_cookie(open_room)

    async def scenario() -> None:
        client = make_communicator(open_room.join_code, cookie)
        await connect_guest(client)

        await client.send_json_to({"type": "chat", "body": "   "})
        await receive_type(client, "chat_error")

        await client.disconnect()

    asyncio.run(run_scenario(scenario))


def test_room_closed_event_closes_connection(websocket_settings, open_room):
    cookie = make_guest_session_cookie(open_room)

    async def scenario() -> None:
        client = make_communicator(open_room.join_code, cookie)
        await connect_guest(client)

        # HTTP-действие закрытия рассылает событие в группу (здесь — напрямую).
        from channels.layers import get_channel_layer

        await get_channel_layer().group_send(
            f"room_{open_room.pk}", {"type": "room.closed", "room_id": open_room.pk}
        )

        event = await receive_type(client, "room_closed")
        assert event["type"] == "room_closed"

        # Сервер закрывает соединение кодом 4403 — клиент не переподключается.
        close_event = await client.receive_output(timeout=1.0)
        assert close_event["type"] == "websocket.close"
        assert close_event["code"] == 4403

    asyncio.run(run_scenario(scenario))


def test_removed_participant_is_disconnected(websocket_settings, open_room):
    cookie = make_guest_session_cookie(open_room, "Удаляемый")

    async def scenario() -> None:
        client = make_communicator(open_room.join_code, cookie)
        await connect_guest(client)

        participant = await database_sync_to_async(
            lambda: Participant.objects.get(room=open_room, guest_name="Удаляемый")
        )()
        from rooms.management import remove_participant

        await database_sync_to_async(remove_participant)(participant)

        event = await receive_type(client, "participant_removed")
        assert event["type"] == "participant_removed"

        close_event = await client.receive_output(timeout=1.0)
        assert close_event["type"] == "websocket.close"
        assert close_event["code"] == 4403

    asyncio.run(run_scenario(scenario))


def test_removed_participant_cannot_reconnect(websocket_settings, open_room):
    cookie = make_guest_session_cookie(open_room, "Удаляемый")

    async def scenario() -> None:
        participant = await database_sync_to_async(
            lambda: Participant.objects.get(room=open_room, guest_name="Удаляемый")
        )()
        from rooms.management import remove_participant

        await database_sync_to_async(remove_participant)(participant)

        client = make_communicator(open_room.join_code, cookie)
        connected, code = await client.connect()
        assert (connected, code) == (False, 4401)

    asyncio.run(run_scenario(scenario))


def test_other_guest_gets_presence_when_one_removed(websocket_settings, open_room):
    keeper_cookie = make_guest_session_cookie(open_room, "Остаётся")
    removed_cookie = make_guest_session_cookie(open_room, "Удаляемый")

    async def scenario() -> None:
        keeper = make_communicator(open_room.join_code, keeper_cookie)
        await connect_guest(keeper)
        removed = make_communicator(open_room.join_code, removed_cookie)
        await connect_guest(removed)

        participant = await database_sync_to_async(
            lambda: Participant.objects.get(room=open_room, guest_name="Удаляемый")
        )()
        from rooms.management import remove_participant

        await database_sync_to_async(remove_participant)(participant)

        # Читаем presence, пока не придёт обновление без удалённого участника.
        names = {"Остаётся", "Удаляемый"}
        for _ in range(5):
            event = await receive_type(keeper, "presence")
            names = {p["name"] for p in event["participants"]}
            if "Удаляемый" not in names:
                break
        assert "Удаляемый" not in names

        await keeper.disconnect()

    asyncio.run(run_scenario(scenario))


def test_chat_rate_limit(websocket_settings, open_room, settings):
    settings.CHAT_RATE_LIMIT_MESSAGES = 2
    settings.CHAT_RATE_LIMIT_WINDOW = 5
    cookie = make_guest_session_cookie(open_room)

    async def scenario() -> None:
        client = make_communicator(open_room.join_code, cookie)
        await connect_guest(client)

        await client.send_json_to({"type": "chat", "body": "раз"})
        await receive_type(client, "chat_message")
        await client.send_json_to({"type": "chat", "body": "два"})
        await receive_type(client, "chat_message")
        await client.send_json_to({"type": "chat", "body": "три"})
        blocked = await receive_type(client, "chat_error")
        assert blocked == {"type": "chat_error", "error": "rate_limited", "retry_after": 5}

        await client.disconnect()

    asyncio.run(run_scenario(scenario))
