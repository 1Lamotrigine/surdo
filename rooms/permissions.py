"""Проверки доступа к управлению комнатами."""

from collections.abc import Callable
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest


def can_create_room(user) -> bool:
    return bool(
        user.is_authenticated
        and (getattr(user, "is_teacher", False) or getattr(user, "is_admin", False))
    )


def is_room_member(request, room) -> bool:
    """Участник комнаты: владелец/админ или гость с записанным именем."""
    user = request.user
    if user.is_authenticated and (
        getattr(user, "is_admin", False) or room.owner_id == user.pk
    ):
        return True
    mapping = request.session.get("rooms") or {}
    return isinstance(mapping.get(room.join_code), dict)


def room_creator_required(view: Callable):
    """Пускать только преподавателя или администратора."""

    @login_required
    @wraps(view)
    def wrapped(request: HttpRequest, *args, **kwargs):
        if not can_create_room(request.user):
            raise PermissionDenied("Создавать комнаты может только преподаватель.")
        return view(request, *args, **kwargs)

    return wrapped
