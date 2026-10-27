"""Временный consumer этапа A2: проверка channel layer и групп Channels.

Это не комната и не чат: endpoint доступен только при DEBUG=True и будет
заменён `RoomConsumer` на этапе A8.
"""

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

GROUP_PREFIX = "echo_"
MAX_GROUP_SLUG_LENGTH = 40


class EchoConsumer(AsyncJsonWebsocketConsumer):
    """Отправляет каждое полученное сообщение всем клиентам своей группы."""

    group_name: str

    async def connect(self) -> None:
        if not settings.DEBUG:
            await self.close(code=4404)
            return

        group = self.scope["url_route"]["kwargs"].get("group", "default")
        if len(group) > MAX_GROUP_SLUG_LENGTH:
            await self.close(code=4400)
            return

        self.group_name = f"{GROUP_PREFIX}{group}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code: int) -> None:
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs) -> None:
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "echo.message", "body": content},
        )

    async def echo_message(self, event: dict) -> None:
        await self.send_json({"type": "echo.message", "body": event["body"]})
