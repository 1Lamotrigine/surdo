"""Тестовая страница аватара (C1): сцена рендерится, модуль подключается."""

from __future__ import annotations

from django.test import override_settings
from django.urls import reverse


def test_avatar_page_renders(client):
    response = client.get(reverse("avatar-test"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "text/html" in response["Content-Type"]
    assert "Аватар в браузере" in html
    # Контейнер сцены и атрибуты для модуля avatar-page.ts.
    assert "data-avatar-page" in html
    assert "data-avatar-stage" in html
    assert "data-avatar-status" in html
    # C3: управление проигрыванием клипа.
    assert "data-avatar-demo" in html
    assert "data-avatar-play" in html
    assert "data-avatar-stop" in html
    assert "data-avatar-file" in html
    # C4: очередь клипов, блендинг, скорость и пауза между фразами.
    assert "data-avatar-queue" in html
    assert "data-avatar-speed" in html
    assert "data-avatar-gap" in html
    # C5: дактиль — ввод слова и показ по буквам.
    assert "data-avatar-dactyl" in html
    assert "data-avatar-dactyl-text" in html
    # C6: субтитры — фраза и контейнер подсветки слова.
    assert "data-avatar-phrase" in html
    assert "data-avatar-subtitles" in html
    assert "subtitle-size-large" in html
    # C7: настройки студента — скорость, размер, положение и фон.
    assert "data-avatar-settings" in html
    assert "data-settings-speed" in html
    assert "data-settings-size" in html
    assert "data-settings-offset-x" in html
    assert "data-settings-offset-y" in html
    assert "data-settings-theme" in html
    assert "data-settings-reset" in html
    # Точка входа клиента (собранный ассет или dev-сервер Vite).
    assert "avatar-page" in html


def test_avatar_page_is_public(client):
    """Тестовая страница C1 доступна без входа."""
    response = client.get(reverse("avatar-test"))

    assert response.status_code == 200


@override_settings(AVATAR_MODEL_URL="https://example.test/avatar.vrm")
def test_avatar_page_passes_model_url(client):
    response = client.get(reverse("avatar-test"))
    html = response.content.decode()

    assert 'data-avatar-model-url="https://example.test/avatar.vrm"' in html
    assert "Модель не задана" not in html


@override_settings(AVATAR_MODEL_URL="")
def test_avatar_page_without_model_shows_hint(client):
    response = client.get(reverse("avatar-test"))
    html = response.content.decode()

    assert 'data-avatar-model-url=""' in html
    assert "Модель не задана" in html
