"""WebSocket-маршруты проекта."""

from django.urls import path

from config.consumers import EchoConsumer
from rooms.consumers import RoomConsumer

websocket_urlpatterns = [
    path("ws/rooms/<str:join_code>/", RoomConsumer.as_asgi()),
    # Тестовый эхо-endpoint остаётся для проверки channel layer (A2).
    path("ws/echo/<slug:group>/", EchoConsumer.as_asgi()),
]
