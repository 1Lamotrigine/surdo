"""HTTP API словаря: публичный список и загрузка клипа редактором."""

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import Role
from dictionary.models import (
    DictionaryVersion,
    Language,
    Sign,
    SignClip,
    SignStatus,
)
from services.clips import pack_clip

pytestmark = pytest.mark.django_db

LAYOUT = {"pose": 33, "hand_l": 21, "hand_r": 21, "face": 468}


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


def _clip_file(**overrides) -> SimpleUploadedFile:
    payload = {
        "version": 1,
        "gloss": "УЧЕБНИК",
        "fps": 30,
        "frames": 54,
        "layout": LAYOUT,
        "data": "H4sIA",
    }
    payload.update(overrides)
    blob = pack_clip(
        gloss=payload["gloss"],
        fps=payload["fps"],
        frames=payload["frames"],
        layout=payload["layout"],
        data=payload["data"],
        version=payload["version"],
    )
    return SimpleUploadedFile("clip.json.gz", blob, content_type="application/gzip")


# --- GET /api/dictionary/ -------------------------------------------------


def test_dictionary_list_is_public(client, editor):
    Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.VERIFIED, recorded_by=editor)

    response = client.get(reverse("api-dictionary"))

    assert response.status_code == 200
    glosses = [s["gloss"] for s in response.json()["signs"]]
    assert glosses == ["УЧЕБНИК"]


def test_dictionary_sign_reports_allowed_transitions(client, editor):
    Sign.objects.create(gloss="ЧЕРНОВИК", status=SignStatus.DRAFT, recorded_by=editor)
    client.force_login(editor)

    response = client.get(reverse("api-dictionary"), {"status": SignStatus.DRAFT})

    sign = response.json()["signs"][0]
    assert sign["allowed_transitions"] == ["review"]
    assert sign["comment"] == ""


def test_dictionary_list_excludes_drafts_by_default(client, editor):
    Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.VERIFIED, recorded_by=editor)
    Sign.objects.create(gloss="ЧЕРНОВИК", status=SignStatus.DRAFT, recorded_by=editor)

    response = client.get(reverse("api-dictionary"))

    assert [s["gloss"] for s in response.json()["signs"]] == ["УЧЕБНИК"]


def test_dictionary_list_filters_by_language(client, editor):
    Sign.objects.create(gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.VERIFIED)
    Sign.objects.create(gloss="КІТАП", lang=Language.KSL, status=SignStatus.VERIFIED)

    response = client.get(reverse("api-dictionary"), {"lang": Language.KSL})

    assert [s["gloss"] for s in response.json()["signs"]] == ["КІТАП"]


def test_dictionary_list_reports_version(client, editor):
    DictionaryVersion.objects.create(lang=Language.RSL, number=3)
    Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.VERIFIED)

    response = client.get(reverse("api-dictionary"), {"lang": Language.RSL})

    assert response.json()["version"] == 3


def test_dictionary_version_is_null_without_versions(client):
    response = client.get(reverse("api-dictionary"), {"lang": Language.RSL})

    assert response.json()["version"] is None


def test_dictionary_list_rejects_unknown_language(client):
    response = client.get(reverse("api-dictionary"), {"lang": "xx"})

    assert response.status_code == 400


def test_drafts_require_dictionary_role(client, teacher):
    client.force_login(teacher)

    response = client.get(reverse("api-dictionary"), {"status": SignStatus.DRAFT})

    assert response.status_code == 403


def test_editor_sees_drafts(client, editor):
    Sign.objects.create(gloss="ЧЕРНОВИК", status=SignStatus.DRAFT, recorded_by=editor)
    client.force_login(editor)

    response = client.get(reverse("api-dictionary"), {"status": SignStatus.DRAFT})

    assert response.status_code == 200
    assert [s["gloss"] for s in response.json()["signs"]] == ["ЧЕРНОВИК"]


def test_dictionary_sign_includes_clip_url(client, editor, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.VERIFIED)
    clip = SignClip.objects.create(sign=sign, file="clips/a.json.gz", frames=54)

    response = client.get(reverse("api-dictionary"))

    clips = response.json()["signs"][0]["clips"]
    assert clips[0]["id"] == clip.pk
    assert clips[0]["url"].endswith(f"/media/clips/{clip.pk}.json.gz")


