"""HTTP-представления комнат для преподавателя и студентов."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from rooms.forms import GuestNameForm, RoomForm
from rooms.models import Participant, Room
from rooms.permissions import room_creator_required
from rooms.qr import build_join_url, room_qr_svg
from rooms.ratelimit import check_join_rate_limit
from rooms.services import (
    create_room,
    find_open_room,
    find_room,
    guest_name_for,
    guest_rooms,
    join_room_as_guest,
)


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


def _get_room_or_404(join_code: str) -> Room:
    # Код может повторяться у старых закрытых комнат; показываем последнюю.
    room = find_room(join_code)
    if room is None:
        raise Http404("Комната не найдена.")
    return get_object_or_404(Room, pk=room.pk)


def _can_view_room(user, room: Room) -> bool:
    return bool(
        user.is_authenticated
        and (getattr(user, "is_admin", False) or room.owner_id == user.pk)
    )


def room_detail(request: HttpRequest, join_code: str):
    room = _get_room_or_404(join_code)
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


@require_http_methods(["GET", "POST"])
def room_join(request: HttpRequest, join_code: str):
    """Вход студента: гостевая сессия по имени, без регистрации."""
    room = find_open_room(join_code)
    if room is None:
        closed = find_room(join_code)
        return render(
            request,
            "rooms/join_error.html",
            {"join_code": join_code.strip().upper(), "closed": closed is not None},
            status=404 if closed is None else 410,
        )

    already_joined = room.join_code in guest_rooms(request)

    if request.method == "POST":
        rate = check_join_rate_limit(request)
        if not rate.allowed:
            return render(
                request,
                "rooms/join_error.html",
                {
                    "join_code": room.join_code,
                    "rate_limited": True,
                    "retry_after": rate.retry_after,
                },
                status=429,
            )

        form = GuestNameForm(request.POST)
        if form.is_valid():
            join_room_as_guest(request, room, form.cleaned_data["name"])
            return redirect("room_student:live", join_code=room.join_code)
        # неверное имя не расходует попытки перебора ID
    else:
        form = GuestNameForm()

    return render(
        request,
        "rooms/join.html",
        {
            "room": room,
            "form": form,
            "already_joined": already_joined,
        },
    )


def room_student(request: HttpRequest, join_code: str):
    """Страница комнаты для студента (аватар и субтитры появятся в блоке C/D)."""
    room = find_open_room(join_code)
    if room is None:
        closed = find_room(join_code)
        return render(
            request,
            "rooms/join_error.html",
            {"join_code": join_code.strip().upper(), "closed": closed is not None},
            status=404 if closed is None else 410,
        )

    name = guest_name_for(request, room)
    participant = None
    if request.user.is_authenticated and (
        getattr(request.user, "is_admin", False) or room.owner_id == request.user.pk
    ):
        participant = Participant.objects.filter(room=room, user=request.user).first()
    elif name:
        participant = (
            Participant.objects.filter(room=room, session_key=request.session.session_key)
            .order_by("-joined_at")
            .first()
        )

    if participant is None and not name:
        return redirect("room_student:join", join_code=room.join_code)

    return render(
        request,
        "rooms/student.html",
        {
            "room": room,
            "participant": participant,
            "display_name": participant.display_name if participant else name,
        },
    )
