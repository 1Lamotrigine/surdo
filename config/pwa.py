"""PWA (этап G1): манифест, service worker и точка входа версии словаря.

Манифест и service worker должны отдаваться **с корня сайта**: только тогда
service worker получает область видимости ``/`` и управляет страницами комнаты
(``/r/<code>/`` и ``/rooms/<code>/``). Поэтому Django отдаёт их отдельными
представлениями, а не статикой из ``/static/``.

Версия кэша собирается из версии словаря (`DictionaryVersion`) и хэша сборки
клиента (имён файлов в манифесте Vite). Новая версия словаря или новая сборка
меняют имя кэша — старые клипы и статика вытесняются (FR-24).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.templatetags.static import static

from dictionary.models import DictionaryVersion, Language

# Имя кэша SW и корневая область — клиент регистрирует SW по этому пути.
SW_FILENAME = "sw.js"
MANIFEST_FILENAME = "manifest.webmanifest"

# Цвета манифеста совпадают с оформлением сайта (`static/css/base.css`).
THEME_COLOR = "#1f2937"
BACKGROUND_COLOR = "#0f172a"

# Иконки PWA лежат в статике. Размеры — минимальный набор Chrome/Safari;
# maskable нужен, чтобы иконка не обрезалась «плиткой» на Android.
ICONS = (
    {"src": "img/pwa/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "img/pwa/icon-512.png", "sizes": "512x512", "type": "image/png"},
    {
        "src": "img/pwa/maskable-512.png",
        "sizes": "512x512",
        "type": "image/png",
        "purpose": "maskable",
    },
)


def _static_url(path: str) -> str:
    """Публичный URL статики иконок: учитывает хэш `ManifestStaticFilesStorage`.

    Иконки кладутся в статику, поэтому в проде `static()` добавит хэш сборки —
    именно такой URL должен попасть в манифест, иначе после `collectstatic`
    ссылка на иконку «сломается».
    """
    return static(path)


def _icons() -> list[dict[str, str]]:
    return [{**icon, "src": _static_url(icon["src"])} for icon in ICONS]


def dictionary_cache_version() -> str:
    """Версия кэша словаря: номера версий обоих языков.

    ``DictionaryVersion`` растёт при каждом утверждении жеста (B4), поэтому её
    номера достаточно, чтобы сбросить кэш клипов при обновлении словаря.
    """
    parts: list[str] = []
    for lang in Language.values:
        version = DictionaryVersion.current(lang)
        parts.append(f"{lang}.{version.number if version else 0}")
    return "_".join(parts)


def _build_fingerprint() -> str:
    """Короткий хэш имён файлов сборки Vite — сбрасывает кэш статики.

    Читаем `static/dist/manifest.json`. Если файла нет (не выполнялась сборка,
    например в части тестов) — возвращаем ``no-build``: кэш всё равно
    пересоберётся, когда появится манифест.
    """
    manifest_path: Path = settings.DJANGO_VITE["default"]["manifest_path"]
    try:
        raw = manifest_path.read_bytes()
    except OSError:
        return "no-build"
    names = []
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError:
        return hashlib.sha256(raw).hexdigest()[:12]
    if isinstance(manifest, dict):
        names = sorted(
            str(entry.get("file", "")) for entry in manifest.values() if isinstance(entry, dict)
        )
    if not names:
        return hashlib.sha256(raw).hexdigest()[:12]
    return hashlib.sha256("|".join(names).encode("utf-8")).hexdigest()[:12]


def cache_version() -> str:
    """Полная версия кэша PWA: словарь + сборка клиента.

    Только буквы, цифры, точки и подчёркивания: строка вшивается в JS-шаблон
    через `escapejs`, и такой алфавит не превращается в `\\uXXXX`-последовательности
    (важно для читаемого кода service worker'а).
    """
    return f"d{dictionary_cache_version()}_b{_build_fingerprint()}"


def manifest(request: HttpRequest) -> JsonResponse:
    """Веб-манифест (FR-23): имя, иконки, режим standalone, область видимости."""
    payload = {
        "id": "/",
        "name": "ИИ-аватар сурдопереводчик",
        "short_name": "Жест·Прототип",
        "description": (
            "Прототип помощника-сурдопереводчика: аватар, субтитры и чат "
            "для лекций на русском и РЖЯ."
        ),
        "lang": "ru",
        "dir": "ltr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "theme_color": THEME_COLOR,
        "background_color": BACKGROUND_COLOR,
        "icons": _icons(),
    }
    response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False})
    response["Content-Type"] = "application/manifest+json"
    # Манифест меняется только со сборкой/словарём — короткий кэш допустим.
    response["Cache-Control"] = "public, max-age=3600"
    return response


def service_worker(request: HttpRequest) -> HttpResponse:
    """Service worker (FR-24) с версией кэша, вшитой при отдаче.

    Сам скрипт лежит шаблоном `templates/pwa/sw.js` (он не проходит через Vite:
    SW регистрируется напрямую). Django подставляет версию словаря и список
    статических ресурсов оболочки, поэтому новая версия словаря автоматически
    удаляет устаревшие клипы.
    """
    body = render_to_string(
        f"pwa/{SW_FILENAME}",
        {
            "cache_version": cache_version(),
            "shell_assets": _shell_assets(),
            "manifest_name": MANIFEST_FILENAME,
        },
    )
    response = HttpResponse(body, content_type="application/javascript")
    # SW должен проверяться при каждом входе: браузер не должен держать старую
    # копию (по умолчанию байты SW кэшируются максимум 24 ч, но запрос всё же
    # нужно разрешить — no-cache, а не no-store, чтобы работал 304).
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response


def _shell_assets() -> list[str]:
    """URL статических файлов «оболочки»: CSS и собранный JS-вход.

    Список нужен SW, чтобы закэшировать минимальный каркас приложения. Точные
    имена файлов берём из манифеста Vite; если его нет — пропускаем, тогда SW
    закэширует статику по запросу (cache-first по пути `/static/`).
    """
    assets = [static("css/base.css")]
    manifest_path: Path = settings.DJANGO_VITE["default"]["manifest_path"]
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (OSError, json.JSONDecodeError):
        return assets
    entry = manifest.get("frontend/main.ts") if isinstance(manifest, dict) else None
    if isinstance(entry, dict) and entry.get("file"):
        assets.append(f"{settings.STATIC_URL}dist/{entry['file']}")
    return assets