# --- POST /api/signs/ -----------------------------------------------------


def test_create_sign_requires_authentication(client):
    response = client.post(reverse("api-sign-create"), {"gloss": "УЧЕБНИК"})

    assert response.status_code == 401
    assert Sign.objects.count() == 0


def test_create_sign_rejects_teacher(client, teacher):
    client.force_login(teacher)

    response = client.post(reverse("api-sign-create"), {"gloss": "УЧЕБНИК"})

    assert response.status_code == 403
    assert Sign.objects.count() == 0


def test_create_sign_rejects_anonymous_draft_listing(client):
    response = client.get(reverse("api-dictionary"), {"status": SignStatus.REJECTED})

    assert response.status_code == 403


def test_editor_creates_sign_from_form(client, editor, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(editor)

    response = client.post(
        reverse("api-sign-create"),
        {"gloss": "УЧЕБНИК", "lang": Language.RSL, "description": "школьный"},
    )

    assert response.status_code == 201
    sign = Sign.objects.get()
    assert sign.gloss == "УЧЕБНИК"
    assert sign.status == SignStatus.DRAFT
    assert sign.recorded_by == editor
    assert response.json()["id"] == sign.pk


def test_editor_creates_sign_from_json(client, editor):
    client.force_login(editor)

    response = client.post(
        reverse("api-sign-create"),
        data=json.dumps({"gloss": "УЧЕБНИК", "lang": Language.RSL}),
        content_type="application/json",
    )

    assert response.status_code == 201
    assert Sign.objects.filter(gloss="УЧЕБНИК").exists()


def test_create_sign_with_uploaded_clip(client, editor, expert, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(editor)

    response = client.post(
        reverse("api-sign-create"),
        {"gloss": "УЧЕБНИК", "clip": _clip_file()},
    )

    assert response.status_code == 201
    clip = SignClip.objects.get()
    assert clip.frames == 54
    assert clip.fps == 30
    assert clip.size_bytes > 0
    # Файл реально сохранён в хранилище.
    assert (tmp_path / clip.file.name).is_file()


def test_create_sign_rejects_empty_gloss(client, editor):
    client.force_login(editor)

    response = client.post(reverse("api-sign-create"), {"gloss": "   "})

    assert response.status_code == 400
    assert Sign.objects.count() == 0


def test_create_sign_rejects_unknown_language(client, editor):
    client.force_login(editor)

    response = client.post(
        reverse("api-sign-create"), {"gloss": "УЧЕБНИК", "lang": "xx"}
    )

    assert response.status_code == 400


def test_create_sign_rejects_broken_clip(client, editor, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(editor)
    broken = SimpleUploadedFile("bad.json.gz", b"not gzip")

    response = client.post(
        reverse("api-sign-create"), {"gloss": "УЧЕБНИК", "clip": broken}
    )

    assert response.status_code == 400
    assert Sign.objects.count() == 0
    assert SignClip.objects.count() == 0


def test_create_sign_rejects_oversized_frame_count(client, editor, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.CLIP_MAX_FRAMES = 10
    client.force_login(editor)

    response = client.post(
        reverse("api-sign-create"),
        {"gloss": "УЧЕБНИК", "clip": _clip_file(frames=999)},
    )

    assert response.status_code == 400
    assert Sign.objects.count() == 0


def test_create_sign_rejects_oversized_file(client, editor, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.CLIP_MAX_SIZE_BYTES = 10
    client.force_login(editor)

    response = client.post(
        reverse("api-sign-create"),
        {"gloss": "УЧЕБНИК", "clip": _clip_file()},
    )

    assert response.status_code == 413
    assert Sign.objects.count() == 0


def test_created_draft_appears_in_admin(client, editor, admin_user):
    client.force_login(editor)
    created = client.post(
        reverse("api-sign-create"),
        data=json.dumps({"gloss": "УЧЕБНИК", "lang": Language.RSL}),
        content_type="application/json",
    )
    assert created.status_code == 201

    client.force_login(admin_user)
    response = client.get(reverse("admin:dictionary_sign_changelist"))

    assert response.status_code == 200
    assert "УЧЕБНИК" in response.content.decode()


def test_expert_can_create_sign(client, expert, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(expert)

    response = client.post(
        reverse("api-sign-create"),
        data=json.dumps({"gloss": "ЖЕСТ"}),
        content_type="application/json",
    )

    assert response.status_code == 201


def test_admin_can_create_sign(client, admin_user, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(admin_user)

    response = client.post(
        reverse("api-sign-create"),
        data=json.dumps({"gloss": "ЖЕСТ"}),
        content_type="application/json",
    )

    assert response.status_code == 201


# --- POST /api/signs/<id>/review/ -----------------------------------------


def _review_url(sign):
    return reverse("api-sign-review", kwargs={"sign_id": sign.pk})


def test_review_requires_authentication(client, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)

    response = client.post(
        _review_url(sign),
        data=json.dumps({"decision": "approve"}),
        content_type="application/json",
    )

    assert response.status_code == 401
    sign.refresh_from_db()
    assert sign.status == SignStatus.REVIEW


def test_review_rejects_editor(client, editor):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)
    client.force_login(editor)

    response = client.post(
        _review_url(sign),
        data=json.dumps({"decision": "approve"}),
        content_type="application/json",
    )

    assert response.status_code == 403
    sign.refresh_from_db()
    assert sign.status == SignStatus.REVIEW


def test_review_rejects_teacher(client, teacher):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)
    client.force_login(teacher)

    response = client.post(
        _review_url(sign),
        data=json.dumps({"decision": "approve"}),
        content_type="application/json",
    )

    assert response.status_code == 403


def test_expert_approves_sign(client, expert):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)
    client.force_login(expert)

    response = client.post(
        _review_url(sign),
        data=json.dumps({"decision": "approve", "comment": "Читается хорошо"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    sign.refresh_from_db()
    assert sign.status == SignStatus.VERIFIED
    assert sign.verified_by == expert
    assert sign.comment == "Читается хорошо"
    assert DictionaryVersion.current(Language.RSL).number == 1
    assert response.json()["status"] == SignStatus.VERIFIED


def test_expert_rejects_sign(client, expert):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)
    client.force_login(expert)

    response = client.post(
        _review_url(sign),
        data=json.dumps({"decision": "reject", "comment": "Слишком быстро"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    sign.refresh_from_db()
    assert sign.status == SignStatus.REJECTED
    assert sign.comment == "Слишком быстро"
    assert DictionaryVersion.objects.count() == 0


def test_review_accepts_form_encoded_body(client, expert):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)
    client.force_login(expert)

    response = client.post(_review_url(sign), {"decision": "approve", "comment": "ок"})

    assert response.status_code == 200
    sign.refresh_from_db()
    assert sign.status == SignStatus.VERIFIED


def test_review_rejects_unknown_decision(client, expert):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)
    client.force_login(expert)

    response = client.post(
        _review_url(sign),
        data=json.dumps({"decision": "maybe"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    sign.refresh_from_db()
    assert sign.status == SignStatus.REVIEW


def test_review_rejects_broken_json(client, expert):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)
    client.force_login(expert)

    response = client.post(
        _review_url(sign), data="{not json", content_type="application/json"
    )

    assert response.status_code == 400


def test_review_conflict_for_draft_sign(client, expert):
    """Утвердить черновик нельзя: фаза перехода не та — 409, статус не меняется."""
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.DRAFT)
    client.force_login(expert)

    response = client.post(
        _review_url(sign),
        data=json.dumps({"decision": "approve"}),
        content_type="application/json",
    )

    assert response.status_code == 409
    sign.refresh_from_db()
    assert sign.status == SignStatus.DRAFT


def test_review_unknown_sign_returns_404(client, expert):
    client.force_login(expert)

    response = client.post(
        reverse("api-sign-review", kwargs={"sign_id": 999999}),
        data=json.dumps({"decision": "approve"}),
        content_type="application/json",
    )

    assert response.status_code == 404


def test_admin_can_review(client, admin_user):
    sign = Sign.objects.create(gloss="УЧЕБНИК", status=SignStatus.REVIEW)
    client.force_login(admin_user)

    response = client.post(
        _review_url(sign),
        data=json.dumps({"decision": "approve"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    sign.refresh_from_db()
    assert sign.status == SignStatus.VERIFIED
