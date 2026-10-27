"""Служебные страницы проекта: стартовая страница и health-проверка."""

import logging

from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render

logger = logging.getLogger(__name__)


def home(request: HttpRequest):
    return render(request, "home.html")


def health(request: HttpRequest) -> JsonResponse:
    checks: dict[str, str] = {}
    healthy = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 — health не должен падать из-за базы
        logger.exception("health: database check failed")
        checks["database"] = "error"
        healthy = False

    return JsonResponse(
        {"status": "ok" if healthy else "error", "checks": checks},
        status=200 if healthy else 503,
    )
