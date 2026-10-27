"""Админка словаря: регистрация моделей, список, фильтр и просмотр клипа."""

import pytest
from django.contrib import admin

from accounts.models import Role
from dictionary.admin import (
    DictionaryVersionAdmin,
    SignAdmin,
    SignClipAdmin,
    UnknownWordAdmin,
)
from dictionary.models import (
    DictionaryVersion,
    Language,
    Sign,
    SignClip,
    SignStatus,
    UnknownWord,
    UnknownWordStatus,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(django_user_model):
    return django_user_model.objects.create_superuser(
        email="admin@example.com",
        password="StrongPass-12345",
        name="Администратор",
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
def expert(django_user_model):
    return django_user_model.objects.create_user(
        email="expert@example.com",
        password="StrongPass-12345",
        name="Эксперт",
        role=Role.EXPERT,
    )


# --- Регистрация моделей ---------------------------------------------------


@pytest.mark.parametrize(
    ("model", "admin_class"),
    [
        (Sign, SignAdmin),
        (SignClip, SignClipAdmin),
        (UnknownWord, UnknownWordAdmin),
        (DictionaryVersion, DictionaryVersionAdmin),
    ],
)
def test_models_are_registered_in_admin(model, admin_class):
    assert model in admin.site._registry
    assert isinstance(admin.site._registry[model], admin_class)


# --- Список, фильтр и поиск ------------------------------------------------


def test_sign_changelist_shows_status_filter(client, admin_user, editor):
    Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.VERIFIED, recorded_by=editor)
    Sign.objects.create(gloss="ЧЕРНОВИК", status=SignStatus.DRAFT, recorded_by=editor)
    client.force_login(admin_user)

    response = client.get("/admin/dictionary/sign/")

    assert response.status_code == 200
    assert "УЧЕБНИК" in response.content.decode()
    assert "ЧЕРНОВИК" in response.content.decode()

    filtered = client.get("/admin/dictionary/sign/", {"status": SignStatus.VERIFIED})
    body = filtered.content.decode()
    assert "УЧЕБНИК" in body
    assert "ЧЕРНОВИК" not in body


def test_sign_search_by_gloss(client, admin_user, editor):
    Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)
    Sign.objects.create(gloss="СТРАНИЦА", recorded_by=editor)
    client.force_login(admin_user)

    response = client.get("/admin/dictionary/sign/", {"q": "УЧЕБНИК"})

    body = response.content.decode()
    assert "УЧЕБНИК" in body
    assert "СТРАНИЦА" not in body


def test_unknown_word_list_orders_by_count(client, admin_user):
    UnknownWord.objects.create(lemma="редкое", count=1)
    UnknownWord.objects.create(lemma="частое", count=9)
    client.force_login(admin_user)

    response = client.get("/admin/dictionary/unknownword/")

    assert response.status_code == 200
    body = response.content.decode()
    assert body.index("частое") < body.index("редкое")


def _run_unknown_action(client, queryset_ids, action: str):
    return client.post(
        "/admin/dictionary/unknownword/",
        {
            "action": action,
            "_selected_action": [str(pk) for pk in queryset_ids],
        },
        follow=True,
    )


def test_admin_takes_word_in_work(client, admin_user):
    word = UnknownWord.objects.create(lemma="Иванов")
    client.force_login(admin_user)

    _run_unknown_action(client, [word.pk], "queue_words")

    word.refresh_from_db()
    assert word.status == UnknownWordStatus.QUEUED


def test_admin_marks_word_recorded(client, admin_user):
    word = UnknownWord.objects.create(lemma="Иванов", status=UnknownWordStatus.QUEUED)
    client.force_login(admin_user)

    _run_unknown_action(client, [word.pk], "mark_words_recorded")

    word.refresh_from_db()
    assert word.status == UnknownWordStatus.RECORDED


def test_admin_action_skips_forbidden_word_transition(client, admin_user):
    word = UnknownWord.objects.create(lemma="Иванов")  # new
    client.force_login(admin_user)

    response = _run_unknown_action(client, [word.pk], "mark_words_recorded")

    assert response.status_code == 200
    word.refresh_from_db()
    assert word.status == UnknownWordStatus.NEW


# --- Просмотр клипа --------------------------------------------------------


def test_sign_change_page_links_to_clip(client, admin_user, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)
    clip = SignClip.objects.create(
        sign=sign, file="clips/a.json.gz", frames=54, size_bytes=2048
    )
    client.force_login(admin_user)

    response = client.get(f"/admin/dictionary/sign/{sign.pk}/change/")

    assert response.status_code == 200
    body = response.content.decode()
    assert f"/media/clips/{clip.pk}.json.gz" in body


def test_sign_change_page_without_clip(client, admin_user, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)
    client.force_login(admin_user)

    response = client.get(f"/admin/dictionary/sign/{sign.pk}/change/")

    assert response.status_code == 200
    assert "Клипа пока нет" in response.content.decode()


def test_sign_clip_changelist(client, admin_user, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)
    SignClip.objects.create(sign=sign, file="clips/a.json.gz", frames=54)
    client.force_login(admin_user)

    response = client.get("/admin/dictionary/signclip/")

    assert response.status_code == 200


# --- Действия со статусами -------------------------------------------------


def _run_action(client, queryset_ids, action: str):
    return client.post(
        "/admin/dictionary/sign/",
        {
            "action": action,
            "_selected_action": [str(pk) for pk in queryset_ids],
        },
        follow=True,
    )


def test_admin_submits_draft_for_review(client, admin_user, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)
    client.force_login(admin_user)

    response = _run_action(client, [sign.pk], "submit_for_review_action")

    assert response.status_code == 200
    sign.refresh_from_db()
    assert sign.status == SignStatus.REVIEW


def test_admin_action_verifies_review_sign(client, admin_user, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW, recorded_by=editor)
    client.force_login(admin_user)

    _run_action(client, [sign.pk], "verify_action")

    sign.refresh_from_db()
    assert sign.status == SignStatus.VERIFIED
    assert DictionaryVersion.current(Language.RSL).number == 1


def test_admin_action_rejects_review_sign(client, admin_user, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW, recorded_by=editor)
    client.force_login(admin_user)

    _run_action(client, [sign.pk], "reject_action")

    sign.refresh_from_db()
    assert sign.status == SignStatus.REJECTED


def test_admin_action_skips_forbidden_transition(client, admin_user, editor):
    """Утвердить черновик нельзя: действие пропускает жест и не падает."""
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.DRAFT, recorded_by=editor)
    client.force_login(admin_user)

    response = _run_action(client, [sign.pk], "verify_action")

    assert response.status_code == 200
    sign.refresh_from_db()
    assert sign.status == SignStatus.DRAFT
    assert DictionaryVersion.objects.count() == 0


# --- Версии словаря в админке ----------------------------------------------


def test_dictionary_version_is_read_only(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/dictionary/dictionaryversion/add/")

    assert response.status_code == 403


def test_dictionary_version_changelist_marks_current(client, admin_user):
    DictionaryVersion.objects.create(lang=Language.RSL, number=1)
    DictionaryVersion.objects.create(lang=Language.RSL, number=2)
    client.force_login(admin_user)

    response = client.get("/admin/dictionary/dictionaryversion/")

    assert response.status_code == 200
