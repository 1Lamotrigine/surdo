"""HTTP-представления комнат для преподавателя."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404, redirect, render

from rooms.forms import RoomForm
from rooms.models import Room
from rooms.permissions import room_creator_required
from rooms.qr import build_join_url, room_qr_svg
from rooms.services import create_room


@room_creator_required
def create_room_view(request: HttpRequest):
    if request.method == "POST":
        form = RoomForm(request.POST)
        if form.is_valid():
            room = create_room(
                owner=request.user,
                title=form.cleaned_data["title"],
                demo_mode=form.cleaned_data["demo_mode"],
            )
            messages.success(request, f"Комната {room.join_code} создана.")
            return redirect("rooms:detail", join_code=room.join_code)
    else:
        form = RoomForm()

    return render(request, "rooms/create.html", {"form": form})


def _find_room(join_code: str) -> Room:
    # Код может повторяться у старых закрытых комнат; показываем последнюю.
    room = (
        Room.objects.filter(join_code__iexact=join_code)
        .select_related("owner")
        .order_by("-created_at")
        .first()
    )
    if room is None:
        raise Http404("Комната не найдена.")
    return get_object_or_404(Room, pk=room.pk)


def _can_view_room(user, room: Room) -> bool:
    return bool(
        user.is_authenticated
        and (getattr(user, "is_admin", False) or room.owner_id == user.pk)
    )


def room_detail(request: HttpRequest, join_code: str):
    room = _find_room(join_code)
    if not _can_view_room(request.user, room):
        raise PermissionDenied("Нет доступа к этой комнате.")

    join_url = build_join_url(request, room.join_code)
    return render(
        request,
        "rooms/detail.html",
        {
            "room": room,
            "join_url": join_url,
            "qr_svg": room_qr_svg(request, room),
        },
    )
