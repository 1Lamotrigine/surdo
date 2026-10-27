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


@pytest.fixture
def open_room(owner):
    return Room.objects.create(owner=owner, title="Алгебра", join_code="ABC234")


def test_guest_with_session_connects_and_gets_presence(websocket_settings, open_room):
    cookie = make_guest_session_cookie(open_room)

    async def scenario() -> None:
        client = make_communicator(open_room.join_code, cookie)
        connected, _ = await client.connect()
        assert connected is True

        event = await client.receive_json_from()
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
        assert await first.connect() == (True, None)
        await first.receive_json_from()  # первый получил наличие себя

        second = make_communicator(open_room.join_code, second_cookie)
        assert await second.connect() == (True, None)
        event = await second.receive_json_from()
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
        assert await client.connect() == (True, None)
        event = await client.receive_json_from()
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
        assert await first.connect() == (True, None)
        await first.receive_json_from()

        second = make_communicator(open_room.join_code, cookie)
        assert await second.connect() == (True, None)
        await second.receive_json_from()

        await second.disconnect()
        await first.disconnect()

    asyncio.run(run_scenario(scenario))

    # после закрытия всех соединений presence пуст (одна вкладка count=1)
    assert presence.list_participants(open_room.pk) == []


def test_ping_gets_pong(websocket_settings, open_room):
    cookie = make_guest_session_cookie(open_room)

    async def scenario() -> None:
        client = make_communicator(open_room.join_code, cookie)
        assert await client.connect() == (True, None)
        await client.receive_json_from()  # presence

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
