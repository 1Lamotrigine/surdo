"""Хранение персональных данных (ТЗ 17): удаление старых записей по cron.

Хранятся имя гостя, текст чата и фразы. Срок задаётся `RETENTION_DAYS`;
команда `purge_old_data` вызывает `purge_expired_data` и удаляет:

- закрытые комнаты, закрытые раньше срока (каскадом уходят участники, чат и
  фразы такой комнаты);
- сообщения чата открытых комнат старше срока;
- фразы (`pipeline.Utterance`) открытых комнат старше срока.

Открытые комнаты не трогаем: занятие может идти дольше срока хранения, а его
данные ещё нужны. Аудио не хранится вовсе, поэтому чистить нечего.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from pipeline.models import Utterance
from rooms.models import Message, Room


@dataclass(frozen=True)
class PurgeResult:
    """Сколько записей удалено (для лога и тестов)."""

    messages: int
    utterances: int
    rooms: int

    @property
    def total(self) -> int:
        return self.messages + self.utterances + self.rooms


def purge_expired_data(*, days: int | None = None, now=None) -> PurgeResult:
    """Удалить записи старше `days` дней и вернуть счётчики.

    `days` по умолчанию берётся из `settings.RETENTION_DAYS`; `now` можно
    подменить в тестах, чтобы не зависеть от системных часов.
    """
    days = settings.RETENTION_DAYS if days is None else days
    cutoff = (now or timezone.now()) - timedelta(days=days)

    # Сначала закрытые комнаты: удаление каскадом (on_delete=CASCADE) снимает
    # их участников, чат и фразы. После этого оставшиеся счётчики относятся к
    # ещё открытым комнатам, и суммы не пересекаются.
    rooms, _ = Room.objects.filter(status=Room.Status.CLOSED, closed_at__lt=cutoff).delete()
    messages, _ = Message.objects.filter(created_at__lt=cutoff).delete()
    utterances, _ = Utterance.objects.filter(created_at__lt=cutoff).delete()

    return PurgeResult(messages=messages, utterances=utterances, rooms=rooms)
