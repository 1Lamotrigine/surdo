"""Модель пользователя и роли."""

import pytest

from accounts.models import Role

pytestmark = pytest.mark.django_db


def test_create_user_normalizes_email_and_sets_teacher_role(django_user_model):
    user = django_user_model.objects.create_user(
        email=" Teacher@Example.COM ",
        password="StrongPass-12345",
        name="Иван Петров",
    )

    assert user.email == "teacher@example.com"
    assert user.role == Role.TEACHER
    assert user.name == "Иван Петров"
    assert user.check_password("StrongPass-12345")
    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser


def test_create_superuser_sets_admin_role(django_user_model):
    user = django_user_model.objects.create_superuser(
        email="admin@example.com",
        password="StrongPass-12345",
        name="Администратор",
    )

    assert user.role == Role.ADMIN
    assert user.is_staff
    assert user.is_superuser
    assert user.is_admin


@pytest.mark.parametrize(
    ("role", "flag", "is_true"),
    [
        (Role.TEACHER, "is_teacher", True),
        (Role.TEACHER, "is_editor", False),
        (Role.EDITOR, "is_editor", True),
        (Role.EXPERT, "is_expert", True),
        (Role.ADMIN, "is_admin", True),
        (Role.EXPERT, "is_admin", False),
    ],
)
def test_role_flags(role, flag, is_true, django_user_model):
    user = django_user_model.objects.create_user(
        email=f"{role}@example.com",
        password="StrongPass-12345",
        name="Тест",
        role=role,
    )

    assert getattr(user, flag) is is_true


def test_has_role(django_user_model):
    user = django_user_model.objects.create_user(
        email="editor@example.com",
        password="StrongPass-12345",
        name="Редактор",
        role=Role.EDITOR,
    )

    assert user.has_role(Role.EDITOR, Role.ADMIN)
    assert not user.has_role(Role.TEACHER)


def test_natural_key_lookup_is_case_insensitive(django_user_model):
    django_user_model.objects.create_user(
        email="expert@example.com",
        password="StrongPass-12345",
        name="Эксперт",
        role=Role.EXPERT,
    )

    found = django_user_model.objects.get_by_natural_key("EXPERT@EXAMPLE.COM")

    assert found.email == "expert@example.com"
