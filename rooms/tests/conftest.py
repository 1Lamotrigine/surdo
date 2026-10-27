"""Общие фикстуры тестов комнат."""

import pytest

from accounts.models import Role


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )


@pytest.fixture
def other_teacher(django_user_model):
    return django_user_model.objects.create_user(
        email="other@example.com",
        password="StrongPass-12345",
        name="Другой преподаватель",
    )


@pytest.fixture
def editor(django_user_model):
    return django_user_model.objects.create_user(
        email="editor@example.com",
        password="StrongPass-12345",
        name="Редактор",
        role=Role.EDITOR,
    )


@pytest.fixture
def admin_user(django_user_model):
    return django_user_model.objects.create_superuser(
        email="admin@example.com",
        password="StrongPass-12345",
        name="Администратор",
    )
