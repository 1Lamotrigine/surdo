"""Импорт клипов Slovo (landmarks) и конвертация видео в клипы.

Скрипт ``scripts/slovo_to_clips.py`` запускается на хосте (MediaPipe только в
``requirements-dev``), а команда ``import_slovo`` — в контейнере. Тесты
проверяют формат упаковки, устойчивость импорта и замену старых клипов; сами
видео и MediaPipe в тестах не нужны.
"""

from __future__ import annotations

import gzip
import json
import struct
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from dictionary.models import (
    ClipFormat,
    DictionaryVersion,
    Language,
    Sign,
    SignClip,
    SignStatus,
)
from pipeline.events import clip_refs_for_glosses
from services.clips import pack_clip, parse_clip

pytestmark = pytest.mark.django_db

SLovo = pytest.importorskip("scripts.slovo_to_clips", reason="нужен mediapipe/numpy")


# --- Формат клипа ----------------------------------------------------------


def _sample_clip(gloss: str = "КОШКА", frames: int = 3) -> bytes:
    points = SLovo.LAYOUT_POINTS
    values: list[float] = []
    for frame in range(frames):
        for point in range(points):
            values.extend((0.1 * point + frame, 0.2, -0.3))
    payload = SLovo.encode_clip_payload(gloss=gloss, fps=30, frames=frames, values=values)
    return SLovo.pack_clip_file(payload)


def test_encoded_clip_parses_with_server_format():
    blob = _sample_clip()

    meta = parse_clip(blob)

    assert meta.version == 1
    assert meta.gloss == "КОШКА"
    assert meta.fps == 30
    assert meta.frames == 3
    assert meta.layout == {"pose": 33, "hand_l": 21, "hand_r": 21}
    assert meta.duration_ms == 100


def test_encoded_clip_uses_little_endian_float16():
    blob = _sample_clip()
    payload = json.loads(gzip.decompress(blob))
    raw = gzip.decompress(SLovo.base64.b64decode(payload["data"]))

    assert len(raw) == 3 * SLovo.LAYOUT_POINTS * 3 * 2
    # Первое значение — x первой точки первого кадра: 0.0 в Float16.
    assert struct.unpack_from("<e", raw, 0)[0] == 0.0
    # Первая точка второго кадра — ровно 1.0 (0x3c00 в little-endian).
    offset = SLovo.LAYOUT_POINTS * 3 * 2
    assert struct.unpack_from("<e", raw, offset)[0] == 1.0
    assert struct.unpack_from("<H", raw, offset)[0] == 0x3C00


def test_float16_matches_frontend_special_values():
    assert SLovo.to_float16_bits(0.0) == 0x0000
    assert SLovo.to_float16_bits(-0.0) == 0x8000
    assert SLovo.to_float16_bits(1.0) == 0x3C00
    assert SLovo.to_float16_bits(-1.0) == 0xBC00
    assert SLovo.to_float16_bits(65504.0) == 0x7BFF
    assert SLovo.to_float16_bits(100000.0) == 0x7C00
    assert SLovo.to_float16_bits(float("inf")) == 0x7C00
    assert SLovo.to_float16_bits(float("-inf")) == 0xFC00
    assert SLovo.to_float16_bits(float("nan")) == 0x7E00


def test_gloss_mapping_letters_and_semicolon_alternatives():
    assert SLovo._glosses_for_label("А") == ["ДАКТИЛЬ_А"]
    assert SLovo._glosses_for_label("Ё") == ["ДАКТИЛЬ_Ё"]
    assert SLovo._glosses_for_label("козел") == ["КОЗЕЛ"]
    assert SLovo._glosses_for_label("вредный; озорной") == ["ВРЕДНЫЙ", "ОЗОРНОЙ"]
    assert SLovo._glosses_for_label("летучая мышь") == ["ЛЕТУЧАЯ МЫШЬ"]


def test_auto_trim_uses_body_frames():
    empty = SLovo.SkeletonFrame(0, [], [], [])
    body = SLovo.SkeletonFrame(0, [(0.5, 0.5, 0.0)] * 15, [], [])
    frames = [empty, empty, body, body, empty, empty]

    # По умолчанию по 2 кадра запаса с каждой стороны.
    assert SLovo.auto_trim_range(frames) == (0, 6)
    assert SLovo.auto_trim_range(frames, padding=0) == (2, 4)


def test_auto_trim_without_body_returns_none():
    empty = SLovo.SkeletonFrame(0, [], [], [])
    assert SLovo.auto_trim_range([empty, empty]) is None


