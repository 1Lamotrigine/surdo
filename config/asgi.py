"""
ASGI-точка входа проекта.

HTTP обрабатывает Django, WebSocket — Channels. Проверка Origin выполняется до
маршрутизации, чтобы соединения с чужих доменов не доходили до consumer.
"""

import asyncio
import logging
import os
import threading

from django.conf import settings
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Приложение Django должно загрузиться до импорта routing/consumers:
# consumer'ы могут обращаться к моделям и app registry.
django_asgi_application = get_asgi_application()

logger = logging.getLogger(__name__)


def _warm_up_asr() -> None:
    """Загрузить модель Whisper в фоне, чтобы первая фраза не ждала диск.

    При пустом кэше веса ещё и скачиваются; это не должно задерживать старт
    сайта, поэтому прогрев идёт в daemon-потоке и не влияет на healthcheck.
    """
    try:
        from services.asr import warm_up

        warm_up(timeout=180.0)
        logger.info("ASR model is ready")
    except Exception:  # noqa: BLE001 — прогрев не должен ронять сервер
        logger.warning(
            "ASR warm-up failed; the first phrase will load the model",
            exc_info=True,
        )


if settings.ASR_WARMUP:
    threading.Thread(target=_warm_up_asr, name="asr-warmup", daemon=True).start()

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
