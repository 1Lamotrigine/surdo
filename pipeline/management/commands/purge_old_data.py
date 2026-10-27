"""Команда удаления старых персональных данных (ТЗ 17, cron).

Запуск:

    python manage.py purge_old_data
    python manage.py purge_old_data --days 30 --dry-run

По умолчанию срок — `RETENTION_DAYS` из окружения. `--dry-run` показывает,
сколько записей попадёт под удаление, ничего не удаляя.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from pipeline.models import Utterance
from pipeline.retention import purge_expired_data
from rooms.models import Message, Room


class Command(BaseCommand):
    help = "Удалить чат, фразы и закрытые комнаты старше RETENTION_DAYS дней."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="срок хранения в днях (по умолчанию RETENTION_DAYS)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="только показать, сколько записей будет удалено",
        )

    def handle(self, *args, **options):
        days = options["days"] if options["days"] is not None else settings.RETENTION_DAYS
        cutoff = timezone.now() - timedelta(days=days)

        if options["dry_run"]:
            rooms = Room.objects.filter(status=Room.Status.CLOSED, closed_at__lt=cutoff).count()
            messages = Message.objects.filter(created_at__lt=cutoff).count()
            utterances = Utterance.objects.filter(created_at__lt=cutoff).count()
            self.stdout.write(
                f"dry-run: к удалению комнаты={rooms}, сообщения={messages}, "
                f"фразы={utterances} (старше {days} дней)"
            )
            return

        result = purge_expired_data(days=days)
        self.stdout.write(
            self.style.SUCCESS(
                f"Удалено: сообщений={result.messages}, фраз={result.utterances}, "
                f"комнат={result.rooms} (старше {days} дней)"
            )
        )
