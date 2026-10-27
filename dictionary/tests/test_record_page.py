"""Инструмент записи жеста (D1): доступ и параметры страницы."""

from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

from accounts.models import Role

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
def teacher(django_user_model):
    return django_user_model.objects.create_user(
        email="teacher@example.com",
        password="StrongPass-12345",
        name="Преподаватель",
        role=Role.TEACHER,
    )


def test_record_page_requires_login(client):
    response = client.get(reverse("dictionary:record"))

    assert response.status_code == 302
    assert reverse("accounts:login") in response["Location"]


def test_record_page_denied_to_teacher(client, teacher):
    client.force_login(teacher)

    response = client.get(reverse("dictionary:record"))

    assert response.status_code == 403


def test_record_page_renders_camera_and_skeleton(client, editor):
    client.force_login(editor)

    response = client.get(reverse("dictionary:record"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Запись жеста с камеры" in html
    # Контейнер камеры, видео и холст поверх него.
    assert "data-record-page" in html
    assert "data-record-video" in html
    assert "data-record-canvas" in html
    assert "data-record-start" in html
    assert "data-record-stop" in html
    assert "data-record-status" in html
    # Показатели распознавания и точка входа клиента.
    assert "data-record-stats" in html
    assert "data-record-hands" in html
    # D2: запись клипа, обрезка, проверка распаковкой и скачивание.
    assert "data-record-start-clip" in html
    assert "data-record-stop-clip" in html
    assert "data-record-clip-status" in html
    assert "data-record-trim" in html
    assert "data-record-trim-start" in html
    assert "data-record-trim-end" in html
    assert "data-record-build-status" in html
    assert "data-record-download" in html
    # D3: аватар, метаданные и сохранение черновика через API.
    assert "data-record-preview" in html
    assert "data-record-preview-stage" in html
    assert "data-record-preview-play" in html
    assert "data-record-preview-stop" in html
    assert "data-sign-form" in html
    assert 'data-sign-api-url="/api/signs/"' in html
    assert "data-sign-gloss" in html
    assert "data-sign-lang" in html
    assert "data-sign-description" in html
    assert "data-sign-save" in html
    assert "data-sign-status" in html
    assert "csrfmiddlewaretoken" in html
    assert '<option value="rsl">Русский жестовый</option>' in html
    assert '<option value="ksl">Казахский жестовый</option>' in html
    assert "record-page" in html


@override_settings(MEDIAPIPE_HOLISTIC_MODEL_URL="https://example.test/holistic.task")
def test_record_page_passes_model_url(client, editor):
    client.force_login(editor)

    response = client.get(reverse("dictionary:record"))
    html = response.content.decode()

    assert 'data-mediapipe-model-url="https://example.test/holistic.task"' in html
    assert "Не задан URL модели Holistic" not in html


@override_settings(AVATAR_MODEL_URL="https://example.test/avatar.vrm")
def test_record_page_passes_avatar_model_url(client, editor):
    client.force_login(editor)

    response = client.get(reverse("dictionary:record"))
    html = response.content.decode()

    assert 'data-avatar-model-url="https://example.test/avatar.vrm"' in html
    assert "Модель аватара не задана" not in html


@override_settings(MEDIAPIPE_HOLISTIC_MODEL_URL="")
def test_record_page_without_model_shows_hint(client, editor):
    client.force_login(editor)

    response = client.get(reverse("dictionary:record"))
    html = response.content.decode()

    assert 'data-mediapipe-model-url=""' in html
    assert "Не задан URL модели Holistic" in html


@override_settings(AVATAR_MODEL_URL="")
def test_record_page_without_avatar_model_still_allows_save(client, editor):
    client.force_login(editor)

    response = client.get(reverse("dictionary:record"))
    html = response.content.decode()

    assert 'data-avatar-model-url=""' in html
    assert "Модель аватара не задана" in html
    assert "data-sign-save" in html


def test_record_page_uses_built_wasm(client, editor):
    client.force_login(editor)
    prod_config = {
        "default": {
            "dev_mode": False,
            "static_url_prefix": "dist",
            "manifest_path": "",
        }
    }

    with override_settings(DJANGO_VITE=prod_config):
        response = client.get(reverse("dictionary:record"))

    assert 'data-mediapipe-wasm="/static/dist/mediapipe"' in response.content.decode()


def test_record_page_uses_vite_wasm_in_dev(client, editor):
    client.force_login(editor)
    dev_config = {
        "default": {
            "dev_mode": True,
            "dev_server_host": "vite.test",
            "dev_server_port": 5173,
            "static_url_prefix": "dist",
        }
    }

    with override_settings(DJANGO_VITE=dev_config):
        response = client.get(reverse("dictionary:record"))

    assert (
        'data-mediapipe-wasm="http://vite.test:5173/static/dist/mediapipe"'
        in response.content.decode()
    )


def test_unknown_queue_links_to_record_tool(client, editor):
    client.force_login(editor)

    response = client.get(reverse("dictionary:unknown-queue"))
    html = response.content.decode()

    assert reverse("dictionary:record") in html
    assert "Записать жест с камеры" in html


@override_settings(CLIP_DEFAULT_FPS=25, CLIP_MAX_FRAMES=100, CLIP_MAX_SIZE_BYTES=1234)
def test_record_page_passes_clip_limits(client, editor):
    client.force_login(editor)

    response = client.get(reverse("dictionary:record"))
    html = response.content.decode()

    assert 'data-record-fps="25"' in html
    assert 'data-record-max-frames="100"' in html
    assert 'data-record-max-bytes="1234"' in html
    assert "4,0" in html
    assert "(100 кадров при 25 FPS)" in html
