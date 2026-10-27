"""JSON API комнат."""

import json

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from rooms.forms import RoomForm
from rooms.permissions import can_create_room
from rooms.qr import build_join_url
from rooms.services import create_room


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
