"""WebSocket-consumer комнаты: изоляция, presence, чат и heartbeat.

A8: проверка кода и сессии в `connect()`, группа `room_<id>`, presence.
A9: чат — приём `{type: chat, body}`, рассылка `chat_message`, догрузка истории
при подключении.
A10: `room_closed` закрывает соединения, `participant_removed` закрывает
соединения удалённого участника.
A11: heartbeat — клиент шлёт `ping`, сервер закрывает соединение без пинга за
`ROOM_PING_TIMEOUT` секунд.
"""

import asyncio
import logging
from time import monotonic

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from pipeline.lag_policy import lag_playback_policy
from pipeline.services import record_display_started
from rooms import presence
from rooms.consumers_support import resolve_connection
from rooms.ratelimit import check_chat_rate_limit
from rooms.services import ChatValidationError, find_open_room, post_message, recent_messages

logger = logging.getLogger(__name__)

# Коды закрытия из ТЗ (7.6).
CLOSE_NO_SESSION = 4401
CLOSE_NO_ACCESS = 4403
CLOSE_RATE_LIMITED = 4429
CLOSE_HEARTBEAT_TIMEOUT = 4408


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
    last_seen: float
    heartbeat_task: asyncio.Task | None

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
        self.last_seen = monotonic()
        self.heartbeat_task = None

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

        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self, code: int) -> None:
        if not hasattr(self, "group_name"):
            return
        if self.heartbeat_task is not None:
            self.heartbeat_task.cancel()
            self.heartbeat_task = None
        participants = await database_sync_to_async(presence.remove_connection)(
            self.room_id, self.connection_key
        )
        await self._broadcast_presence(participants)
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def _heartbeat_loop(self) -> None:
        """Закрыть соединение, если клиент молчит дольше `ROOM_PING_TIMEOUT`."""
        timeout = settings.ROOM_PING_TIMEOUT
        interval = max(settings.ROOM_PING_INTERVAL, 1)
        while True:
            await asyncio.sleep(interval)
            if monotonic() - self.last_seen > timeout:
                logger.info(
                    "heartbeat timeout: room=%s key=%s",
                    self.room_id,
                    self.connection_key,
                )
                # Задачу закрываем сами, чтобы disconnect не отменял её повторно.
                self.heartbeat_task = None
                await self.close(code=CLOSE_HEARTBEAT_TIMEOUT)
                return

    async def receive_json(self, content, **kwargs) -> None:
        if not isinstance(content, dict):
            return

        # Любое сообщение клиента продлевает heartbeat-окно.
        self.last_seen = monotonic()

        message_type = content.get("type")
        if message_type == "ping":
            await database_sync_to_async(presence.touch)(self.room_id, self.connection_key)
            await self.send_json({"type": "pong"})
        elif message_type == "chat":
            await self._handle_chat(content.get("body", ""))
        elif message_type == "display_started":
            await self._handle_display_started(content)

    async def _handle_display_started(self, content: dict) -> None:
        """E4/F8: студент сообщил фактическое начало показа фразы.

        Метрика сохраняется у ``Utterance``, уровень отставания уходит
        преподавателю, а политика догона — студентам. Студент может ускорить
        текущую фразу и убрать паузы на ходу; сжатие следующей фразы сервер
        применит при её обработке.
        """
        utterance_id = content.get("utterance_id")
        if (
            not isinstance(utterance_id, int)
            or isinstance(utterance_id, bool)
            or utterance_id <= 0
        ):
            return

        lag = await database_sync_to_async(record_display_started)(
            self.room_id,
            utterance_id,
            ts=content.get("ts"),
        )
        if lag is None:
            return
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "lag.status", **lag.as_event()},
        )
        policy = lag_playback_policy(lag.lag_ms)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "playback",
                "utterance_id": utterance_id,
                **policy.as_event(),
            },
        )

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

    async def asr_text(self, event: dict) -> None:
        """E3: распознанный текст показывается сразу, до глосс и клипов."""
        await self.send_json({"type": "asr_text", "text": event.get("text", "")})

    async def utterance(self, event: dict) -> None:
        """E3: глоссы фразы и ссылки на клипы для очереди студента."""
        await self.send_json(
            {"type": "utterance", "utterance": event.get("utterance", {})}
        )

    async def lag_status(self, event: dict) -> None:
        """E4: индикатор отставания видит только преподаватель."""
        if not getattr(self, "is_teacher", False):
            return
        await self.send_json(
            {
                "type": "lag_status",
                "lag_ms": event.get("lag_ms", 0),
                "level": event.get("level", "green"),
            }
        )

    async def playback(self, event: dict) -> None:
        """F8: параметры догона получает только студент.

        Преподавателю они не нужны: его индикатор — ``lag_status``. Студент по
        этому событию меняет скорость и паузы уже играющей фразы.
        """
        if getattr(self, "is_teacher", False):
            return
        await self.send_json(
            {
                "type": "playback",
                "utterance_id": event.get("utterance_id"),
                "level": event.get("level", "green"),
                "lag_ms": event.get("lag_ms", 0),
                "speed": event.get("speed"),
                "gap_ms": event.get("gap_ms", 0),
            }
        )

    async def unknown_words(self, event: dict) -> None:
        """E4: слова без жеста из последней фразы — только преподавателю."""
        if not getattr(self, "is_teacher", False):
            return
        await self.send_json(
            {"type": "unknown_words", "words": event.get("words", [])}
        )

    async def room_closed(self, event: dict) -> None:
        """Событие A10: комната закрыта преподавателем."""
        await self.send_json({"type": "room_closed"})
        await self.close(code=CLOSE_NO_ACCESS)

    async def participant_removed(self, event: dict) -> None:
        """Событие A10: участник удалён преподавателем.

        Удалённый получает `participant_removed` и отключение (переподключение
        бессмысленно — 4403), остальные — обновлённый presence.
        """
        if event.get("connection_key") == self.connection_key:
            await self.send_json({"type": "participant_removed"})
            await self.close(code=CLOSE_NO_ACCESS)
            return
        await self.send_json(
            {
                "type": "presence",
                "participants": event.get("participants", []),
            }
        )
