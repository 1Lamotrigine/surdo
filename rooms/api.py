"""JSON API комнат."""

import json

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from rooms.forms import RoomForm
from rooms.models import Room
from rooms.permissions import can_create_room, is_room_member
from rooms.qr import build_join_url
from rooms.services import create_room, find_open_room, recent_messages


@require_POST
def create_room_api(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Требуется вход."}, status=401)
    if not can_create_room(request.user):
        return JsonResponse({"detail": "Создавать комнаты может только преподаватель."}, status=403)

    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"detail": "Некорректный JSON."}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({"detail": "Ожидался JSON-объект."}, status=400)
    else:
        payload = request.POST

    form = RoomForm(payload)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)

    room = create_room(
        owner=request.user,
        title=form.cleaned_data["title"],
        demo_mode=form.cleaned_data["demo_mode"],
    )
    return JsonResponse(
        {
            "id": room.pk,
            "join_code": room.join_code,
            "join_url": build_join_url(request, room.join_code),
        },
        status=201,
    )


def _parse_int(value, *, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@require_GET
def chat_history_api(request: HttpRequest, join_code: str) -> JsonResponse:
    """Пропущенные сообщения чата для переподключения.

    `?after_message_id=<id>` возвращает только новые сообщения; без него —
    последние (до 50). Доступ только у участников комнаты.
    """
    room = find_open_room(join_code) or get_object_or_404(
        Room, join_code__iexact=join_code, status=Room.Status.CLOSED
    )
    if not is_room_member(request, room):
        return JsonResponse({"detail": "Нет доступа к этой комнате."}, status=403)

    after_id = _parse_int(request.GET.get("after_message_id"))
    messages = recent_messages(room, after_id=after_id)
    return JsonResponse(
        {
            "room": room.join_code,
            "messages": [message.as_event() for message in messages],
        }
    )
