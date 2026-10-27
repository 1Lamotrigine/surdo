"""
ASGI-точка входа проекта.

HTTP обрабатывает Django, WebSocket — Channels. Проверка Origin выполняется до
маршрутизации, чтобы соединения с чужих доменов не доходили до consumer.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Приложение Django должно загрузиться до импорта routing/consumers:
# consumer'ы могут обращаться к моделям и app registry.
django_asgi_application = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from config.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_application,
        "websocket": AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns)),
    }
)
