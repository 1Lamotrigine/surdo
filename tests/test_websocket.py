"""Тесты Channels: подключение, группы и проверка Origin.

Тесты синхронные, сценарии выполняются в одном `asyncio.run`: так обе стороны
WebSocket живут в одном event loop и in-memory channel layer работает предсказуемо.
"""

import asyncio

import pytest
from channels.testing import WebsocketCommunicator

from config.asgi import application

ORIGIN_HEADERS = [(b"origin", b"http://localhost")]
IN_MEMORY_CHANNEL_LAYER = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}


@pytest.fixture
def websocket_settings(settings):
    # pytest-django принудительно выключает DEBUG; для echo-endpoint он нужен.
    settings.DEBUG = True
    settings.CHANNEL_LAYERS = IN_MEMORY_CHANNEL_LAYER


def make_communicator(group: str, *, with_origin: bool = True) -> WebsocketCommunicator:
    return WebsocketCommunicator(
        application,
        f"/ws/echo/{group}/",
        headers=ORIGIN_HEADERS if with_origin else [],
    )


async def two_clients_receive_group_message() -> None:
    first = make_communicator("a2-shared")
    second = make_communicator("a2-shared")

    assert await first.connect() == (True, None)
    assert await second.connect() == (True, None)

    payload = {"type": "hello", "text": "привет"}
    await first.send_json_to(payload)

    expected = {"type": "echo.message", "body": payload}
    assert await first.receive_json_from() == expected
    assert await second.receive_json_from() == expected

    await first.disconnect()
    await second.disconnect()


async def groups_are_isolated() -> None:
    first = make_communicator("a2-alpha")
    second = make_communicator("a2-beta")

    assert await first.connect() == (True, None)
    assert await second.connect() == (True, None)

    await first.send_json_to({"type": "hello"})
    assert await first.receive_json_from() == {
        "type": "echo.message",
        "body": {"type": "hello"},
    }
    assert await second.receive_nothing(timeout=0.2) is True

    await first.disconnect()
    await second.disconnect()


def test_two_clients_receive_group_message(websocket_settings):
    asyncio.run(two_clients_receive_group_message())


def test_groups_are_isolated(websocket_settings):
    asyncio.run(groups_are_isolated())


def test_connection_without_allowed_origin_is_rejected(websocket_settings):
    async def scenario() -> None:
        client = make_communicator("a2-origin", with_origin=False)
        connected, _code = await client.connect()
        assert connected is False

    asyncio.run(scenario())


def test_echo_is_disabled_outside_debug(websocket_settings, settings):
    settings.DEBUG = False

    async def scenario() -> None:
        client = make_communicator("a2-production")
        connected, code = await client.connect()
        assert (connected, code) == (False, 4404)

    asyncio.run(scenario())
