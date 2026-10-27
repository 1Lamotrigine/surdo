"""Сервисные переходы статусов: роли, версия словаря, поля проверки."""

import pytest

from accounts.models import Role
from dictionary.models import DictionaryVersion, Language, Sign, SignStatus
from dictionary.services import (
    SignPermissionError,
    SignValidationError,
    reject_sign,
    submit_for_review,
    transition_sign,
    verify_sign,
)

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


@pytest.fixture
def admin_user(django_user_model):
    return django_user_model.objects.create_superuser(
        email="admin@example.com",
        password="StrongPass-12345",
        name="Администратор",
    )


def test_editor_submits_draft_for_review(editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)

    result = submit_for_review(sign, actor=editor)

    assert result.status == SignStatus.REVIEW
    sign.refresh_from_db()
    assert sign.status == SignStatus.REVIEW


def test_expert_verifies_from_review(expert, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)

    verify_sign(sign, actor=expert, comment="Читается хорошо")

    sign.refresh_from_db()
    assert sign.status == SignStatus.VERIFIED
    assert sign.verified_by == expert
    assert sign.verified_at is not None
    assert sign.comment == "Читается хорошо"


def test_verifying_bumps_dictionary_version(expert):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)

    verify_sign(sign, actor=expert)

    assert DictionaryVersion.current(Language.RSL).number == 1


def test_each_verification_increments_version(expert):
    first = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)
    second = Sign.objects.create(gloss="СТРАНИЦА", status=SignStatus.REVIEW)

    verify_sign(first, actor=expert)
    verify_sign(second, actor=expert)

    assert DictionaryVersion.objects.filter(lang=Language.RSL).count() == 2
    assert DictionaryVersion.current(Language.RSL).number == 2


def test_version_is_per_language(expert):
    rsl = Sign.objects.create(gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.REVIEW)
    ksl = Sign.objects.create(gloss="КІТАП", lang=Language.KSL, status=SignStatus.REVIEW)

    verify_sign(rsl, actor=expert)
    verify_sign(ksl, actor=expert)

    assert DictionaryVersion.current(Language.RSL).number == 1
    assert DictionaryVersion.current(Language.KSL).number == 1


def test_expert_rejects_from_review(expert):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)

    reject_sign(sign, actor=expert, comment="Слишком быстро")

    sign.refresh_from_db()
    assert sign.status == SignStatus.REJECTED
    assert sign.comment == "Слишком быстро"
    assert sign.verified_by is None


def test_rejected_can_be_resubmitted(editor, expert):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)
    reject_sign(sign, actor=expert, comment="Переделать")

    submit_for_review(sign, actor=editor)

    sign.refresh_from_db()
    assert sign.status == SignStatus.REVIEW


def test_expert_can_reopen_verified_sign(expert):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)
    verify_sign(sign, actor=expert)

    transition_sign(sign, to_status=SignStatus.REVIEW, actor=expert)

    sign.refresh_from_db()
    assert sign.status == SignStatus.REVIEW


def test_editor_cannot_verify(editor, expert):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)

    with pytest.raises(SignPermissionError):
        verify_sign(sign, actor=editor)

    sign.refresh_from_db()
    assert sign.status == SignStatus.REVIEW
    assert DictionaryVersion.objects.count() == 0


def test_editor_cannot_reject(editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)

    with pytest.raises(SignPermissionError):
        reject_sign(sign, actor=editor)


def test_teacher_cannot_submit(teacher):
    sign = Sign.objects.create(gloss="УЧЕБНИК")

    with pytest.raises(SignPermissionError):
        submit_for_review(sign, actor=teacher)


def test_expert_can_submit_for_review(expert):
    """Эксперт-носитель также закрывает роль редактора."""
    sign = Sign.objects.create(gloss="УЧЕБНИК")

    submit_for_review(sign, actor=expert)

    sign.refresh_from_db()
    assert sign.status == SignStatus.REVIEW


def test_admin_can_verify(admin_user):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)

    verify_sign(sign, actor=admin_user)

    sign.refresh_from_db()
    assert sign.status == SignStatus.VERIFIED
    assert sign.verified_by == admin_user


def test_forbidden_transition_raises_validation_error(expert):
    sign = Sign.objects.create(gloss="УЧЕБНИК")  # draft

    with pytest.raises(SignValidationError):
        transition_sign(sign, to_status=SignStatus.VERIFIED, actor=expert)

    sign.refresh_from_db()
    assert sign.status == SignStatus.DRAFT
    assert DictionaryVersion.objects.count() == 0


def test_same_status_raises_validation_error(editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)

    with pytest.raises(SignValidationError):
        transition_sign(sign, to_status=SignStatus.REVIEW, actor=editor)


def test_unknown_status_raises_validation_error(editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК")

    with pytest.raises(SignValidationError):
        transition_sign(sign, to_status="nonsense", actor=editor)


def test_model_verify_goes_through_service_and_bumps_version(expert):
    """``Sign.verify()`` — обёртка над сервисом: тоже растит версию словаря."""
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)

    sign.verify(expert, comment="ОК")

    assert DictionaryVersion.current(Language.RSL).number == 1
