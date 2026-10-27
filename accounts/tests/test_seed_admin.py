"""Команда seed_admin."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import Role

pytestmark = pytest.mark.django_db


def test_seed_admin_creates_superuser(django_user_model):
    call_command(
        "seed_admin",
        email="Admin@Example.COM",
        password="StrongPass-12345",
        name="Администратор",
        verbosity=0,
    )

    user = django_user_model.objects.get(email="admin@example.com")
    assert user.role == Role.ADMIN
    assert user.name == "Администратор"
    assert user.is_staff
    assert user.is_superuser
    assert user.check_password("StrongPass-12345")


def test_seed_admin_is_idempotent_and_updates_password(django_user_model):
    call_command(
        "seed_admin",
        email="admin@example.com",
        password="StrongPass-12345",
        name="Старое имя",
        verbosity=0,
    )
    call_command(
        "seed_admin",
        email="admin@example.com",
        password="NewStrongPass-67890",
        name="Новое имя",
        verbosity=0,
    )

    assert django_user_model.objects.count() == 1
    user = django_user_model.objects.get(email="admin@example.com")
    assert user.name == "Новое имя"
    assert user.check_password("NewStrongPass-67890")


def test_seed_admin_requires_credentials():
    with pytest.raises(CommandError):
        call_command("seed_admin", email="", password="", verbosity=0)


def test_seed_admin_rejects_invalid_email():
    with pytest.raises(CommandError):
        call_command(
            "seed_admin",
            email="not-an-email",
            password="StrongPass-12345",
            verbosity=0,
        )
