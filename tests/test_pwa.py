"""PWA (G1): манифест, service worker, версия кэша и мета-теги страниц.

Манифест и service worker отдаются с корня сайта (иначе SW не получит область
видимости `/`). Версия кэша должна меняться вместе с версией словаря и сборкой
клиента (FR-24).
"""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse

from config import pwa
from dictionary.models import DictionaryVersion, Language

pytestmark = pytest.mark.django_db


def test_manifest_served_from_root():
    response = Client().get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/manifest+json"
    payload = json.loads(response.content)
    assert payload["start_url"] == "/"
    assert payload["scope"] == "/"
    assert payload["display"] == "standalone"
    assert payload["theme_color"] == pwa.THEME_COLOR


def test_manifest_lists_required_icons():
    payload = json.loads(Client().get("/manifest.webmanifest").content)
    icons = {(icon["sizes"], icon.get("purpose", "any")) for icon in payload["icons"]}

    assert ("192x192", "any") in icons
    assert ("512x512", "any") in icons
    assert ("512x512", "maskable") in icons
    for icon in payload["icons"]:
        assert icon["src"].startswith("/static/")
        assert icon["type"] == "image/png"


def test_service_worker_served_from_root_with_scope():
    response = Client().get("/sw.js")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/javascript"
    # Явная область видимости: регистрируем SW в корне, он должен управлять
    # страницами комнаты (/r/<code>/ и /rooms/<code>/).
    assert response["Service-Worker-Allowed"] == "/"
    assert response["Cache-Control"] == "no-cache"


def test_service_worker_embeds_cache_version_and_shell():
    body = Client().get("/sw.js").content.decode()

    assert pwa.cache_version() in body
    assert "SHELL_ASSETS" in body
    # Клипы кэшируются cache-first по неизменяемому пути.
    assert "media" in body and "clips" in body
    assert "clips:" in body


def test_cache_version_grows_with_dictionary():
    """Утверждение жеста растит версию словаря — и версию кэша PWA (FR-24)."""
    before = pwa.cache_version()
    DictionaryVersion.bump(Language.RSL)
    after = pwa.cache_version()

    assert before != after
    assert "rsl.1" in after


def test_cache_version_is_stable_without_changes():
    assert pwa.cache_version() == pwa.cache_version()


def test_home_page_links_manifest_and_icons():
    html = Client().get(reverse("home")).content.decode()

    assert 'rel="manifest"' in html
    assert 'href="/manifest.webmanifest"' in html
    assert 'name="theme-color"' in html
    assert "apple-touch-icon" in html
