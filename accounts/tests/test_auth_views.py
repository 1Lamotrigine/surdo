"""Регистрация, вход, выход и доступ к админке."""

import pytest
from django.urls import reverse

from accounts.models import Role

pytestmark = pytest.mark.django_db


def test_registration_creates_teacher_and_logs_in(client, django_user_model):
    response = client.post(
        reverse("accounts:register"),
        {
            "name": "Иван Петров",
            "email": "Ivan@Example.COM",
            "password1": "StrongPass-12345",
            "password2": "StrongPass-12345",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("home")
    user = django_user_model.objects.get(email="ivan@example.com")
    assert user.role == Role.TEACHER
    assert user.check_password("StrongPass-12345")
    assert client.session["_auth_user_id"] == str(user.pk)


def test_registration_rejects_duplicate_email_case_insensitive(client, django_user_model):
    django_user_model.objects.create_user(
        email="dup@example.com",
        password="StrongPass-12345",
        name="Первый",
    )

    response = client.post(
        reverse("accounts:register"),
        {
            "name": "Второй",
            "email": "DUP@example.com",
            "password1": "StrongPass-12345",
            "password2": "StrongPass-12345",
        },
    )

    assert response.status_code == 200
    assert "уже зарегистрирован" in response.content.decode()
    assert django_user_model.objects.count() == 1


def test_login_by_email(client, django_user_model):
    user = django_user_model.objects.create_user(
        email="login@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )

    response = client.post(
        reverse("accounts:login"),
        {"username": "Login@Example.com", "password": "StrongPass-12345"},
    )

    assert response.status_code == 302
    assert response.url == reverse("home")
    assert client.session["_auth_user_id"] == str(user.pk)


def test_login_with_wrong_password_does_not_authenticate(client, django_user_model):
    django_user_model.objects.create_user(
        email="login@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )

    response = client.post(
        reverse("accounts:login"),
        {"username": "login@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_logout_requires_post_and_clears_session(client, django_user_model):
    user = django_user_model.objects.create_user(
        email="logout@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )
    client.force_login(user)

    assert client.get(reverse("accounts:logout")).status_code == 405

    response = client.post(reverse("accounts:logout"))

    assert response.status_code == 302
    assert response.url == reverse("home")
    assert "_auth_user_id" not in client.session


def test_teacher_cannot_open_admin(client, django_user_model):
    user = django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
    )
    client.force_login(user)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 302
    assert reverse("admin:login") in response.url


def test_admin_role_opens_admin(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        email="admin@example.com",
        password="StrongPass-12345",
        name="Администратор",
    )
    client.force_login(user)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200


def test_admin_can_log_in_with_email(client, django_user_model):
    django_user_model.objects.create_superuser(
        email="admin@example.com",
        password="StrongPass-12345",
        name="Администратор",
    )

    response = client.post(
        reverse("admin:login"),
        {"username": "ADMIN@Example.com", "password": "StrongPass-12345", "next": "/admin/"},
    )

    assert response.status_code == 302
    assert response.url == reverse("admin:index")
