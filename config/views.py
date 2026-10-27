"""Служебные страницы проекта: стартовая страница и health-проверка."""

import logging

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect, render

from rooms.forms import JoinCodeForm

logger = logging.getLogger(__name__)


def home(request: HttpRequest):
    # POST — студент вводит ID комнаты на главной и попадает на `/r/<code>/`.
    if request.method == "POST":
        join_form = JoinCodeForm(request.POST)
        if join_form.is_valid():
            return redirect("room_student:join", join_code=join_form.cleaned_data["join_code"])
        return render(request, "home.html", {"join_form": join_form}, status=400)

    return render(request, "home.html", {"join_form": JoinCodeForm()})


def htmx_demo(request: HttpRequest):
    """Небольшой фрагмент для проверки HTMX без перезагрузки страницы."""
    return render(request, "partials/htmx_demo.html")


def avatar_test(request: HttpRequest):
    """Тестовая страница аватара (C1): сцена, камера, свет и загрузка VRM."""
    return render(
        request,
        "static_pages/avatar.html",
        {
            "model_url": settings.AVATAR_MODEL_URL,
        },
    )


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
