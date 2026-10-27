"""Определение участника WebSocket-соединения комнаты.

Проверяет сессию Django в `connect()`: зарегистрированный пользователь
(владелец комнаты или админ) либо гость, который ввёл имя на `/r/<code>/`.
Скрытие в интерфейсе изоляцией не считается, поэтому проверка идёт на сервере.
"""

from dataclasses import dataclass

from rooms.models import Participant, Room

GUEST_ROOMS_SESSION_KEY = "rooms"


@dataclass(frozen=True)
class ConnectionIdentity:
    key: str
    name: str
    guest: bool
    participant_id: int | None


def _is_room_staff(user, room: Room) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and (getattr(user, "is_admin", False) or room.owner_id == user.pk)
    )


def _guest_name_from_session(scope, room: Room) -> tuple[str | None, str]:
    session = scope.get("session")
    if session is None:
        return None, ""
    mapping = session.get(GUEST_ROOMS_SESSION_KEY) or {}
    entry = mapping.get(room.join_code)
    session_key = session.session_key or ""
    if isinstance(entry, dict):
        return entry.get("name"), session_key
    return None, session_key


def resolve_connection(scope, room: Room, channel_name: str) -> ConnectionIdentity | None:
    """Вернуть участника соединения или None, если доступа нет."""
    user = scope.get("user")

    if _is_room_staff(user, room):
        name = getattr(user, "name", "") or getattr(user, "email", "")
        return ConnectionIdentity(
            key=f"user:{user.pk}",
            name=name,
            guest=False,
            participant_id=None,
        )

    name, session_key = _guest_name_from_session(scope, room)
    if not name or not session_key:
        return None

    participant = (
        Participant.objects.filter(room=room, session_key=session_key, removed_at__isnull=True)
        .order_by("-joined_at")
        .first()
    )
    if participant is None:
        return None

    # Несколько вкладок одного гостя — один участник, поэтому ключ по сессии.
    return ConnectionIdentity(
        key=f"session:{session_key}",
        name=participant.guest_name or name,
        guest=True,
        participant_id=participant.pk,
    )
