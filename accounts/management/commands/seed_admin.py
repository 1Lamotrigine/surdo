"""Создание начального администратора из аргументов или переменных окружения."""

import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from accounts.models import Role, User


class Command(BaseCommand):
    help = "Создаёт или обновляет администратора (роль admin, is_staff, is_superuser)."

    def add_arguments(self, parser):
        parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL"))
        parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD"))
        parser.add_argument(
            "--name",
            default=os.environ.get("ADMIN_NAME", "Администратор"),
        )

    def handle(self, *args, **options):
        email = (options["email"] or "").strip().lower()
        password = options["password"] or ""
        name = (options["name"] or "").strip() or "Администратор"

        if not email:
            raise CommandError("Укажите --email или ADMIN_EMAIL")
        if not password:
            raise CommandError("Укажите --password или ADMIN_PASSWORD")
        try:
            validate_email(email)
        except ValidationError as error:
            raise CommandError("Некорректный email администратора.") from error

        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if user is None:
            user = User(email=email, name=name)
        else:
            user.name = name

        try:
            validate_password(password, user=user)
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from error

        user.email = email
        user.name = name
        user.role = Role.ADMIN
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()

        action = "создан" if created else "обновлён"
        self.stdout.write(self.style.SUCCESS(f"Администратор {email} {action}."))
