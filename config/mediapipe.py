"""Путь к клиентским ресурсам MediaPipe."""

from django.conf import settings


def mediapipe_wasm_path() -> str:
    """Каталог WASM MediaPipe: Vite dev-сервер или собранная статика.

    В dev-режиме модули и WASM отдаёт Vite (`npm run dev`), в остальных случаях —
    `static/dist/mediapipe`, куда плагин Vite копирует файлы при сборке.
    """
    config = settings.DJANGO_VITE["default"]
    prefix = config.get("static_url_prefix", "dist")
    if config.get("dev_mode"):
        host = config.get("dev_server_host", "localhost")
        port = config.get("dev_server_port", 5173)
        return f"http://{host}:{port}/{settings.STATIC_URL.strip('/')}/{prefix}/mediapipe"
    static_url = settings.STATIC_URL.rstrip("/")
    return f"{static_url}/{prefix}/mediapipe"
