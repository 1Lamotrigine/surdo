"""Модели комнат."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from rooms.codes import generate_join_code


class Room(models.Model):
    """Урок-комната: код действует, пока комната открыта."""

    class Status(models.TextChoices):
        OPEN = "open", "Открыта"
        CLOSED = "closed", "Закрыта"

    class Language(models.TextChoices):
        RU = "ru", "Русский"
        KK = "kk", "Казахский"

    title = models.CharField("название", max_length=200, default="Урок")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rooms",
        verbose_name="преподаватель",
    )
    lang = models.CharField(
        "язык",
        max_length=10,
        choices=Language.choices,
        default=Language.RU,
    )
    status = models.CharField(
        "статус",
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
    )
    join_code = models.CharField("код комнаты", max_length=6, blank=True, editable=False)
    demo_mode = models.BooleanField("демо-режим", default=False)
    created_at = models.DateTimeField("создана", auto_now_add=True)
    closed_at = models.DateTimeField("закрыта", null=True, blank=True)

    class Meta:
        verbose_name = "комната"
        verbose_name_plural = "комнаты"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("join_code",),
                condition=Q(status="open"),
                name="unique_open_room_join_code",
            ),
        ]
        indexes = [
            models.Index(fields=("owner", "status"), name="room_owner_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.join_code})"

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)

        if not self.join_code:
            self.join_code = generate_join_code()
            if update_fields is not None:
                update_fields.add("join_code")

        if self.status == self.Status.CLOSED and self.closed_at is None:
            self.closed_at = timezone.now()
            if update_fields is not None:
                update_fields.add("closed_at")

        if update_fields is not None:
            kwargs["update_fields"] = update_fields

        super().save(*args, **kwargs)

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.OPEN

    @property
    def is_closed(self) -> bool:
        return self.status == self.Status.CLOSED

    def close(self) -> None:
        """Закрыть комнату; повторный вызов ничего не меняет."""
        if self.is_closed:
            return
        self.status = self.Status.CLOSED
        self.closed_at = timezone.now()
        self.save(update_fields=("status", "closed_at"))


class Participant(models.Model):
    """Участник комнаты: зарегистрированный пользователь или гость по имени.

    Студент входит без регистрации: создаётся запись с `guest_name` и
    `session_key` из Django-сессии. `user` заполняется, если вошёл
    зарегистрированный пользователь (например, преподаватель).
    """

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="participants",
        verbose_name="комната",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="participations",
        verbose_name="пользователь",
    )
    guest_name = models.CharField("имя гостя", max_length=100, blank=True)
    session_key = models.CharField("ключ сессии", max_length=64, blank=True, db_index=True)
    joined_at = models.DateTimeField("вошёл", auto_now_add=True)
    removed_at = models.DateTimeField("удалён", null=True, blank=True)

    class Meta:
        verbose_name = "участник"
        verbose_name_plural = "участники"
        ordering = ("joined_at",)
        indexes = [
            models.Index(fields=("room", "removed_at"), name="participant_room_active_idx"),
        ]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        if self.user_id is not None:
            return self.user.name or self.user.email
        return self.guest_name

    @property
    def is_guest(self) -> bool:
        return self.user_id is None

    @property
    def is_active(self) -> bool:
        return self.removed_at is None

    def remove(self) -> None:
        """Удалить участника из комнаты; повторный вызов ничего не меняет."""
        if self.removed_at is not None:
            return
        self.removed_at = timezone.now()
        self.save(update_fields=("removed_at",))
