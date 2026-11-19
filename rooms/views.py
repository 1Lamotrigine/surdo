"""HTTP-представления комнат для преподавателя и студентов."""

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from pipeline.queue import submit_text
from pipeline.services import (
    MAX_UTTERANCE_TEXT_LENGTH,
    UtteranceValidationError,
    normalize_text,
    recent_room_utterances,
)
from rooms.forms import GuestNameForm, RoomForm
from rooms.management import close_room, remove_participant, rotate_join_code
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


def _phrase_feed_context(room: Room) -> dict:
    return {"phrases": recent_room_utterances(room)}


def _phrase_form_context(
    room: Room,
    *,
    text: str = "",
    error: str = "",
    status: str = "",
) -> dict:
    return {
        "room": room,
        "text": text,
        "error": error,
        "status": status,
        "max_text_length": MAX_UTTERANCE_TEXT_LENGTH,
    }


@room_creator_required
def room_live(request: HttpRequest, join_code: str):
    """Панель преподавателя: ввод фраз, лента, отставание, чат и участники (E5)."""
    room = _get_room_or_404(join_code)
    if not _can_view_room(request.user, room):
        raise PermissionDenied("Нет доступа к этой комнате.")

    context = {
        "room": room,
        "join_url": build_join_url(request, room.join_code),
        "qr_svg": room_qr_svg(request, room),
        "avatar_model_url": settings.AVATAR_MODEL_URL,
        **_phrase_form_context(room),
        **_phrase_feed_context(room),
    }
    return render(request, "rooms/live.html", context)


@require_GET
@room_creator_required
def room_live_feed(request: HttpRequest, join_code: str):
    """HTMX-фрагмент ленты фраз: последние ``Utterance`` комнаты."""
    room = _get_room_or_404(join_code)
    if not _can_view_room(request.user, room):
        raise PermissionDenied("Нет доступа к этой комнате.")

    return render(
        request,
        "rooms/_phrase_feed.html",
        {"room": room, **_phrase_feed_context(room)},
    )


@require_POST
@room_creator_required
def room_live_phrase(request: HttpRequest, join_code: str):
    """Принять фразу из формы преподавателя и вернуть HTMX-фрагмент формы.

    Текст проходит ту же проверку, что и JSON API E2, и ставится в фоновую
    очередь. HTML-ответ нужен для HTMX; без него форма работает как обычный
    POST с редиректом и сообщением.
    """
    room = _get_room_or_404(join_code)
    if not _can_view_room(request.user, room):
        raise PermissionDenied("Нет доступа к этой комнате.")

    raw_text = request.POST.get("text", "")
    error = ""
    status = ""
    if room.is_closed:
        error = "Комната закрыта: новые фразы отправить нельзя."
    else:
        try:
            clean_text = normalize_text(raw_text)
        except UtteranceValidationError as exc:
            error = str(exc)
        else:
            try:
                submit_text(room.pk, clean_text, started_at=timezone.now())
            except RuntimeError:
                error = "Очередь обработки недоступна. Попробуйте ещё раз."
            else:
                status = "Фраза поставлена в очередь."
                raw_text = ""

    is_htmx = request.headers.get("HX-Request") == "true"
    if not is_htmx:
        if error:
            messages.error(request, error)
        else:
            messages.success(request, status)
        return redirect("rooms:live", join_code=room.join_code)

    response = render(
        request,
        "rooms/_phrase_form.html",
        _phrase_form_context(room, text=raw_text, error=error, status=status),
    )
    if status:
        response["HX-Trigger"] = "phrase-saved"
    return response


@require_POST
@room_creator_required
def room_close(request: HttpRequest, join_code: str):
    """Закрыть комнату: старый ID и QR перестают работать."""
    room = _get_room_or_404(join_code)
    if not _can_view_room(request.user, room):
        raise PermissionDenied("Нет доступа к этой комнате.")

    close_room(room)
    messages.success(request, f"Комната {room.join_code} закрыта.")
    return redirect("rooms:detail", join_code=room.join_code)


@require_POST
@room_creator_required
def room_rotate_code(request: HttpRequest, join_code: str):
    """Сменить ID комнаты: старый QR перестаёт работать."""
    room = _get_room_or_404(join_code)
    if not _can_view_room(request.user, room):
        raise PermissionDenied("Нет доступа к этой комнате.")

    if room.is_closed:
        messages.error(request, "Комната закрыта: ID не меняется.")
        return redirect("rooms:detail", join_code=room.join_code)

    old_code = room.join_code
    new_code = rotate_join_code(room)
    messages.success(request, f"ID комнаты изменён: {old_code} → {new_code}.")
    return redirect("rooms:detail", join_code=new_code)


@require_POST
@room_creator_required
def room_remove_participant(request: HttpRequest, join_code: str, participant_id: int):
    """Удалить участника из комнаты."""
    room = _get_room_or_404(join_code)
    if not _can_view_room(request.user, room):
        raise PermissionDenied("Нет доступа к этой комнате.")

    participant = get_object_or_404(Participant, pk=participant_id, room=room)
    if participant.user_id is not None and participant.user_id == room.owner_id:
        messages.error(request, "Нельзя удалить владельца комнаты.")
        return redirect("rooms:live", join_code=room.join_code)

    remove_participant(participant)
    messages.success(request, f"Участник {participant.display_name} удалён.")
    return redirect("rooms:live", join_code=room.join_code)


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
    """Страница комнаты для студента: аватар, клипы и субтитры (E3)."""
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
            Participant.objects.filter(
                room=room,
                session_key=request.session.session_key,
                removed_at__isnull=True,
            )
            .order_by("-joined_at")
            .first()
        )

    if participant is None and not name:
        return redirect("room_student:join", join_code=room.join_code)
    if participant is None and name:
        # Удалён преподавателем: отправляем на форму входа заново.
        messages.warning(request, "Преподаватель удалил вас из комнаты. Войдите снова.")
        return redirect("room_student:join", join_code=room.join_code)

    return render(
        request,
        "rooms/student.html",
        {
            "room": room,
            "participant": participant,
            "display_name": participant.display_name if participant else name,
            "avatar_model_url": settings.AVATAR_MODEL_URL,
        },
    )
