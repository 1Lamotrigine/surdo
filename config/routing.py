"""WebSocket-маршруты проекта."""

from django.urls import path

from config.consumers import EchoConsumer

websocket_urlpatterns = [
    path("ws/echo/<slug:group>/", EchoConsumer.as_asgi()),
]
