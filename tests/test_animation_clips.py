"""Анимационные клипы (H1): GLB/VRMA вместо landmarks.

Сервер не проигрывает анимации, но обязан проверить контейнер, сохранить
метаданные, отдать правильный тип и ссылку, а также предпочесть анимацию
landmarks при показе фразы. Проигрывание проверяется в vitest.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
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


def test_parse_animation_reads_each_animation_name_and_duration():
    blob = make_glb(names=["uchebnik", "daktil_a"], durations=[1.5, 0.75])

    meta = parse_animation(blob, filename="gestures.glb")

    assert meta.animations == 2
    assert meta.names == ("uchebnik", "daktil_a")
    assert meta.durations_ms == (1500, 750)
    assert meta.duration_for("daktil_a") == 750
    assert meta.duration_for("") == 1500
    assert meta.duration_for("нет-такой") == meta.duration_ms == 1500


def test_parse_animation_keeps_unnamed_animation_empty():
    meta = parse_animation(make_glb(names=[""]), filename="g.glb")

    assert meta.names == ("",)


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


def test_create_sign_selects_animation_from_multi_file(settings, tmp_path, editor):
    settings.MEDIA_ROOT = tmp_path

    sign = create_sign(
        recorded_by=editor,
        gloss="ДАКТИЛЬ_А",
        animation=make_glb(names=["uchebnik", "daktil_a"], durations=[1.5, 0.75]),
        animation_name="gestures.glb",
        animation_clip="daktil_a",
    )

    clip = sign.clips.get()
    assert clip.animation_name == "daktil_a"
    assert clip.duration_ms == 750
    assert clip.file_ext == "glb"


def test_create_sign_rejects_unknown_animation_name(editor):
    with pytest.raises(SignValidationError, match="нет анимации"):
        create_sign(
            recorded_by=editor,
            gloss="УЧЕБНИК",
            animation=make_glb(names=["uchebnik"]),
            animation_name="gestures.glb",
            animation_clip="daktil_a",
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


def test_api_selects_named_animation_from_multi_file(client, editor, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client.force_login(editor)
    upload = SimpleUploadedFile(
        "gestures.glb",
        make_glb(names=["uchebnik", "daktil_a"], durations=[1.5, 0.75]),
        content_type="model/gltf-binary",
    )

    response = client.post(
        reverse("api-sign-create"),
        {
            "gloss": "ДАКТИЛЬ_А",
            "lang": "rsl",
            "animation": upload,
            "animation_clip": "daktil_a",
        },
    )

    assert response.status_code == 201
    clip = response.json()["clips"][0]
    assert clip["animation_name"] == "daktil_a"
    assert clip["duration_ms"] == 750


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
    SignClip.objects.create(
        sign=sign,
        file="clips/x.vrma",
        format=ClipFormat.ANIMATION,
        animation_name="uchebnik",
    )

    refs = clip_refs_for_glosses(
        {
            "lang": "rsl",
            "text": "УЧЕБНИК",
            "tokens": [{"type": "sign", "gloss": "УЧЕБНИК"}],
        }
    )

    assert refs[0]["format"] == "animation"
    assert refs[0]["animation_name"] == "uchebnik"


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


# --- Импорт одного файла с несколькими жестами ----------------------------


def test_import_animations_stores_file_once_for_many_gestures(
    settings, tmp_path, editor
):
    settings.MEDIA_ROOT = tmp_path
    source = tmp_path / "gestures.glb"
    source.write_bytes(
        make_glb(names=["УЧЕБНИК", "ДАКТИЛЬ_А"], durations=[1.5, 0.75])
    )

    call_command(
        "import_animations",
        str(source),
        "--user",
        editor.email,
        stdout=StringIO(),
    )

    clips = list(SignClip.objects.filter(format=ClipFormat.ANIMATION))
    assert len(clips) == 2
    paths = {clip.file.name for clip in clips}
    assert len(paths) == 1
    stored = tmp_path / paths.pop()
    assert stored.is_file()

    by_gloss = {clip.sign.gloss: clip for clip in clips}
    assert by_gloss["УЧЕБНИК"].animation_name == "УЧЕБНИК"
    assert by_gloss["УЧЕБНИК"].duration_ms == 1500
    assert by_gloss["ДАКТИЛЬ_А"].duration_ms == 750
    assert by_gloss["УЧЕБНИК"].version == 1


def test_import_animations_is_idempotent(settings, tmp_path, editor):
    settings.MEDIA_ROOT = tmp_path
    source = tmp_path / "gestures.glb"
    source.write_bytes(make_glb(names=["УЧЕБНИК", "ДАКТИЛЬ_А"]))

    call_command("import_animations", str(source), stdout=StringIO())
    call_command("import_animations", str(source), stdout=StringIO())

    assert SignClip.objects.filter(format=ClipFormat.ANIMATION).count() == 2
    assert Sign.objects.count() == 2


def test_import_animations_supports_explicit_map(settings, tmp_path, editor):
    settings.MEDIA_ROOT = tmp_path
    source = tmp_path / "gestures.glb"
    source.write_bytes(make_glb(names=["anim_1", "anim_2"], durations=[1.0, 2.0]))

    call_command(
        "import_animations",
        str(source),
        "--map",
        "УЧЕБНИК=anim_2",
        stdout=StringIO(),
    )

    clip = SignClip.objects.get()
    assert clip.sign.gloss == "УЧЕБНИК"
    assert clip.animation_name == "anim_2"
    assert clip.duration_ms == 2000


def test_import_animations_dry_run_writes_nothing(settings, tmp_path, editor):
    settings.MEDIA_ROOT = tmp_path
    source = tmp_path / "gestures.glb"
    source.write_bytes(make_glb(names=["УЧЕБНИК"]))

    call_command(
        "import_animations",
        str(source),
        "--dry-run",
        stdout=StringIO(),
    )

    assert Sign.objects.count() == 0
    assert SignClip.objects.count() == 0
    assert list((tmp_path / "clips").rglob("*.glb")) == []
