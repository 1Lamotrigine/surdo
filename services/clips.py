"""Хранилище клипов жестов за интерфейсом ``ClipStorage``.

Клип — файл ``.json.gz`` с landmarks (см. ``docs/spec/clip-format.md``).
Интерфейс отделяет код словаря от места хранения: сейчас это файловая система
внутри контейнера (Docker volume, раздаётся Caddy), позже — S3-совместимое
хранилище. Django не раздаёт файлы в проде, но отдаёт их в разработке и тестах
с кэш-заголовками (``ETag``), чтобы повторный запрос получал 304.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from django.conf import settings


class ClipStorage(Protocol):
    """Контракт хранилища клипов.

    Пути — относительные (например, ``clips/2026/10/uch.json.gz``); абсолютное
    расположение и URL задаёт реализация.
    """

    def save(self, name: str, data: bytes) -> str:
        """Сохранить клип и вернуть его относительный путь."""

    def exists(self, path: str) -> bool:
        """Есть ли файл по относительному пути."""

    def read(self, path: str) -> bytes:
        """Прочитать файл целиком."""

    def open(self, path: str):  # noqa: A003 — имя из контракта хранилища
        """Открыть файл для потоковой отдачи."""

    def delete(self, path: str) -> None:
        """Удалить файл, если он есть."""

    def size(self, path: str) -> int:
        """Размер файла в байтах."""

    def etag(self, path: str) -> str:
        """Стабильный ETag содержимого (для заголовка ``ETag`` и 304)."""

    def url(self, path: str) -> str:
        """Публичный URL файла."""


class FileClipStorage:
    """Файловая реализация ``ClipStorage`` поверх ``MEDIA_ROOT``."""

    def __init__(self, root: str | Path | None = None, url: str | None = None) -> None:
        self._root = Path(root) if root is not None else None
        self._base_url = url

    @property
    def root(self) -> Path:
        # Берём из настроек лениво, чтобы `override_settings(MEDIA_ROOT=...)`
        # в тестах действовал и на уже созданный экземпляр хранилища.
        return self._root if self._root is not None else Path(settings.MEDIA_ROOT)

    @property
    def base_url(self) -> str:
        return self._base_url if self._base_url is not None else settings.MEDIA_URL

    def _absolute(self, path: str) -> Path:
        return self.root / path

    def save(self, name: str, data: bytes) -> str:
        target = self._absolute(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return name

    def exists(self, path: str) -> bool:
        return self._absolute(path).is_file()

    def read(self, path: str) -> bytes:
        return self._absolute(path).read_bytes()

    def open(self, path: str):  # noqa: A003 — имя из контракта хранилища
        return self._absolute(path).open("rb")

    def delete(self, path: str) -> None:
        target = self._absolute(path)
        if target.exists():
            target.unlink()

    def size(self, path: str) -> int:
        return self._absolute(path).stat().st_size

    def etag(self, path: str) -> str:
        digest = hashlib.md5(self.read(path), usedforsecurity=False).hexdigest()
        return f'"{digest}"'

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"


default_storage = FileClipStorage()


class ClipFormatError(ValueError):
    """Файл клипа не соответствует формату ``docs/spec/clip-format.md``."""


@dataclass(frozen=True)
class ClipMeta:
    """Метаданные клипа, прочитанные из файла ``.json.gz``."""

    version: int
    gloss: str
    fps: int
    frames: int
    layout: dict
    data: str

    @property
    def duration_ms(self) -> int:
        """Длительность клипа в миллисекундах по числу кадров и fps."""
        if not self.fps:
            return 0
        return round(self.frames / self.fps * 1000)


def pack_clip(
    *,
    gloss: str,
    fps: int,
    frames: int,
    layout: dict,
    data: str,
    version: int | None = None,
) -> bytes:
    """Собрать файл клипа (``.json.gz``) из метаданных и данных.

    Данные (``data``) — уже готовая строка base64 от gzip-сжатых Float16
    landmarks; сервер их не переупаковывает (это делает инструмент записи).
    """
    payload = {
        "version": version if version is not None else settings.CLIP_VERSION,
        "gloss": gloss,
        "fps": fps,
        "frames": frames,
        "layout": layout,
        "data": data,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw)


def parse_clip(blob: bytes) -> ClipMeta:
    """Прочитать и проверить файл клипа ``.json.gz``.

    Проверяются: gzip, JSON-объект, версия формата, положительные ``fps`` и
    ``frames``, лимит кадров и наличие ``layout``/``data``.
    """
    try:
        raw = gzip.decompress(blob)
    except (OSError, EOFError) as exc:
        raise ClipFormatError("Файл клипа не является gzip.") from exc

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ClipFormatError("Внутри клипа не JSON.") from exc
    if not isinstance(payload, dict):
        raise ClipFormatError("Ожидался JSON-объект клипа.")

    version = payload.get("version")
    if version != settings.CLIP_VERSION:
        raise ClipFormatError(
            f"Версия формата клипа {version!r} не поддерживается "
            f"(ожидается {settings.CLIP_VERSION})."
        )

    fps = payload.get("fps")
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise ClipFormatError("Поле fps должно быть положительным целым числом.")

    frames = payload.get("frames")
    if not isinstance(frames, int) or isinstance(frames, bool) or frames <= 0:
        raise ClipFormatError("Поле frames должно быть положительным целым числом.")
    if frames > settings.CLIP_MAX_FRAMES:
        raise ClipFormatError(
            f"Клип длиннее лимита: {frames} кадров (максимум {settings.CLIP_MAX_FRAMES})."
        )

    layout = payload.get("layout")
    if not isinstance(layout, dict) or not layout:
        raise ClipFormatError("Поле layout должно быть непустым объектом.")

    data = payload.get("data")
    if not isinstance(data, str) or not data:
        raise ClipFormatError("Поле data должно быть непустой строкой base64.")

    gloss = payload.get("gloss") or ""
    if not isinstance(gloss, str):
        raise ClipFormatError("Поле gloss должно быть строкой.")

    return ClipMeta(
        version=version,
        gloss=gloss,
        fps=fps,
        frames=frames,
        layout=layout,
        data=data,
    )
