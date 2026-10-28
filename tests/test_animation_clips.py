"""Анимационные клипы (H1): GLB/VRMA вместо landmarks.

Сервер не проигрывает анимации, но обязан проверить контейнер, сохранить
метаданные, отдать правильный тип и ссылку, а также предпочесть анимацию
landmarks при показе фразы. Проигрывание проверяется в vitest.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import Role
from dictionary.models import ClipFormat, Language, Sign, SignClip, SignStatus
from dictionary.services import SignValidationError, create_sign
from pipeline.events import clip_refs_for_glosses
from services.clips import ClipFormatError, parse_animation
from services.tests.glb_fixture import animation_payload, glb_bytes, make_glb

pytestmark = pytest.mark.django_db


@pytest.fixture
def editor(django_user_model):
    return django_user_model.objects.create_user(
        email="editor@example.com",
        password="StrongPass-12345",
        name="Редактор",
        role=Role.EDITOR,
    )


# --- Разбор контейнера -----------------------------------------------------


def test_parse_animation_reads_glb_and_duration():
    meta = parse_animation(make_glb(duration_s=1.5), filename="gesture.glb")

    assert meta.format == "animation"
    assert meta.extension == "glb"
    assert meta.vrma is False
    assert meta.animations == 1
    assert meta.duration_ms == 1500


def test_parse_animation_detects_vrma_by_extension_marker():
    meta = parse_animation(make_glb(vrma=True), filename="gesture.glb")

    assert meta.vrma is True


def test_parse_animation_detects_vrma_by_filename():
    meta = parse_animation(make_glb(), filename="gesture.vrma")

    assert meta.vrma is True
    assert meta.extension == "vrma"


def test_parse_animation_default_extension_without_filename():
    assert parse_animation(make_glb()).extension == "glb"
    assert parse_animation(make_glb(vrma=True)).extension == "vrma"


@pytest.mark.parametrize(
    "blob, message",
    [
        (b"", "Пустой файл"),
        (b"not-a-glb", "короче заголовка"),
        (b"glTF" + (2).to_bytes(4, "little") + (999).to_bytes(4, "little"), "не совпадает"),
    ],
)
def test_parse_animation_rejects_broken_files(blob, message):
    with pytest.raises(ClipFormatError, match=message):
        parse_animation(blob, filename="gesture.glb")


def test_parse_animation_rejects_foreign_signature():
    blob = bytearray(make_glb())
    blob[0:4] = b"NOPE"

    with pytest.raises(ClipFormatError, match="сигнатуры"):
        parse_animation(bytes(blob), filename="gesture.glb")


def test_parse_animation_rejects_unsupported_glb_version():
    blob = bytearray(make_glb())
    blob[4:8] = (1).to_bytes(4, "little")

    with pytest.raises(ClipFormatError, match="Версия GLB"):
        parse_animation(bytes(blob), filename="gesture.glb")


def test_parse_animation_rejects_file_without_animations():
    with pytest.raises(ClipFormatError, match="нет ни одной анимации"):
        parse_animation(make_glb(animations=0), filename="gesture.glb")


def test_parse_animation_rejects_unknown_extension():
    with pytest.raises(ClipFormatError, match="Расширение"):
        parse_animation(make_glb(), filename="gesture.fbx")


def test_parse_animation_respects_size_limit():
    with pytest.raises(ClipFormatError, match="больше лимита"):
        parse_animation(make_glb(), filename="gesture.glb", max_bytes=10)


def test_parse_animation_requires_json_first_chunk():
    payload = animation_payload()
    json_chunk = glb_bytes(payload)
    # Собираем GLB, где первый чанк помечен как BIN, а не JSON.
    body = bytearray(json_chunk)
    body[16:20] = (0x004E4942).to_bytes(4, "little")

    with pytest.raises(ClipFormatError, match="должен быть JSON"):
        parse_animation(bytes(body), filename="gesture.glb")


# --- Сервис создания жеста ------------------------------------------------


def test_create_sign_attaches_animation_clip(settings, tmp_path, editor):
    settings.MEDIA_ROOT = tmp_path

    sign = create_sign(
        recorded_by=editor,
        gloss="УЧЕБНИК",
        animation=make_glb(duration_s=2.0, vrma=True),
        animation_name="tutorial.vrma",
    )

    clip = sign.clips.get()
    assert clip.format == ClipFormat.ANIMATION
    assert clip.is_animation is True
    assert clip.frames == 0
    assert clip.duration_ms == 2000
    assert clip.storage_path.endswith(".vrma")
    assert clip.file_ext == "vrma"
    assert (tmp_path / clip.storage_path).exists()


def test_create_sign_rejects_both_clip_and_animation(editor):
    with pytest.raises(SignValidationError, match="либо клип"):
        create_sign(
            recorded_by=editor,
            gloss="УЧЕБНИК",
            clip=b"x",
            animation=make_glb(),
            animation_name="g.glb",
        )


def test_create_sign_rejects_broken_animation(editor):
    with pytest.raises(SignValidationError, match="GLB"):
        create_sign(
            recorded_by=editor,
            gloss="УЧЕБНИК",
            animation=b"not-glb",
            animation_name="g.glb",
        )


# --- HTTP API --------------------------------------------------------------


def _animation_upload(**kwargs) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        kwargs.pop("name", "gesture.vrma"),
        make_glb(**kwargs),
        content_type="model/gltf-binary",
    )


def test_api_accepts_animation_upload(client, editor, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(editor)

    response = client.post(
        reverse("api-sign-create"),
        {"gloss": "УЧЕБНИК", "lang": "rsl", "animation": _animation_upload()},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["clips"][0]["format"] == "animation"
    assert payload["clips"][0]["url"].endswith(".vrma")


def test_api_rejects_both_files(client, editor):
    client.force_login(editor)

    response = client.post(
        reverse("api-sign-create"),
        {
            "gloss": "УЧЕБНИК",
            "clip": SimpleUploadedFile("c.json.gz", b"x", content_type="application/gzip"),
            "animation": _animation_upload(),
        },
    )

    assert response.status_code == 400
    assert "либо клип" in response.json()["detail"]


def test_api_rejects_oversized_animation(client, editor, settings):
    settings.CLIP_MAX_ANIMATION_BYTES = 10
    client.force_login(editor)

    response = client.post(
        reverse("api-sign-create"),
        {"gloss": "УЧЕБНИК", "animation": _animation_upload()},
    )

    assert response.status_code == 413


# --- Отдача файла и ссылки -------------------------------------------------


def test_animation_is_served_as_gltf_binary(client, settings, tmp_path, editor):
    settings.MEDIA_ROOT = tmp_path
    sign = create_sign(
        recorded_by=editor,
        gloss="УЧЕБНИК",
        animation=make_glb(),
        animation_name="g.vrma",
    )
    clip = sign.clips.get()

    response = client.get(reverse("clip-file-animation", args=[clip.pk, "vrma"]))

    assert response.status_code == 200
    assert response["Content-Type"] == "model/gltf-binary"
    assert response["Cache-Control"] == "public, max-age=604800, immutable"


def test_animation_url_uses_extension(settings, tmp_path, editor):
    settings.MEDIA_ROOT = tmp_path
    sign = create_sign(
        recorded_by=editor,
        gloss="УЧЕБНИК",
        animation=make_glb(),
        animation_name="g.glb",
    )
    clip = sign.clips.get()

    assert clip.file_url().endswith(".glb")


def test_landmark_url_is_unchanged(settings, tmp_path, editor):
    settings.MEDIA_ROOT = tmp_path
    sign = Sign.objects.create(gloss="УЧЕБНИК", recorded_by=editor)
    clip = SignClip.objects.create(sign=sign, file="clips/x.json.gz", frames=10)

    assert clip.file_url().endswith(".json.gz")


# --- События конвейера -----------------------------------------------------


def test_events_include_clip_format():
    sign = Sign.objects.create(gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.VERIFIED)
    SignClip.objects.create(sign=sign, file="clips/x.vrma", format=ClipFormat.ANIMATION)

    refs = clip_refs_for_glosses(
        {
            "lang": "rsl",
            "text": "УЧЕБНИК",
            "tokens": [{"type": "sign", "gloss": "УЧЕБНИК"}],
        }
    )

    assert refs[0]["format"] == "animation"


def test_events_prefer_animation_over_landmarks():
    sign = Sign.objects.create(gloss="УЧЕБНИК", lang=Language.RSL, status=SignStatus.VERIFIED)
    SignClip.objects.create(
        sign=sign,
        file="clips/landmarks.json.gz",
        format=ClipFormat.LANDMARKS,
        frames=90,
        version=1,
    )
    animation = SignClip.objects.create(
        sign=sign,
        file="clips/gesture.vrma",
        format=ClipFormat.ANIMATION,
        frames=0,
        version=2,
    )

    refs = clip_refs_for_glosses(
        {
            "lang": "rsl",
            "text": "УЧЕБНИК",
            "tokens": [{"type": "sign", "gloss": "УЧЕБНИК"}],
        }
    )

    assert refs[0]["id"] == animation.pk
