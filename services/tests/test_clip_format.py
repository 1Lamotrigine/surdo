"""Формат клипа: упаковка, чтение и валидация ``.json.gz``."""

import gzip
import json

import pytest

from services.clips import ClipFormatError, ClipMeta, pack_clip, parse_clip

LAYOUT = {"pose": 33, "hand_l": 21, "hand_r": 21, "face": 468}


def _clip(**overrides) -> bytes:
    payload = {
        "version": 1,
        "gloss": "УЧЕБНИК",
        "fps": 30,
        "frames": 54,
        "layout": LAYOUT,
        "data": "H4sIA",
    }
    payload.update(overrides)
    return gzip.compress(json.dumps(payload).encode("utf-8"))


def test_pack_and_parse_roundtrip():
    blob = pack_clip(gloss="УЧЕБНИК", fps=30, frames=54, layout=LAYOUT, data="H4sIA")

    meta = parse_clip(blob)

    assert meta.gloss == "УЧЕБНИК"
    assert meta.fps == 30
    assert meta.frames == 54
    assert meta.layout == LAYOUT
    assert meta.data == "H4sIA"
    assert meta.version == 1


def test_pack_is_gzipped_json():
    blob = pack_clip(gloss="ЖЕСТ", fps=30, frames=10, layout=LAYOUT, data="x")

    payload = json.loads(gzip.decompress(blob))

    assert payload["gloss"] == "ЖЕСТ"
    assert payload["frames"] == 10


def test_duration_is_derived_from_frames_and_fps():
    meta = parse_clip(_clip(fps=30, frames=60))

    assert meta.duration_ms == 2000


def test_duration_is_zero_without_fps():
    # fps=0 отвергается парсером, поэтому проверяем свойство напрямую.
    meta = ClipMeta(version=1, gloss="X", fps=0, frames=30, layout=LAYOUT, data="d")

    assert meta.duration_ms == 0


def test_parse_rejects_non_gzip():
    with pytest.raises(ClipFormatError):
        parse_clip(b"not gzip at all")


def test_parse_rejects_non_json():
    with pytest.raises(ClipFormatError):
        parse_clip(gzip.compress(b"<html>"))


def test_parse_rejects_json_array():
    with pytest.raises(ClipFormatError):
        parse_clip(gzip.compress(b"[1, 2, 3]"))


def test_parse_rejects_wrong_version():
    with pytest.raises(ClipFormatError):
        parse_clip(_clip(version=99))


def test_parse_rejects_non_positive_fps():
    with pytest.raises(ClipFormatError):
        parse_clip(_clip(fps=0))


def test_parse_rejects_non_positive_frames():
    with pytest.raises(ClipFormatError):
        parse_clip(_clip(frames=0))


def test_parse_rejects_too_many_frames(settings):
    settings.CLIP_MAX_FRAMES = 10

    with pytest.raises(ClipFormatError):
        parse_clip(_clip(frames=11))


def test_parse_accepts_frames_at_limit(settings):
    settings.CLIP_MAX_FRAMES = 10

    meta = parse_clip(_clip(frames=10))

    assert meta.frames == 10


def test_parse_rejects_empty_layout():
    with pytest.raises(ClipFormatError):
        parse_clip(_clip(layout={}))


def test_parse_rejects_missing_data():
    with pytest.raises(ClipFormatError):
        parse_clip(_clip(data=""))


def test_parse_rejects_boolean_fps():
    with pytest.raises(ClipFormatError):
        parse_clip(_clip(fps=True))
