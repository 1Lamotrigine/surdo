"""Интерфейс эксперта: очередь на проверке и карточка жеста с решением."""

import pytest
from django.urls import reverse

from accounts.models import Role
from dictionary.models import DictionaryVersion, Language, Sign, SignClip, SignStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def editor(django_user_model):
    return django_user_model.objects.create_user(
        email="editor@example.com",
        password="StrongPass-12345",
        name="Редактор",
        role=Role.EDITOR,
    )


@pytest.fixture
def expert(django_user_model):
    return django_user_model.objects.create_user(
        email="expert@example.com",
        password="StrongPass-12345",
        name="Эксперт",
        role=Role.EXPERT,
    )


@pytest.fixture
def teacher(django_user_model):
    return django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
        role=Role.TEACHER,
    )


# --- Очередь на проверке ---------------------------------------------------


def test_queue_requires_login(client):
    response = client.get(reverse("dictionary:review-queue"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_queue_rejects_teacher(client, teacher):
    client.force_login(teacher)

    response = client.get(reverse("dictionary:review-queue"))

    assert response.status_code == 403


def test_queue_rejects_editor(client, editor):
    client.force_login(editor)

    response = client.get(reverse("dictionary:review-queue"))

    assert response.status_code == 403


def test_queue_lists_only_review_signs(client, expert, editor):
    Sign.objects.create(gloss="НА_ПРОВЕРКЕ", status=SignStatus.REVIEW, recorded_by=editor)
    Sign.objects.create(gloss="ЧЕРНОВИК", status=SignStatus.DRAFT, recorded_by=editor)
    Sign.objects.create(gloss="ПРОВЕРЕН", status=SignStatus.VERIFIED, recorded_by=editor)
    client.force_login(expert)

    response = client.get(reverse("dictionary:review-queue"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "НА_ПРОВЕРКЕ" in body
    assert "ЧЕРНОВИК" not in body
    assert "ПРОВЕРЕН" not in body


def test_queue_is_empty_message(client, expert):
    client.force_login(expert)

    response = client.get(reverse("dictionary:review-queue"))

    assert response.status_code == 200
    assert "Жестов на проверке нет" in response.content.decode()


# --- Карточка жеста --------------------------------------------------------


def test_card_shows_clip_link(client, expert, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW, recorded_by=editor)
    clip = SignClip.objects.create(sign=sign, file="clips/a.json.gz", frames=54)
    client.force_login(expert)

    response = client.get(reverse("dictionary:review-sign", kwargs={"sign_id": sign.pk}))

    assert response.status_code == 200
    body = response.content.decode()
    assert "УЧЕБНИК" in body
    assert f"/media/clips/{clip.pk}.json.gz" in body


def test_card_without_clip_warns(client, expert, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW, recorded_by=editor)
    client.force_login(expert)

    response = client.get(reverse("dictionary:review-sign", kwargs={"sign_id": sign.pk}))

    assert response.status_code == 200
    assert "У жеста нет клипа" in response.content.decode()


def test_card_requires_expert(client, teacher, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW, recorded_by=editor)
    client.force_login(teacher)

    response = client.get(reverse("dictionary:review-sign", kwargs={"sign_id": sign.pk}))

    assert response.status_code == 403


def test_card_unknown_sign_returns_404(client, expert):
    client.force_login(expert)

    response = client.get(reverse("dictionary:review-sign", kwargs={"sign_id": 999999}))

    assert response.status_code == 404


# --- Решение через форму ---------------------------------------------------


def test_expert_approves_from_form(client, expert, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW, recorded_by=editor)
    client.force_login(expert)

    response = client.post(
        reverse("dictionary:review-sign", kwargs={"sign_id": sign.pk}),
        {"decision": "approve", "comment": "Хорошо"},
    )

    assert response.status_code == 302
    assert response.url == reverse("dictionary:review-queue")
    sign.refresh_from_db()
    assert sign.status == SignStatus.VERIFIED
    assert sign.verified_by == expert
    assert sign.comment == "Хорошо"
    assert DictionaryVersion.current(Language.RSL).number == 1


def test_expert_rejects_from_form(client, expert, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW, recorded_by=editor)
    client.force_login(expert)

    client.post(
        reverse("dictionary:review-sign", kwargs={"sign_id": sign.pk}),
        {"decision": "reject", "comment": "Переделать"},
    )

    sign.refresh_from_db()
    assert sign.status == SignStatus.REJECTED
    assert DictionaryVersion.objects.count() == 0


def test_form_without_decision_does_not_change_status(client, expert, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW, recorded_by=editor)
    client.force_login(expert)

    response = client.post(
        reverse("dictionary:review-sign", kwargs={"sign_id": sign.pk}),
        {"comment": "комментарий"},
    )

    assert response.status_code == 302
    sign.refresh_from_db()
    assert sign.status == SignStatus.REVIEW


def test_form_ignores_forbidden_transition(client, expert, editor):
    """Утверждение черновика отклоняется сервисом, статус не меняется."""
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.DRAFT, recorded_by=editor)
    client.force_login(expert)

    response = client.post(
        reverse("dictionary:review-sign", kwargs={"sign_id": sign.pk}),
        {"decision": "approve"},
    )

    assert response.status_code == 302
    sign.refresh_from_db()
    assert sign.status == SignStatus.DRAFT
    assert DictionaryVersion.objects.count() == 0
