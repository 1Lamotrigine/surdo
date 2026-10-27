"""JSON API конвейера фраз: приём текста от преподавателя (E2)."""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from pipeline.queue import submit_text
from pipeline.services import UtteranceValidationError, normalize_text
from rooms.models import Room
from rooms.services import find_open_room

logger = logging.getLogger(__name__)


def _can_send_text(user, room: Room) -> bool:
    """Отправлять фразы может только владелец комнаты или администратор."""
    return bool(
        user.is_authenticated
        and (getattr(user, "is_admin", False) or room.owner_id == user.pk)
    )


def _read_payload(request: HttpRequest):
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, JsonResponse({"detail": "Некорректный JSON."}, status=400)
        if not isinstance(payload, dict):
            return None, JsonResponse({"detail": "Ожидался JSON-объект."}, status=400)
        return payload, None
    return request.POST, None


@require_POST
def text_api(request: HttpRequest, join_code: str) -> JsonResponse:
    """Принять текст фразы и обработать его в фоне (ТЗ 7.4, этап E2).

    Доступ только у преподавателя этой комнаты (или администратора): гость и
    посторонний преподаватель получают 403, аноним — 401. Ответ 202 означает,
    что фраза встала в очередь: глоссы и сохранение ``Utterance`` идут в
    фоновом обработчике и не блокируют WebSocket-чат комнаты.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Требуется вход."}, status=401)

    room = find_open_room(join_code)
    if room is None:
        return JsonResponse({"detail": "Комната не найдена или закрыта."}, status=404)
    if not _can_send_text(request.user, room):
        return JsonResponse(
            {"detail": "Отправлять фразы может только преподаватель этой комнаты."},
            status=403,
        )

    payload, error = _read_payload(request)
    if error is not None:
        return error

    try:
        text = normalize_text(payload.get("text", "") or "")
    except UtteranceValidationError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    try:
        submit_text(room.pk, text, started_at=timezone.now())
    except RuntimeError:
        logger.exception("text queue unavailable: room=%s", room.pk)
        return JsonResponse({"detail": "Очередь обработки недоступна."}, status=503)

    return JsonResponse({"status": "accepted"}, status=202)
