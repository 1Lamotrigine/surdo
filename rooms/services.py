"""Сервисные функции комнат."""

from django.db import IntegrityError, transaction

from rooms.codes import generate_join_code
from rooms.models import Room

MAX_JOIN_CODE_ATTEMPTS = 20


class JoinCodeGenerationError(RuntimeError):
    """Не удалось подобрать свободный код комнаты."""


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
