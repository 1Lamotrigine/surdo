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


# --- Анимационные клипы (H1): VRMA/glTF вместо landmarks -------------------
#
# Второй формат клипа — готовая анимация, сделанная вручную (Blender и т. п.).
# Файл — бинарный glTF (GLB), в котором лежит одна или несколько анимаций.
# VRMA (``.vrma``) — частный случай GLB с расширением ``VRMC_vrm_animation``:
# та же структура контейнера, но дорожки адресуют гуманоидные кости VRM, а не
# узлы конкретной модели. Сервер формат не проигрывает — он только проверяет
# контейнер и сохраняет метаданные (см. ``docs/ANIMATIONS.md``).

GLB_MAGIC = b"glTF"
GLB_VERSION = 2
_GLB_HEADER_SIZE = 12
_GLB_CHUNK_HEADER_SIZE = 8
_GLB_JSON_CHUNK = 0x4E4F534A  # 'JSON'
VRMA_EXTENSION = "VRMC_vrm_animation"
ANIMATION_EXTENSIONS = (".vrma", ".glb")


@dataclass(frozen=True)
class AnimationMeta:
    """Метаданные анимационного клипа, прочитанные из GLB-контейнера.

    В одном GLB может лежать несколько анимаций-записей (H1): ``names`` и
    ``durations_ms`` идут в том же порядке, что и ``animations`` в JSON. Жест
    выбирает одну запись по имени (``SignClip.animation_name``), поэтому
    длительность берётся не общая, а для конкретной записи.
    """

    extension: str
    vrma: bool
    animations: int
    duration_ms: int
    size_bytes: int
    names: tuple[str, ...] = ()
    durations_ms: tuple[int, ...] = ()

    @property
    def format(self) -> str:
        return "animation"

    def duration_for(self, name: str = "") -> int:
        """Длительность записи по имени; без имени — первой в файле."""
        if not self.durations_ms:
            return self.duration_ms
        if name:
            try:
                return self.durations_ms[self.names.index(name)]
            except ValueError:
                return self.duration_ms
        return self.durations_ms[0]



def glb_json(blob: bytes) -> dict:
    """Достать JSON-чанк из GLB-контейнера (без разбора бинарных данных).

    Проверяет сигнатуру ``glTF``, версию 2 и целостность первого чанка. Этого
    достаточно, чтобы отсечь не-GLB файлы и битые загрузки; геометрию и
    анимации сервер не валидирует — это делает браузер при проигрывании.
    """
    if len(blob) < _GLB_HEADER_SIZE:
        raise ClipFormatError("Файл анимации короче заголовка GLB.")
    magic, version, length = (
        blob[0:4],
        int.from_bytes(blob[4:8], "little"),
        int.from_bytes(blob[8:12], "little"),
    )
    if magic != GLB_MAGIC:
        raise ClipFormatError("Файл анимации не является GLB (нет сигнатуры glTF).")
    if version != GLB_VERSION:
        raise ClipFormatError(f"Версия GLB {version} не поддерживается (ожидается 2).")
    if length != len(blob):
        raise ClipFormatError(
            f"Длина GLB в заголовке ({length}) не совпадает с размером файла ({len(blob)})."
        )

    offset = _GLB_HEADER_SIZE
    if offset + _GLB_CHUNK_HEADER_SIZE > len(blob):
        raise ClipFormatError("В GLB нет JSON-чанка.")
    chunk_length = int.from_bytes(blob[offset : offset + 4], "little")
    chunk_type = int.from_bytes(blob[offset + 4 : offset + 8], "little")
    if chunk_type != _GLB_JSON_CHUNK:
        raise ClipFormatError("Первый чанк GLB должен быть JSON.")
    start = offset + _GLB_CHUNK_HEADER_SIZE
    end = start + chunk_length
    if end > len(blob):
        raise ClipFormatError("JSON-чанк GLB выходит за границы файла.")
    try:
        payload = json.loads(blob[start:end].decode("utf-8").rstrip("\x00 "))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClipFormatError("JSON-чанк GLB не разбирается.") from exc
    if not isinstance(payload, dict):
        raise ClipFormatError("JSON-чанк GLB должен быть объектом.")
    return payload


