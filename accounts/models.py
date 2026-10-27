"""Пользователь проекта и роли."""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class Role(models.TextChoices):
    TEACHER = "teacher", "Преподаватель"
    EDITOR = "editor", "Редактор словаря"
    EXPERT = "expert", "Эксперт-носитель"
    ADMIN = "admin", "Администратор"


class UserManager(BaseUserManager):
    """Менеджер пользователей с email вместо username."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("Email обязателен")
        email = self.normalize_email(email).strip().lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("role", Role.TEACHER)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("role", Role.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Суперпользователь должен иметь is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Суперпользователь должен иметь is_superuser=True")
        if extra_fields.get("role") != Role.ADMIN:
            raise ValueError("Суперпользователь должен иметь роль admin")

        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username: str):
        # Вход по email без учёта регистра.
        return self.get(email__iexact=username.strip())


class User(AbstractUser):
    """Пользователь сервиса: вход по email, роль и отображаемое имя."""

    username = None
    email = models.EmailField("email", unique=True)
    name = models.CharField("имя", max_length=150)
    role = models.CharField(
        "роль",
        max_length=20,
        choices=Role.choices,
        default=Role.TEACHER,
    )
    created_at = models.DateTimeField("создан", auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    objects = UserManager()

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN or self.is_superuser

    @property
    def is_teacher(self) -> bool:
        return self.role == Role.TEACHER

    @property
    def is_editor(self) -> bool:
        return self.role == Role.EDITOR

    @property
    def is_expert(self) -> bool:
        return self.role == Role.EXPERT

    def has_role(self, *roles: str) -> bool:
        return self.role in roles
