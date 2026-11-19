"""Конвертация видео Slovo в клипы landmarks (C2) для аватара.

Читает датасет Slovo (``annotations.csv`` + ``train/*.mp4``), прогоняет кадры
через MediaPipe Holistic (Tasks API) и сохраняет по одному клипу на слово:

    staging/
        manifest.json       # план: глосса → файл, статус, метаданные
        clips/<slug>.json.gz

Клипы повторяют конвейер записи жеста ``frontend/clip-record.ts``: пересэмпли-
рование на 30 FPS, сглаживание соседних кадров и упаковка Float16 →
gzip → base64. Лицо в клипах не сохраняется (сейчас нужны только корпус и
руки); ретаргет на клиенте пропускает отсутствующую часть layout.

Запуск::

    .venv/bin/python scripts/slovo_to_clips.py ../slovo --out ../slovo_motion
    .venv/bin/python scripts/slovo_to_clips.py ../slovo --out ../slovo_motion \\
        --only козел --only ДАКТИЛЬ_А

Импорт в Django (внутри ``web``)::

    python manage.py import_slovo /import --lang rsl --replace-clips
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import json
import math
import os
import re
import struct
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

# MediaPipe/absl пишут служебные WARNING в stderr на каждый кадр; для пакетной
# конвертации это шум. Переменная действует до инициализации TensorFlow Lite,
# поэтому выставляется на уровне модуля: её видят и дочерние процессы пула.
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

FPS = 30
MAX_FRAMES = 300
LAYOUT = {"pose": 33, "hand_l": 21, "hand_r": 21}
LAYOUT_POINTS = sum(LAYOUT.values())
CLIP_VERSION = 1

DEFAULT_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/holistic_landmarker/"
    "holistic_landmarker/float16/1/holistic_landmarker.task"
)

# Кириллица в имени файла не нужна: ASCII-слаг повторяет ``_ascii_slug`` из
# ``dictionary.services``, чтобы имена клипов было удобно читать в томе.
_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}
_LETTER_RE = re.compile(r"^[А-ЯЁ]$")


class SlovoError(RuntimeError):
    """Видео не удалось превратить в клип."""


# --- Модель ----------------------------------------------------------------


def ensure_model(path: Path, url: str = DEFAULT_MODEL_URL) -> Path:
    """Скачать ``holistic_landmarker.task``, если его ещё нет."""
    if path.is_file() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Скачиваю модель MediaPipe: {url}", file=sys.stderr)
    import urllib.request

    with urllib.request.urlopen(url, timeout=120) as response:
        blob = response.read()
    path.write_bytes(blob)
    return path


# --- Разбор датасета -------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    """Одно видео датасета и его глосса."""

    video: str
    label: str
    gloss: str
    split: str
    signer: str
    frames: int


def _glosses_for_label(label: str) -> list[str]:
    """Преобразовать метку, включая фразы и варианты через точку с запятой."""
    parts = [part.strip() for part in label.split(";") if part.strip()]
    glosses: list[str] = []
    for part in parts:
        if _LETTER_RE.match(part):
            glosses.append(f"ДАКТИЛЬ_{part.upper()}")
        else:
            gloss = " ".join(part.rstrip("!?").upper().split())
            if gloss:
                glosses.append(gloss)
    return glosses


def _slug(value: str) -> str:
    chars: list[str] = []
    for char in value.lower():
        if char.isascii() and (char.isalnum() or char in "-_"):
            chars.append(char)
        elif char in _TRANSLIT:
            chars.append(_TRANSLIT[char])
        elif chars and chars[-1] != "-":
            chars.append("-")
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:60] or "sign"


def _file_stem(gloss: str, taken: set[str]) -> str:
    """Уникальное имя файла для глоссы.

    Транслит склеивает разные кириллические буквы (``Ё``/``Е``/``Э`` → ``e``,
    ``Й``/``Ы`` → ``y``, ``Ъ``/``Ь`` → пусто), поэтому одной строки мало: при
    совпадении добавляется короткий хеш глоссы, иначе один жест молча
    перезаписал бы другой.
    """
    slug = _slug(gloss)
    stem = slug
    if stem in taken:
        digest = hashlib.sha1(gloss.encode("utf-8")).hexdigest()[:6]
        stem = f"{slug}-{digest}"
    taken.add(stem)
    return stem


def _video_path(dataset: Path, split: str, video: str) -> Path:
    return dataset / split / f"{video}.mp4"


def plan_entries(dataset: Path, *, split: str = "train") -> dict[str, list[Entry]]:
    """Сгруппировать видео по глоссам, отбросив ``no_event``.

    Берётся только выбранный сплит (по умолчанию ``train``): он больше и не
    пересекается с тестом. Для каждой глоссы возвращается список кандидатов в
    порядке датасета; первый доступный файл становится клипом.
    """
    csv_path = dataset / "annotations.csv"
    if not csv_path.is_file():
        raise SlovoError(f"Нет файла разметки: {csv_path}")

    by_gloss: dict[str, list[Entry]] = {}
    with csv_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            label = (row.get("text") or "").strip()
            video = (row.get("attachment_id") or "").strip()
            if not label or not video or label == "no_event":
                continue
            if split and row.get("train") != "True" and split == "train":
                continue
            if split and row.get("train") == "True" and split != "train":
                continue
            if not _video_path(dataset, split or "train", video).is_file():
                continue
            for gloss in _glosses_for_label(label):
                by_gloss.setdefault(gloss, []).append(
                    Entry(
                        video=video,
                        label=label,
                        gloss=gloss,
                        split=split or "train",
                        signer=(row.get("user_id") or "").strip(),
                        frames=int(float(row.get("length") or 0)),
                    )
                )
    # Для совпавшей глоссы сначала идёт её собственная запись, затем варианты
    # из составных меток. Так «кусок» получает свою запись, а «тонкими
    # слоями» сохраняет видео из «кусок; тонкими слоями».
    for entries in by_gloss.values():
        entries.sort(key=lambda entry: ";" in entry.label)
    return by_gloss


# --- MediaPipe -------------------------------------------------------------


@dataclass
class SkeletonFrame:
    """Landmarks в мировых координатах MediaPipe, в метрах."""

    time_ms: float
    pose: list[tuple[float, float, float]]
    left_hand: list[tuple[float, float, float]]
    right_hand: list[tuple[float, float, float]]

    def has_body(self) -> bool:
        return len(self.left_hand) >= 21 or len(self.right_hand) >= 21 or len(self.pose) >= 15


def _landmarks(points) -> list[tuple[float, float, float]]:
    return [(float(p.x), float(p.y), float(p.z)) for p in points]


def _read_frames(video: Path, landmarker) -> list[SkeletonFrame]:
    """Прочитать видео и получить landmarks для каждого кадра."""
    import av
    import mediapipe as mp
    import numpy as np

    frames: list[SkeletonFrame] = []
    timestamp_ms = -1
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        source_fps = float(stream.average_rate or FPS)
        for index, frame in enumerate(container.decode(stream)):
            time_ms = (
                float(frame.time) * 1000 if frame.time is not None else index * 1000 / source_fps
            )
            timestamp_ms = max(timestamp_ms + 1, round(time_ms))
            image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(frame.to_ndarray(format="rgb24")),
            )
            result = landmarker.detect_for_video(image, timestamp_ms)
            frames.append(
                SkeletonFrame(
                    time_ms=timestamp_ms,
                    pose=_landmarks(result.pose_world_landmarks),
                    left_hand=_landmarks(result.left_hand_world_landmarks),
                    right_hand=_landmarks(result.right_hand_world_landmarks),
                )
            )
    return frames


def _create_landmarker(model_path: Path):
    from mediapipe.tasks.python import BaseOptions, vision

    options = vision.HolisticLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        min_pose_detection_confidence=0.4,
        min_pose_landmarks_confidence=0.4,
        min_hand_landmarks_confidence=0.4,
    )
    return vision.HolisticLandmarker.create_from_options(options)


# --- Обработка кадров (порт frontend/clip-record.ts) ----------------------


def auto_trim_range(
    frames: list[SkeletonFrame], *, padding: int = 2, min_frames: int = 2
) -> tuple[int, int] | None:
    """От первой до последней позы/кисти плюс запас кадров по краям."""
    first = -1
    last = -1
    for index, frame in enumerate(frames):
        if frame.has_body():
            if first == -1:
                first = index
            last = index
    if first == -1:
        return None
    start = max(0, first - padding)
    end = min(len(frames), last + 1 + padding)
    if end - start < min_frames:
        end = min(len(frames), start + min_frames)
        start = max(0, end - min_frames)
    return start, end


def resample(frames: list[SkeletonFrame], fps: int = FPS) -> list[SkeletonFrame]:
    """Равномерная сетка: для каждой метки берётся ближайший по времени кадр."""
    if not frames:
        return []
    if len(frames) == 1:
        return [frames[0]]
    first_time = frames[0].time_ms
    duration_ms = max(0.0, frames[-1].time_ms - first_time)
    count = round(duration_ms / 1000 * fps) + 1
    step = 1000 / fps
    result: list[SkeletonFrame] = []
    source = 0
    for index in range(count):
        target = first_time + index * step
        while source + 1 < len(frames) and abs(frames[source + 1].time_ms - target) <= abs(
            frames[source].time_ms - target
        ):
            source += 1
        frame = frames[source]
        result.append(
            SkeletonFrame(
                target,
                frame.pose,
                frame.left_hand,
                frame.right_hand,
            )
        )
    return result


def _smooth_points(before: list[tuple], current: list[tuple], after: list[tuple]) -> list[tuple]:
    """Короткое симметричное окно без фазовой задержки и склейки через пропуск."""
    if not (len(before) == len(current) == len(after)):
        return current
    return [
        tuple(0.125 * a + 0.75 * b + 0.125 * c for a, b, c in zip(prev, point, nxt, strict=True))
        for prev, point, nxt in zip(before, current, after, strict=True)
    ]


def prepare_frames(frames: list[SkeletonFrame]) -> list[SkeletonFrame]:
    """Заполнить пропуски позы и сгладить каждую кисть отдельно."""
    pose = next((frame.pose for frame in frames if len(frame.pose) == 33), None)
    if pose is None:
        raise SlovoError("В видео не найдена пространственная поза.")

    prepared: list[SkeletonFrame] = []
    missing_hand = [(0.0, 0.0, 0.0)] * 21
    for index, frame in enumerate(frames):
        before = frames[max(0, index - 1)]
        after = frames[min(len(frames) - 1, index + 1)]
        if len(frame.pose) == 33:
            pose = _smooth_points(before.pose, frame.pose, after.pose)
        prepared.append(
            SkeletonFrame(
                frame.time_ms,
                pose,
                _smooth_points(before.left_hand, frame.left_hand, after.left_hand)
                if len(frame.left_hand) == 21
                else missing_hand,
                _smooth_points(before.right_hand, frame.right_hand, after.right_hand)
                if len(frame.right_hand) == 21
                else missing_hand,
            )
        )
    return prepared


# --- Упаковка клипа (порт frontend/clip-encode.ts) ------------------------


def to_float16_bits(value: float) -> int:
    """IEEE 754 binary16; поведение совпадает с ``toFloat16Bits``."""
    if math.isnan(value):
        return 0x7E00
    if value == math.inf:
        return 0x7C00
    if value == -math.inf:
        return 0xFC00
    sign = 0x8000 if math.copysign(1.0, value) < 0 else 0
    absolute = abs(value)
    if absolute == 0:
        return sign
    exponent = math.floor(math.log2(absolute))
    half_exponent = exponent + 15
    if half_exponent >= 0x1F:
        return sign | 0x7C00
    if half_exponent <= 0:
        return sign | round(absolute / 2**-24)
    mantissa = round((absolute / 2**exponent - 1) * 1024)
    if mantissa == 1024:
        half_exponent += 1
        if half_exponent >= 0x1F:
            return sign | 0x7C00
        return sign | (half_exponent << 10)
    return sign | (half_exponent << 10) | mantissa


def flatten(frames: list[SkeletonFrame]) -> list[float]:
    values: list[float] = []
    for frame in frames:
        for part in (frame.pose, frame.left_hand, frame.right_hand):
            for x, y, z in part:
                values.extend((x, y, z))
    return values


def encode_clip_payload(*, gloss: str, fps: int, frames: int, values: list[float]) -> dict:
    expected = frames * LAYOUT_POINTS * 3
    if len(values) != expected:
        raise SlovoError(f"Значений {len(values)}, ожидалось {expected}.")
    raw = bytearray(len(values) * 2)
    for index, value in enumerate(values):
        struct.pack_into("<H", raw, index * 2, to_float16_bits(value))
    compressed = gzip.compress(bytes(raw), mtime=0)
    return {
        "version": CLIP_VERSION,
        "gloss": gloss,
        "fps": fps,
        "frames": frames,
        "layout": dict(LAYOUT),
        "coordinate_space": "mediapipe-world",
        "data": base64.b64encode(compressed).decode("ascii"),
    }


def pack_clip_file(payload: dict) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, mtime=0)


# --- Один клип -------------------------------------------------------------


def build_clip(
    video: Path, *, gloss: str, model_path: Path, fps: int = FPS, max_frames: int = MAX_FRAMES
) -> tuple[bytes, dict]:
    """Видео → файл клипа и метаданные для manifest."""
    landmarker = _create_landmarker(model_path)
    try:
        frames = _read_frames(video, landmarker)
    finally:
        landmarker.close()

    trimmed = auto_trim_range(frames)
    if trimmed is None:
        raise SlovoError("В видео не найдены поза или кисти.")
    start, end = trimmed
    selected = frames[start:end]
    sampled = resample(selected, fps)[:max_frames]
    if not sampled:
        raise SlovoError("После обрезки не осталось кадров.")
    prepared = prepare_frames(sampled)
    payload = encode_clip_payload(
        gloss=gloss, fps=fps, frames=len(prepared), values=flatten(prepared)
    )
    blob = pack_clip_file(payload)
    meta = {
        "frames": len(prepared),
        "fps": fps,
        "duration_ms": round(len(prepared) / fps * 1000),
        "source_frames": len(frames),
        "trim": [start, end],
        "size_bytes": len(blob),
    }
    return blob, meta


def _worker(job: dict) -> dict:
    """Обработать одно видео; ошибки возвращаются в результате, не роняют пул."""
    try:
        blob, meta = build_clip(
            Path(job["video"]),
            gloss=job["gloss"],
            model_path=Path(job["model"]),
            fps=job["fps"],
            max_frames=job["max_frames"],
        )
        Path(job["target"]).parent.mkdir(parents=True, exist_ok=True)
        Path(job["target"]).write_bytes(blob)
        return {"ok": True, "gloss": job["gloss"], "file": job["file"], **meta}
    except Exception as exc:  # noqa: BLE001 — ошибка одного видео не должна рвать импорт
        return {"ok": False, "gloss": job["gloss"], "error": f"{type(exc).__name__}: {exc}"}


# --- CLI -------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Slovo → клипы landmarks (.json.gz).")
    parser.add_argument("dataset", type=Path, help="Папка Slovo с annotations.csv и train/.")
    parser.add_argument("--out", type=Path, required=True, help="Папка staging для клипов.")
    parser.add_argument("--model", type=Path, default=None, help="Путь к holistic_landmarker.task.")
    parser.add_argument(
        "--model-url", default=os.environ.get("MEDIAPIPE_HOLISTIC_MODEL_URL", DEFAULT_MODEL_URL)
    )
    parser.add_argument(
        "--split", default="train", choices=("train", "test"), help="Какой сплит брать."
    )
    parser.add_argument(
        "--only", action="append", default=[], help="Глоссы или метки (можно несколько)."
    )
    parser.add_argument("--limit", type=int, default=0, help="Ограничить число клипов.")
    parser.add_argument(
        "--skip-existing", action="store_true", help="Не пересчитывать готовые клипы."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, min(4, os.cpu_count() or 1)),
        help="Параллельные процессы.",
    )
    parser.add_argument("--fps", type=int, default=FPS)
    parser.add_argument("--max-frames", type=int, default=MAX_FRAMES)
    return parser.parse_args(argv)


def _select(by_gloss: dict[str, list[Entry]], only: list[str], limit: int) -> dict[str, Entry]:
    wanted = {item.strip().upper() for item in only if item.strip()}
    chosen: dict[str, Entry] = {}
    for gloss in sorted(by_gloss):
        candidates = by_gloss[gloss]
        if (
            wanted
            and gloss not in wanted
            and not any(entry.label.upper() in wanted for entry in candidates)
        ):
            continue
        chosen[gloss] = candidates[0]
    if limit:
        chosen = dict(list(chosen.items())[:limit])
    return chosen


def _reusable_clip(target: Path, gloss: str, fps: int, max_frames: int) -> dict | None:
    """При возобновлении не принимать клипы старого формата или другой глоссы."""
    try:
        with gzip.open(target, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, EOFError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    frames = payload.get("frames")
    if (
        payload.get("coordinate_space") != "mediapipe-world"
        or payload.get("gloss") != gloss
        or payload.get("fps") != fps
        or not isinstance(frames, int)
        or not 0 < frames <= max_frames
    ):
        return None
    return {
        "status": "skipped",
        "frames": frames,
        "fps": fps,
        "duration_ms": round(frames / fps * 1000),
        "size_bytes": target.stat().st_size,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dataset: Path = args.dataset.resolve()
    out: Path = args.out.resolve()
    model_path = args.model or (
        Path(__file__).resolve().parents[1] / "assets" / "models" / "holistic_landmarker.task"
    )
    ensure_model(model_path, args.model_url)

    if args.fps < 1 or args.max_frames < 1:
        print("--fps и --max-frames должны быть положительными.", file=sys.stderr)
        return 2

    by_gloss = plan_entries(dataset, split=args.split)
    chosen = _select(by_gloss, args.only, args.limit)
    if not chosen:
        print("Нечего импортировать: проверьте --only/--split.", file=sys.stderr)
        return 2

    clips_dir = out / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    previous = {}
    if args.skip_existing and manifest_path.is_file():
        try:
            old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(old_manifest, dict) and isinstance(old_manifest.get("clips"), dict):
                previous = old_manifest["clips"]
        except (OSError, ValueError):
            pass

    jobs: list[dict] = []
    planned: dict[str, dict] = {}
    taken_stems: set[str] = set()
    file_names: dict[str, str] = {}
    for gloss, prior in previous.items():
        if not isinstance(prior, dict) or gloss not in by_gloss:
            continue
        name = prior.get("file")
        if isinstance(name, str) and re.fullmatch(r"[a-z0-9_-]+\.json\.gz", name):
            stem = name.removesuffix(".json.gz")
            if stem not in taken_stems:
                file_names[gloss] = name
                taken_stems.add(stem)
    for gloss in sorted(by_gloss):
        if gloss not in file_names:
            file_names[gloss] = f"{_file_stem(gloss, taken_stems)}.json.gz"
    for gloss, entry in chosen.items():
        file_name = file_names[gloss]
        target = clips_dir / file_name
        planned[gloss] = {
            "label": entry.label,
            "gloss": gloss,
            "source_video": str(_video_path(dataset, entry.split, entry.video)),
            "split": entry.split,
            "signer": entry.signer,
            "file": file_name,
            "status": "pending",
        }
        prior = previous.get(gloss, {})
        if (
            isinstance(prior, dict)
            and prior.get("status") in {"ok", "skipped"}
            and prior.get("source_video") == planned[gloss]["source_video"]
        ):
            existing = _reusable_clip(target, gloss, args.fps, args.max_frames)
            if existing is not None:
                planned[gloss] = {**prior, **planned[gloss], **existing}
                continue
        jobs.append(
            {
                "video": planned[gloss]["source_video"],
                "gloss": gloss,
                "model": str(model_path),
                "fps": args.fps,
                "max_frames": args.max_frames,
                "target": str(target),
                "file": file_name,
            }
        )

    print(
        f"Клипов к обработке: {len(jobs)}; уже готовы: "
        f"{sum(1 for item in planned.values() if item['status'] == 'skipped')}.",
        file=sys.stderr,
    )

    done = 0
    errors = 0
    if jobs:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(_worker, job) for job in jobs]
            for future in as_completed(futures):
                result = future.result()
                done += 1
                gloss = result["gloss"]
                if result["ok"]:
                    planned[gloss].update(
                        {
                            "status": "ok",
                            "frames": result["frames"],
                            "fps": result["fps"],
                            "duration_ms": result["duration_ms"],
                            "source_frames": result["source_frames"],
                            "trim": result["trim"],
                            "size_bytes": result["size_bytes"],
                        }
                    )
                else:
                    errors += 1
                    planned[gloss].update({"status": "error", "error": result["error"]})
                print(f"[{done}/{len(jobs)}] {gloss}: {planned[gloss]['status']}", file=sys.stderr)

    manifest = {
        "dataset": str(dataset),
        "split": args.split,
        "fps": args.fps,
        "layout": LAYOUT,
        "coordinate_space": "mediapipe-world",
        "clips": planned,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for item in planned.values() if item["status"] in {"ok", "skipped"})
    print(f"Готово клипов: {ok}, ошибок: {errors}. Manifest: {manifest_path}", file=sys.stderr)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
