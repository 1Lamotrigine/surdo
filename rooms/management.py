"""Управление комнатой: закрытие, смена ID, удаление участника.

Логика вынесена из views, чтобы её могли переиспользовать HTTP-представления,
JSON API и consumer. Рассылка событий идёт в группу Channels `room_<id>`
(синхронный код — через `async_to_sync`).

События (ТЗ 7.3, 7.6):

- `room_closed` — комната закрыта; сервер рассылает его и закрывает соединения;
- `participant_removed` — участник удалён преподавателем; соединения этого
  участника закрываются (остальные видят обновлённый presence);
- `presence` — обновлённый список участников.

Смена ID не меняет `room.id`, поэтому группа остаётся той же: старый код и QR
перестают работать для новых подключений (код ищется среди открытых комнат),
а уже подключённые вкладки продолжают получать события до переподключения.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction

from rooms import presence
from rooms.codes import generate_join_code
from rooms.models import Participant, Room

logger = logging.getLogger(__name__)

MAX_JOIN_CODE_ATTEMPTS = 20


class JoinCodeGenerationError(RuntimeError):
    """Не удалось подобрать свободный код комнаты."""


def group_name_for(room_id: int) -> str:
    return f"room_{room_id}"


def _group_send(room_id: int, message: dict) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(group_name_for(room_id), message)


def rotate_join_code(room: Room) -> str:
    """Выдать комнате новый код; старый перестаёт находиться.

    Код уникален только среди открытых комнат, поэтому повторяем попытку при
    редкой коллизии. Группа Channels не меняется (она по `room.id`).
    """
    for _ in range(MAX_JOIN_CODE_ATTEMPTS):
        candidate = generate_join_code()
        try:
            with transaction.atomic():
                room.join_code = candidate
                room.save(update_fields=("join_code",))
            return candidate
        except IntegrityError:
            # Код занят другой открытой комнатой — пробуем ещё раз.
            if Room.objects.filter(
                status=Room.Status.OPEN,
                join_code=candidate,
            ).exists():
                continue
            raise
    raise JoinCodeGenerationError(
        f"Не удалось сгенерировать свободный код за {MAX_JOIN_CODE_ATTEMPTS} попыток"
    )


def close_room(room: Room) -> None:
    """Закрыть комнату, уведомить участников и закрыть их соединения.

    Идемпотентно: повторный вызов не рассылает событие второй раз.
    """
    if room.is_closed:
        return
    room.close()
    presence.clear(room.pk)
    _group_send(room.pk, {"type": "room.closed", "room_id": room.pk})


def remove_participant(participant: Participant) -> None:
    """Удалить участника, закрыть его соединения и обновить presence.

    Гостя определяем по `session_key`: соединение гостя имеет ключ
    `session:<session_key>`, поэтому событие с этим ключом закрывает только
    его вкладки. Presence чистим, чтобы удалённый сразу исчез из списка.
    """
    participant.remove()
    key = f"session:{participant.session_key}" if participant.session_key else None
    if key:
        presence.remove_key(participant.room_id, key)
    _group_send(
        participant.room_id,
        {
            "type": "participant.removed",
            "participant_id": participant.pk,
            "connection_key": key,
            "participants": [entry.to_dict() for entry in presence.list_participants(participant.room_id)],
        },
    )