def _animation_durations_ms(payload: dict) -> list[int]:
    """Длительность каждой анимации по ``max`` входных аксессоров, мс.

    В glTF у ``accessor`` для времени часто есть ``max``; если его нет,
    длительность записи неизвестна и остаётся 0 (клиент возьмёт её из файла).
    Порядок результата совпадает с порядком ``animations`` в JSON.
    """
    animations = payload.get("animations")
    if not isinstance(animations, list):
        return []
    accessors = payload.get("accessors")
    if not isinstance(accessors, list):
        return [0] * len(animations)

    durations: list[int] = []
    for animation in animations:
        longest = 0.0
        samplers = animation.get("samplers") if isinstance(animation, dict) else None
        if isinstance(samplers, list):
            for sampler in samplers:
                if not isinstance(sampler, dict):
                    continue
                index = sampler.get("input")
                if not isinstance(index, int) or not 0 <= index < len(accessors):
                    continue
                accessor = accessors[index]
                if not isinstance(accessor, dict):
                    continue
                maximum = accessor.get("max")
                if (
                    isinstance(maximum, list)
                    and maximum
                    and isinstance(maximum[0], (int, float))
                ):
                    longest = max(longest, float(maximum[0]))
        durations.append(round(longest * 1000))
    return durations


def _animation_names(payload: dict) -> tuple[str, ...]:
    """Имена анимаций в порядке JSON; безымянные записи — пустая строка."""
    animations = payload.get("animations")
    if not isinstance(animations, list):
        return ()
    names: list[str] = []
    for animation in animations:
        name = animation.get("name") if isinstance(animation, dict) else None
        names.append(name.strip() if isinstance(name, str) else "")
    return tuple(names)


def is_demo_animation(payload: dict) -> bool:
    """Распознать пакет заглушек по метке его генератора GLB."""
    asset = payload.get("asset")
    return isinstance(asset, dict) and asset.get("generator") == "make_gestures_vrma.py"


def parse_animation(
    blob: bytes,
    *,
    filename: str = "",
    max_bytes: int | None = None,
) -> AnimationMeta:
    """Проверить анимационный клип (GLB/VRMA) и вернуть метаданные.

    Проверяются: непустой файл, лимит размера, сигнатура и версия GLB, JSON-чанк
    и наличие хотя бы одной анимации. Расширение берётся из имени файла
    (``.vrma``/``.glb``); без имени — по расширению ``VRMC_vrm_animation``.
    """
    limit = settings.CLIP_MAX_ANIMATION_BYTES if max_bytes is None else max_bytes
    if not blob:
        raise ClipFormatError("Пустой файл анимации.")
    if len(blob) > limit:
        raise ClipFormatError(f"Анимация больше лимита: {len(blob)} байт (максимум {limit}).")

    suffix = Path(filename).suffix.lower() if filename else ""
    if suffix and suffix not in ANIMATION_EXTENSIONS:
        raise ClipFormatError(
            f"Расширение {suffix!r} не поддерживается: нужен .vrma или .glb."
        )

    payload = glb_json(blob)
    if is_demo_animation(payload):
        raise ClipFormatError("Пакет демонстрационных заглушек нельзя добавить в словарь.")
    extensions = payload.get("extensionsUsed")
    used = extensions if isinstance(extensions, list) else []
    vrma = VRMA_EXTENSION in used or suffix == ".vrma"

    animations = payload.get("animations")
    count = len(animations) if isinstance(animations, list) else 0
    if count == 0:
        raise ClipFormatError("В файле анимации нет ни одной анимации.")

    if not suffix:
        suffix = ".vrma" if vrma else ".glb"

    durations = _animation_durations_ms(payload)
    return AnimationMeta(
        extension=suffix.lstrip("."),
        vrma=vrma,
        animations=count,
        duration_ms=max(durations, default=0),
        size_bytes=len(blob),
        names=_animation_names(payload),
        durations_ms=tuple(durations),
    )


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
