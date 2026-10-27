"""Проверка сборки клиента: манифест Vite и теги ассетов."""

from pathlib import Path

import pytest
from django.conf import settings
from django_vite.core.asset_loader import DjangoViteAppClient, DjangoViteConfig

MANIFEST_PATH = Path(settings.BASE_DIR) / "static" / "dist" / "manifest.json"

pytestmark = pytest.mark.skipif(
    not MANIFEST_PATH.exists(),
    reason="нет static/dist/manifest.json — выполните npm run build",
)


def test_manifest_contains_main_entry():
    config = DjangoViteConfig(
        dev_mode=False,
        static_url_prefix="dist",
        manifest_path=MANIFEST_PATH,
    )
    client = DjangoViteAppClient(config)

    entry = client.manifest.get("frontend/main.ts")

    assert entry.isEntry is True
    assert entry.file.startswith("assets/main-")
    assert entry.file.endswith(".js")


def test_built_tags_point_to_static_dist():
    config = DjangoViteConfig(
        dev_mode=False,
        static_url_prefix="dist",
        manifest_path=MANIFEST_PATH,
    )
    html = DjangoViteAppClient(config).generate_vite_asset("frontend/main.ts")

    assert 'type="module"' in html
    assert f"{settings.STATIC_URL}dist/assets/main-" in html


def test_manifest_contains_avatar_page_entry():
    """C1: точка входа тестовой страницы аватара попадает в сборку."""
    config = DjangoViteConfig(
        dev_mode=False,
        static_url_prefix="dist",
        manifest_path=MANIFEST_PATH,
    )
    entry = DjangoViteAppClient(config).manifest.get("frontend/avatar-page.ts")

    assert entry is not None
    assert entry.isEntry is True
    assert entry.file.startswith("assets/avatar-page-")
    assert entry.file.endswith(".js")
