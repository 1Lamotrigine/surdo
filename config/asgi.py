"""
ASGI-точка входа проекта.

HTTP обрабатывает Django, WebSocket — Channels. Проверка Origin выполняется до
маршрутизации, чтобы соединения с чужих доменов не доходили до consumer.
"""

import asyncio
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Приложение Django должно загрузиться до импорта routing/consumers:
# consumer'ы могут обращаться к моделям и app registry.
django_asgi_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from config.routing import websocket_urlpatterns  # noqa: E402
from pipeline.events import bind_event_loop  # noqa: E402

# AuthMiddlewareStack кладёт в scope сессию Django и пользователя: consumer
# проверяет гостевую сессию студента и роль преподавателя в connect().
router = ProtocolTypeRouter(
    {
        "http": django_asgi_application,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)


async def application(scope, receive, send):
    """Запоминаем цикл ASGI, чтобы фоновые очереди E3 могли слать события.

    Очередь фраз живёт в отдельном потоке. Перед маршрутизацией каждого
    HTTP/WebSocket-запроса обновляем ссылку на активный цикл; рассылка из
    ``pipeline.events`` ставит ``group_send`` в этот цикл потокобезопасно.
    """
    bind_event_loop(asyncio.get_running_loop())
    await router(scope, receive, send)
