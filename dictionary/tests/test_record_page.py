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
    assert "record-page" in html


@override_settings(MEDIAPIPE_HOLISTIC_MODEL_URL="https://example.test/holistic.task")
def test_record_page_passes_model_url(client, editor):
    client.force_login(editor)

    response = client.get(reverse("dictionary:record"))
    html = response.content.decode()

    assert 'data-mediapipe-model-url="https://example.test/holistic.task"' in html
    assert "Не задан URL модели Holistic" not in html


@override_settings(MEDIAPIPE_HOLISTIC_MODEL_URL="")
def test_record_page_without_model_shows_hint(client, editor):
    client.force_login(editor)

    response = client.get(reverse("dictionary:record"))
    html = response.content.decode()

    assert 'data-mediapipe-model-url=""' in html
    assert "Не задан URL модели Holistic" in html


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
