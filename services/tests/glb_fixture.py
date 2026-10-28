"""Минимальный GLB-контейнер для тестов анимационных клипов (H1).

Собирает валидный бинарный glTF из одного JSON-чанка. Бинарный (BIN) чанк не
нужен: сервер читает только JSON (имена анимаций, наличие записей и длительность
по ``max`` входных аксессоров), а геометрию проверяет браузер.
"""

from __future__ import annotations

import json
import struct

GLB_MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A


def glb_bytes(payload: dict) -> bytes:
    """Упаковать JSON-объект в GLB-контейнер (заголовок + JSON-чанк)."""
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    # Длина чанка должна быть кратна 4; добиваем пробелами (валидно для JSON).
    padding = (-len(raw)) % 4
    raw += b" " * padding
    chunk = struct.pack("<II", len(raw), JSON_CHUNK) + raw
    total = 12 + len(chunk)
    return GLB_MAGIC + struct.pack("<II", 2, total) + chunk


def animation_payload(
    *,
    duration_s: float = 1.5,
    vrma: bool = False,
    animations: int = 1,
    names: list[str] | None = None,
    durations: list[float] | None = None,
) -> dict:
    """JSON-содержимое GLB с анимациями.

    ``names``/``durations`` задают несколько записей с разными именами и
    длительностью; ``animations`` — число записей с именами ``gesture_<i>``.
    """
    if names is None:
        names = [f"gesture_{index}" for index in range(animations)]
    if durations is None:
        durations = [duration_s] * len(names)
    if len(durations) != len(names):
        raise ValueError("durations и names должны быть одной длины")

    payload: dict = {
        "asset": {"version": "2.0"},
        "accessors": [
            {
                "componentType": 5126,
                "count": 2,
                "type": "SCALAR",
                "max": [duration],
                "min": [0.0],
            }
            for duration in durations
        ],
        "buffers": [{"byteLength": 8 * max(1, len(names))}],
    }
    if names:
        payload["animations"] = [
            {
                "name": name,
                "samplers": [{"input": index, "output": 0, "interpolation": "LINEAR"}],
                "channels": [],
            }
            for index, name in enumerate(names)
        ]
    if vrma:
        payload["extensionsUsed"] = ["VRMC_vrm_animation"]
    return payload


def make_glb(**kwargs) -> bytes:
    """Готовый GLB-файл анимации (по умолчанию — 1.5 с, один жест)."""
    return glb_bytes(animation_payload(**kwargs))
