"""WebSocket-consumer комнаты: изоляция, presence и чат.

A8: проверка кода и сессии в `connect()`, группа `room_<id>`, presence.
A9: чат — приём `{type: chat, body}`, рассылка `chat_message`, догрузка истории
при подключении. Heartbeat (A11) и `room_closed` (A10) появятся позже.
"""

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from rooms import presence
from rooms.consumers_support import resolve_connection
from rooms.ratelimit import check_chat_rate_limit
from rooms.services import ChatValidationError, find_open_room, post_message, recent_messages

logger = logging.getLogger(__name__)

# Коды закрытия из ТЗ (7.6).
CLOSE_NO_SESSION = 4401
CLOSE_NO_ACCESS = 4403
CLOSE_RATE_LIMITED = 4429


def group_name_for(room_id: int) -> str:
    return f"room_{room_id}"


class RoomConsumer(AsyncJsonWebsocketConsumer):
    """Комната как группа Channels `room_<id>`."""

    group_name: str
    room_id: int
    participant_id: int | None
    connection_key: str
    display_name: str
    is_guest: bool
    is_teacher: bool

    async def connect(self) -> None:
        join_code = self.scope["url_route"]["kwargs"].get("join_code", "")
        room = await database_sync_to_async(find_open_room)(join_code)
        if room is None:
            # Комнаты нет или она закрыта: переподключение бессмысленно.
            await self.close(code=CLOSE_NO_ACCESS)
            return

        identity = await database_sync_to_async(resolve_connection)(
            self.scope, room, self.channel_name
        )
        if identity is None:
            await self.close(code=CLOSE_NO_SESSION)
            return

        self.room_id = room.pk
        self.group_name = group_name_for(room.pk)
        self.participant_id = identity.participant_id
        self.connection_key = identity.key
        self.display_name = identity.name
        self.is_guest = identity.guest
        self.is_teacher = identity.is_teacher

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Догрузка истории: клиент получает последние сообщения при подключении.
        history = await database_sync_to_async(recent_messages)(room)
        await self.send_json(
            {
                "type": "chat_history",
                "messages": [message.as_event() for message in history],
            }
        )

        participants = await database_sync_to_async(presence.add_connection)(
            self.room_id,
            key=self.connection_key,
            name=self.display_name,
            participant_id=self.participant_id,
            guest=self.is_guest,
        )
        await self._broadcast_presence(participants)

    async def disconnect(self, code: int) -> None:
        if not hasattr(self, "group_name"):
            return
        participants = await database_sync_to_async(presence.remove_connection)(
            self.room_id, self.connection_key
        )
        await self._broadcast_presence(participants)
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs) -> None:
        if not isinstance(content, dict):
            return

        message_type = content.get("type")
        if message_type == "ping":
            await database_sync_to_async(presence.touch)(self.room_id, self.connection_key)
            await self.send_json({"type": "pong"})
        elif message_type == "chat":
            await self._handle_chat(content.get("body", ""))

    async def _handle_chat(self, body: str) -> None:
        rate = await database_sync_to_async(check_chat_rate_limit)(
            self.room_id, self.connection_key
        )
        if not rate.allowed:
            await self.send_json(
                {
                    "type": "chat_error",
                    "error": "rate_limited",
                    "retry_after": rate.retry_after,
                }
            )
            return

        try:
            message = await database_sync_to_async(post_message)(
                room_id=self.room_id,
                participant_id=self.participant_id,
                author_name=self.display_name,
                body=body,
                is_teacher=self.is_teacher,
            )
        except ChatValidationError as error:
            await self.send_json({"type": "chat_error", "error": str(error)})
            return

        await self.channel_layer.group_send(
            self.group_name,
            {"type": "chat.message", "message": message.as_event()},
        )

    async def _broadcast_presence(self, participants) -> None:
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "presence.update",
                "participants": [entry.to_dict() for entry in participants],
            },
        )

    async def presence_update(self, event: dict) -> None:
        await self.send_json(
            {
                "type": "presence",
                "participants": event["participants"],
            }
        )

    async def chat_message(self, event: dict) -> None:
        await self.send_json({"type": "chat_message", "message": event["message"]})

    async def room_closed(self, event: dict) -> None:
        """Событие A10: комната закрыта преподавателем."""
        await self.send_json({"type": "room_closed"})
        await self.close(code=CLOSE_NO_ACCESS)
