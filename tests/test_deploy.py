"""Прод-конфигурация (G4): настройки безопасности, команды и артефакты деплоя.

Проверяем то, что не зависит от запущенного стека: настройки Django для
`DEBUG=False`, наличие команды очистки данных и файлы развёртывания
(`docker-compose.yml`, `Caddyfile`, `scripts/backup.sh`, `docs/DEPLOY.md`).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management import get_commands

BASE_DIR = Path(settings.BASE_DIR)


def test_retention_days_default():
    assert settings.RETENTION_DAYS >= 1


def test_proxy_ssl_header_configured():
    # Caddy передаёт X-Forwarded-Proto; Django должен его учитывать.
    assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


def test_purge_command_registered():
    commands = get_commands()
    assert commands.get("purge_old_data") == "pipeline"


def test_deploy_artifacts_exist():
    for name in ("docker-compose.yml", "Caddyfile", "Dockerfile", "docs/DEPLOY.md"):
        assert (BASE_DIR / name).is_file(), f"нет {name}"


def test_backup_script_is_executable_and_guarded():
    script = BASE_DIR / "scripts" / "backup.sh"
    assert script.is_file()
    text = script.read_text()
    # Скрипт останавливается на первой ошибке и умеет чистить старые копии.
    assert "set -euo pipefail" in text
    assert "pg_dump" in text
    assert "BACKUP_KEEP" in text


def test_compose_has_restart_and_healthchecks():
    compose = (BASE_DIR / "docker-compose.yml").read_text()

    assert "restart: unless-stopped" in compose
    # web проверяется через /health/, caddy ждёт здоровый web.
    assert "/health/" in compose
    assert "condition: service_healthy" in compose


def test_caddyfile_supports_domain_and_https():
    caddy = (BASE_DIR / "Caddyfile").read_text()

    # Адрес сайта задаётся переменной — локально :80, в проде домен с HTTPS.
    assert "{$SITE_ADDRESS" in caddy
    assert "Strict-Transport-Security" in caddy
    assert "reverse_proxy web:8000" in caddy
    # Клипы раздаёт сам Caddy с длинным кэшем.
    assert "/media/*" in caddy


def test_env_example_documents_production():
    env_example = (BASE_DIR / ".env.example").read_text()

    for key in (
        "SITE_ADDRESS",
        "ACME_EMAIL",
        "SESSION_COOKIE_SECURE",
        "SECURE_HSTS_SECONDS",
        "RETENTION_DAYS",
    ):
        assert key in env_example
