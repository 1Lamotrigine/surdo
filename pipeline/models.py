"""Модели конвейера фраз: ``Utterance`` и метрики отставания."""

from django.db import models

from rooms.models import Room


class Utterance(models.Model):
    """Произнесённая фраза: текст, глоссы и метрики обработки.

    Каждая фраза получает порядковый номер ``seq`` в пределах комнаты
    (см. ТЗ 5.7): клиент студента проигрывает по ``seq`` и игнорирует повторы
    после переподключения. Поле ``degraded`` помечает фразы, показанные только
    субтитрами из-за превышения таймаута ASR или LLM.
    """

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="utterances",
        verbose_name="комната",
    )
    seq = models.PositiveIntegerField("номер в комнате")
    text = models.TextField("текст фразы", blank=True)
    glosses = models.JSONField("глоссы", default=dict, blank=True)
    asr_ms = models.PositiveIntegerField("распознавание, мс", null=True, blank=True)
    gloss_ms = models.PositiveIntegerField("глоссы, мс", null=True, blank=True)
    display_lag_ms = models.PositiveIntegerField("отставание, мс", null=True, blank=True)
    playback = models.JSONField("параметры догона", default=dict, blank=True)
    degraded = models.BooleanField("только субтитры", default=False)
    started_at = models.DateTimeField("начата")
    created_at = models.DateTimeField("создана", auto_now_add=True)

    class Meta:
        verbose_name = "фраза"
        verbose_name_plural = "фразы"
        ordering = ("room", "seq")
        constraints = [
            models.UniqueConstraint(
                fields=("room", "seq"),
                name="unique_utterance_room_seq",
            ),
        ]
        indexes = [
            models.Index(fields=("room", "seq"), name="utterance_room_seq_idx"),
        ]

    def __str__(self) -> str:
        return f"#{self.seq} {self.text[:40]}"

    def as_event(self) -> dict:
        """Представление фразы для события ``utterance`` и истории."""
        return {
            "id": self.pk,
            "seq": self.seq,
            "text": self.text,
            "glosses": self.glosses,
            "degraded": self.degraded,
            "display_lag_ms": self.display_lag_ms,
            "playback": self.playback or {},
            "ts": self.started_at.isoformat(),
        }
