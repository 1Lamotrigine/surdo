"""Сервисные функции комнат."""

from django.db import IntegrityError, transaction

from rooms.codes import generate_join_code
from rooms.models import Message, Participant, Room

MAX_JOIN_CODE_ATTEMPTS = 20

# Ключи гостевой сессии студента (хранятся в Django-сессии, cookie HttpOnly).
GUEST_ROOMS_SESSION_KEY = "rooms"
GUEST_SESSION_KEY_SESSION_KEY = "session_key"
MAX_GUEST_NAME_LENGTH = 100

# Ограничения чата.
MAX_MESSAGE_LENGTH = 500
CHAT_HISTORY_LIMIT = 50


class JoinCodeGenerationError(RuntimeError):
    """Не удалось подобрать свободный код комнаты."""


class ChatValidationError(ValueError):
    """Сообщение чата не прошло проверку."""


def find_open_room(join_code: str) -> Room | None:
    """Найти открытую комнату по коду без учёта регистра."""
    code = (join_code or "").strip()
    if not code:
        return None
    return (
        Room.objects.filter(join_code__iexact=code, status=Room.Status.OPEN)
        .select_related("owner")
        .first()
    )


def find_room(join_code: str) -> Room | None:
    """Найти комнату по коду, включая закрытые (для понятного сообщения)."""
    code = (join_code or "").strip()
    if not code:
        return None
    return (
        Room.objects.filter(join_code__iexact=code)
        .select_related("owner")
        .order_by("-created_at")
        .first()
    )


def ensure_session_key(request) -> str:
    """Гарантировать наличие гостевого ключа сессии в Django-сессии."""
    if not request.session.session_key:
        request.session.create()
    key = request.session.get(GUEST_SESSION_KEY_SESSION_KEY)
    if not key:
        key = request.session.session_key
        request.session[GUEST_SESSION_KEY_SESSION_KEY] = key
    return key


def guest_rooms(request) -> dict:
    """Вернуть карту комнат, в которые входил этот гость: код → данные."""
    return dict(request.session.get(GUEST_ROOMS_SESSION_KEY) or {})


def guest_name_for(request, room: Room) -> str | None:
    entry = guest_rooms(request).get(room.join_code)
    if isinstance(entry, dict):
        return entry.get("name")
    return None


def join_room_as_guest(request, room: Room, name: str) -> Participant:
    """Создать (или обновить) гостевого участника комнаты."""
    session_key = ensure_session_key(request)
    participant, _ = Participant.objects.update_or_create(
        room=room,
        session_key=session_key,
        defaults={"guest_name": name, "removed_at": None},
    )
    mapping = dict(request.session.get(GUEST_ROOMS_SESSION_KEY) or {})
    mapping[room.join_code] = {
        "name": name,
        "participant_id": participant.pk,
        "room_id": room.pk,
    }
    request.session[GUEST_ROOMS_SESSION_KEY] = mapping
    return participant


def create_room(
    *,
    owner,
    title: str = "Урок",
    lang: str = Room.Language.RU,
    demo_mode: bool = False,
) -> Room:
    """Создать открытую комнату со свободным кодом.

    Код уникален только среди открытых комнат. Повторная попытка защищает
    от редкого совпадения случайных кодов.
    """
    for _ in range(MAX_JOIN_CODE_ATTEMPTS):
        join_code = generate_join_code()
        try:
            with transaction.atomic():
                return Room.objects.create(
                    owner=owner,
                    title=title,
                    lang=lang,
                    demo_mode=demo_mode,
                    join_code=join_code,
                )
        except IntegrityError:
            # Чужое нарушение ограничений не нужно маскировать повтором.
            if Room.objects.filter(
                status=Room.Status.OPEN,
                join_code=join_code,
            ).exists():
                continue
            raise

    raise JoinCodeGenerationError(
        f"Не удалось сгенерировать свободный код за {MAX_JOIN_CODE_ATTEMPTS} попыток"
    )


def clean_message_body(body: str) -> str:
    """Нормализовать и проверить текст чата."""
    text = " ".join((body or "").split())
    if not text:
        raise ChatValidationError("Сообщение не может быть пустым.")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ChatValidationError(f"Сообщение длиннее {MAX_MESSAGE_LENGTH} символов.")
    return text


def post_message(
    *,
    room_id: int,
    participant_id: int | None,
    author_name: str,
    body: str,
    is_teacher: bool = False,
) -> Message:
    """Сохранить сообщение чата комнаты."""
    text = clean_message_body(body)
    return Message.objects.create(
        room_id=room_id,
        participant_id=participant_id,
        author_name=author_name,
        is_teacher=is_teacher,
        body=text,
    )


def recent_messages(room: Room, *, limit: int = CHAT_HISTORY_LIMIT, after_id: int | None = None):
    """Последние (или новые после `after_id`) сообщения комнаты по возрастанию."""
    queryset = Message.objects.filter(room=room)
    if after_id is not None:
        queryset = queryset.filter(pk__gt=after_id).order_by("pk")
        return list(queryset[:limit])
    return list(queryset.order_by("-pk")[:limit])[::-1]