# --- Команда импорта -------------------------------------------------------


def _staging(tmp_path: Path, clips: dict[str, bytes]) -> Path:
    """Собрать staging-папку с manifest.json, как ``slovo_to_clips.py``."""
    clips_dir = tmp_path / "staging" / "clips"
    clips_dir.mkdir(parents=True)
    manifest: dict = {
        "dataset": str(tmp_path / "slovo"),
        "split": "train",
        "fps": 30,
        "layout": SLovo.LAYOUT,
        "clips": {},
    }
    for gloss, blob in clips.items():
        file_name = f"{SLovo._slug(gloss)}.json.gz"
        (clips_dir / file_name).write_bytes(blob)
        manifest["clips"][gloss] = {
            "label": gloss.lower(),
            "gloss": gloss,
            "source_video": str(tmp_path / "slovo" / "train" / "x.mp4"),
            "split": "train",
            "signer": "signer",
            "file": file_name,
            "status": "ok",
        }
    (tmp_path / "staging" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path / "staging"


def _run(staging: Path, *args: str) -> str:
    output = StringIO()
    call_command("import_slovo", str(staging), *args, stdout=output)
    return output.getvalue()


def test_import_slovo_creates_verified_signs_and_bumps_version_once(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    staging = _staging(
        tmp_path, {"КОШКА": _sample_clip("КОШКА"), "ДАКТИЛЬ_А": _sample_clip("ДАКТИЛЬ_А")}
    )

    _run(staging)

    signs = {sign.gloss: sign for sign in Sign.objects.all()}
    assert set(signs) == {"КОШКА", "ДАКТИЛЬ_А"}
    assert all(sign.status == SignStatus.VERIFIED for sign in signs.values())
    assert signs["КОШКА"].clips.get().format == ClipFormat.LANDMARKS
    assert signs["КОШКА"].clips.get().frames == 3
    assert DictionaryVersion.objects.filter(lang=Language.RSL).count() == 1


def test_import_slovo_is_idempotent(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    staging = _staging(tmp_path, {"КОШКА": _sample_clip("КОШКА")})

    _run(staging)
    _run(staging)

    assert Sign.objects.count() == 1
    assert SignClip.objects.count() == 1
    # Новый клип — изменение словаря, поэтому версия выросла один раз;
    # повторный импорт того же файла версию не трогает.
    assert DictionaryVersion.objects.filter(lang=Language.RSL).count() == 1


def test_import_slovo_bumps_version_when_verified_sign_gets_clip(settings, tmp_path):
    """Жест уже проверен, но клип новый — версия словаря должна вырасти."""
    settings.MEDIA_ROOT = tmp_path / "media"
    sign = Sign.objects.create(gloss="КОШКА", lang=Language.RSL, status=SignStatus.VERIFIED)
    DictionaryVersion.bump(Language.RSL)
    staging = _staging(tmp_path, {"КОШКА": _sample_clip("КОШКА")})

    _run(staging)

    sign.refresh_from_db()
    assert sign.clips.count() == 1
    assert DictionaryVersion.objects.filter(lang=Language.RSL).count() == 2


def test_import_slovo_replaces_animation_clips(settings, tmp_path):
    """Клип Slovo должен стать лучшим: иначе анимация выигрывает у landmarks."""
    settings.MEDIA_ROOT = tmp_path / "media"
    sign = Sign.objects.create(gloss="ПОКА", lang=Language.RSL, status=SignStatus.VERIFIED)
    old = pack_clip(
        gloss="ПОКА",
        fps=30,
        frames=2,
        layout={"pose": 1, "hand_l": 1, "hand_r": 1},
        data="AAAA",
    )
    path = "clips/old-poka.json.gz"
    (tmp_path / "media" / path).parent.mkdir(parents=True)
    (tmp_path / "media" / path).write_bytes(old)
    old_clip = SignClip.objects.create(
        sign=sign,
        file=path,
        format=ClipFormat.ANIMATION,
        animation_name="ПОКА",
        fps=30,
        duration_ms=2000,
        frames=0,
        version=1,
        size_bytes=len(old),
    )
    staging = _staging(tmp_path, {"ПОКА": _sample_clip("ПОКА")})

    _run(staging, "--replace-clips")

    clips = list(SignClip.objects.filter(sign=sign))
    assert len(clips) == 1
    assert clips[0].format == ClipFormat.LANDMARKS
    assert not (tmp_path / "media" / old_clip.file.name).exists()

    refs = clip_refs_for_glosses(
        {"lang": Language.RSL, "tokens": [{"type": "sign", "gloss": "ПОКА"}]}
    )
    assert [ref["format"] for ref in refs] == ["landmarks"]


def test_import_slovo_dry_run_writes_nothing(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    staging = _staging(tmp_path, {"КОШКА": _sample_clip("КОШКА")})

    _run(staging, "--dry-run")

    assert Sign.objects.count() == 0
    assert not (tmp_path / "media" / "clips").exists()


def test_import_slovo_only_filters_glosses(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    staging = _staging(tmp_path, {"КОШКА": _sample_clip("КОШКА"), "СОБАКА": _sample_clip("СОБАКА")})

    _run(staging, "--only", "КОШКА")

    assert [sign.gloss for sign in Sign.objects.all()] == ["КОШКА"]


def test_import_slovo_rejects_broken_manifest(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    folder = tmp_path / "empty"
    folder.mkdir()

    with pytest.raises(CommandError):
        call_command("import_slovo", str(folder), stdout=StringIO())


def test_slovo_uses_world_coordinates_without_copying_the_other_hand():
    pose = [(0.0, -0.2, 0.0)] * 33
    right_hand = [(0.0, -0.01 * index, 0.0) for index in range(21)]
    source = [SLovo.SkeletonFrame(0, pose, [], right_hand)]
    prepared = SLovo.prepare_frames(source)

    assert prepared[0].left_hand == [(0.0, 0.0, 0.0)] * 21
    assert SLovo.flatten(prepared)[-63:] == pytest.approx(
        [v for point in right_hand for v in point]
    )
    payload = SLovo.encode_clip_payload(
        gloss="ДА", fps=30, frames=1, values=SLovo.flatten(prepared)
    )
    assert payload["coordinate_space"] == "mediapipe-world"


def test_resample_includes_last_source_frame():
    frames = [SLovo.SkeletonFrame(time, [], [], []) for time in (0, 33, 67)]

    assert len(SLovo.resample(frames, fps=30)) == 3


def test_slovo_gloss_matches_word_with_exclamation_point():
    assert SLovo._glosses_for_label("Привет!") == ["ПРИВЕТ"]


def test_skip_existing_requires_world_clip(tmp_path):
    target = tmp_path / "clip.json.gz"
    payload = SLovo.encode_clip_payload(
        gloss="ДА", fps=30, frames=1, values=[0] * (SLovo.LAYOUT_POINTS * 3)
    )
    target.write_bytes(SLovo.pack_clip_file(payload))
    assert SLovo._reusable_clip(target, "ДА", 30, 300)["frames"] == 1
    assert SLovo._reusable_clip(target, "НЕТ", 30, 300) is None
    del payload["coordinate_space"]
    target.write_bytes(SLovo.pack_clip_file(payload))
    assert SLovo._reusable_clip(target, "ДА", 30, 300) is None


def test_smoothing_keeps_a_quick_peak_at_the_source_frame():
    still = [(0.0, 0.0, 0.0)] * 33
    motion = [(1.0, 0.0, 0.0)] * 33
    frames = [
        SLovo.SkeletonFrame(time, pose, [], [])
        for time, pose in ((0, still), (33, motion), (67, still))
    ]

    assert [frame.pose[0][0] for frame in SLovo.prepare_frames(frames)] == [0.125, 0.75, 0.125]


def test_slovo_phrase_and_number_resolve_to_recorded_clips(settings, tmp_path):
    from pipeline.glosses import build_simplified_glosses
    from services.gloss import GlossDictionary, fallback_glosses

    settings.MEDIA_ROOT = tmp_path / "media"
    signs = ("ДВЕ", "ДВЕ НЕДЕЛИ", "НЕДЕЛИ", "7:45", "СОРОК")
    _run(_staging(tmp_path, {word: _sample_clip(word) for word in signs}))
    dictionary = GlossDictionary.from_glosses(signs, lang="rsl", version=1)
    text = "Две недели. 7:45. Сорок"
    for result in (
        build_simplified_glosses(
            text, lang="rsl", signs={word.lower().replace(" ", ""): word for word in signs}
        ),
        fallback_glosses(text, "rsl", dictionary),
    ):
        assert [ref["gloss"] for ref in clip_refs_for_glosses(result)] == [
            "ДВЕ НЕДЕЛИ",
            "7:45",
            "СОРОК",
        ]
