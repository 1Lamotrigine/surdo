"""Сгенерировать иконки PWA (G1) без внешних зависимостей.

Картинки рисуются вручную (RGBA → PNG через `zlib`): добавлять Pillow ради
трёх иконок не стоит, а сами иконки — простой знак «рука/жест» на градиенте.
Скрипт одноразовый, но лежит в репозитории, чтобы иконки можно было
пересобрать: `python scripts/make_pwa_icons.py`.

Запуск не требует Django: чистые stdlib + struct + zlib.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "static" / "img" / "pwa"

# Цвета совпадают с темой сайта (config.pwa.THEME_COLOR / BACKGROUND_COLOR).
BG_TOP = (31, 41, 55)  # #1f2937
BG_BOTTOM = (15, 23, 42)  # #0f172a
HAND = (241, 245, 249)  # #f1f5f9
HAND_EDGE = (148, 163, 184)  # #94a3b8
ACCENT = (56, 189, 248)  # #38bdf8


def _lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def _bg(x: int, y: int, size: int) -> tuple[int, int, int]:
    t = y / max(1, size - 1)
    return (
        _lerp(BG_TOP[0], BG_BOTTOM[0], t),
        _lerp(BG_TOP[1], BG_BOTTOM[1], t),
        _lerp(BG_TOP[2], BG_BOTTOM[2], t),
    )


def _inside_palm(nx: float, ny: float) -> bool:
    # Ладонь — скруглённый прямоугольник в нижней половине.
    cx, cy = 0.5, 0.62
    rx, ry = 0.24, 0.22
    return ((nx - cx) / rx) ** 2 + ((ny - cy) / ry) ** 2 <= 1.0


def _inside_finger(nx: float, ny: float) -> bool:
    # Четыре вертикальных «пальца» над ладонью.
    fingers = [0.34, 0.44, 0.54, 0.64]
    for x0 in fingers:
        if abs(nx - x0) <= 0.045 and 0.20 <= ny <= 0.52:
            return True
    # Большой палец — наклонный, слева.
    if 0.18 <= nx <= 0.30 and 0.44 <= ny <= 0.62 and (nx - 0.30) <= -(ny - 0.44) * 0.8:
        return True
    return False


def render(size: int, *, maskable: bool, padding: float) -> bytes:
    """Нарисовать квадратную иконку `size×size` и вернуть PNG-байты.

    `padding` — доля отступа под важную часть рисунка (для maskable-safe зоны
    Android нужен запас: значок занимает центральные ~80%).
    """
    rows: list[bytes] = []
    inner = 1.0 - 2 * padding
    for y in range(size):
        row = bytearray()
        for x in range(size):
            r, g, b = _bg(x, y, size)
            alpha = 255
            # Нормализуем координаты внутрь «важной» области.
            nx = (x / (size - 1) - padding) / inner
            ny = (y / (size - 1) - padding) / inner
            if 0 <= nx <= 1 and 0 <= ny <= 1:
                if _inside_palm(nx, ny) or _inside_finger(nx, ny):
                    r, g, b = HAND
                else:
                    # Тонкая акцентная «орбита» вокруг знака для узнаваемости.
                    d = ((nx - 0.5) ** 2 + (ny - 0.5) ** 2) ** 0.5
                    if 0.40 <= d <= 0.44:
                        r, g, b = ACCENT
            row += bytes((r, g, b, alpha))
        rows.append(bytes(row))
    return _encode_png(size, size, rows)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _encode_png(width: int, height: int, rows: list[bytes]) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8 бит, RGBA
    raw = b"".join(b"\x00" + row for row in rows)  # фильтр 0 на каждую строку
    idat = zlib.compress(raw, 9)
    return signature + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("maskable-512.png", 512, True),
    ]
    for name, size, maskable in targets:
        padding = 0.12 if maskable else 0.06
        png = render(size, maskable=maskable, padding=padding)
        path = OUT_DIR / name
        path.write_bytes(png)
        print(f"{path.relative_to(OUT_DIR.parent.parent)}: {len(png)} байт")


if __name__ == "__main__":
    main()
