"""Минимальный GLB-контейнер для тестов анимационных клипов (H1).

Собирает валидный бинарный glTF из одного JSON-чанка. Бинарный (BIN) чанк не
нужен: сервер читает только JSON (наличие анимаций и длительность по ``max``
входного аксессора), а геометрию проверяет браузер.
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
) -> dict:
    """JSON-содержимое GLB с анимацией заданной длительности."""
    payload: dict = {
        "asset": {"version": "2.0"},
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 2, "type": "SCALAR"},
            {"bufferView": 1, "componentType": 5126, "count": 2, "type": "VEC3"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 8},
            {"buffer": 0, "byteOffset": 8, "byteLength": 24},
        ],
        "buffers": [{"byteLength": 32}],
        "animations": [
            {
                "name": f"gesture_{index}",
                "samplers": [{"input": 0, "output": 1, "interpolation": "LINEAR"}],
                "channels": [],
            }
            for index in range(animations)
        ],
    }
    if animations == 0:
        payload.pop("animations")
        payload["accessors"] = payload["accessors"][:1]
        payload["bufferViews"] = payload["bufferViews"][:1]
        payload["buffers"] = [{"byteLength": 8}]
    else:
        payload["accessors"][0]["max"] = [duration_s]
        payload["accessors"][0]["min"] = [0.0]
    if vrma:
        payload["extensionsUsed"] = ["VRMC_vrm_animation"]
    return payload


def make_glb(**kwargs) -> bytes:
    """Готовый GLB-файл анимации (по умолчанию — 1.5 с, обычный glTF)."""
    return glb_bytes(animation_payload(**kwargs))
