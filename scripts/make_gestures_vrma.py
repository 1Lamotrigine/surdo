"""Сгенерировать набор базовых жестов кодом (VRMA, много записей в одном файле).

Формат — glTF 2.0 GLB с расширением ``VRMC_vrm_animation``: дорожки адресуют
humanoid-кости VRM (hips, spine, rightUpperArm и т. д.), а не узлы конкретной
модели. Один файл содержит несколько **именованных** анимаций; имя записи —
глосса, по которой жест находит конвейер.

Все позы строятся **от положения «руки вниз»**, а не от T-позы модели: у VRM
rest pose — руки в стороны, и без этого аватар стоял бы «буквой Т». Базовое
положение задаёт ``RELAXED`` (плечи опущены, локти чуть согнуты), а каждый жест
отклоняется от него и к нему же возвращается в начале и конце.

Скрипт предназначен для локального испытания рига.

Запуск (создаёт assets/animations/gestures.vrma):

    python scripts/make_gestures_vrma.py
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Кости humanoid, которые есть в файле. Порядок = индексы узлов в glTF.
HUMANOID_BONES: tuple[str, ...] = (
    "hips",
    "spine",
    "chest",
    "upperChest",
    "neck",
    "head",
    "leftShoulder",
    "leftUpperArm",
    "leftLowerArm",
    "leftHand",
    "leftThumbProximal",
    "leftIndexProximal",
    "leftMiddleProximal",
    "rightShoulder",
    "rightUpperArm",
    "rightLowerArm",
    "rightHand",
    "rightThumbProximal",
    "rightIndexProximal",
    "rightMiddleProximal",
)
BONE_NODE = {name: index for index, name in enumerate(HUMANOID_BONES)}

FPS = 30

# Угол, на который плечо опускается из T-позы (руки в стороны) вниз вдоль тела.
# Правая рука вращается вокруг +Z, левая — вокруг -Z (зеркально).
ARM_DOWN_DEG = 80.0
# Лёгкий изгиб локтя в спокойном положении, чтобы руки не выглядели как палки.
ELBOW_RELAX_DEG = 15.0

Quat = tuple[float, float, float, float]


def quat_from_euler(x: float, y: float, z: float) -> Quat:
    """Кватернион из углов Эйлера XYZ (радианы)."""
    cx, sx = math.cos(x / 2), math.sin(x / 2)
    cy, sy = math.cos(y / 2), math.sin(y / 2)
    cz, sz = math.cos(z / 2), math.sin(z / 2)
    return (
        sx * cy * cz + cx * sy * sz,
        cx * sy * cz - sx * cy * sz,
        cx * cy * sz + sx * sy * cz,
        cx * cy * cz - sx * sy * sz,
    )


def quat_mul(a: Quat, b: Quat) -> Quat:
    """Произведение кватернионов a * b (сначала b, потом a)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def quat_normalize(q: Quat) -> Quat:
    length = math.sqrt(q[0] ** 2 + q[1] ** 2 + q[2] ** 2 + q[3] ** 2) or 1.0
    return (q[0] / length, q[1] / length, q[2] / length, q[3] / length)


IDENTITY: Quat = (0.0, 0.0, 0.0, 1.0)


def ease(t: float) -> float:
    """Плавное начало и конец движения внутри фазы (0..1 → 0..1)."""
    return t * t * (3 - 2 * t)


def sway(phase: float, cycles: float = 1.0) -> float:
    """Колебание -1..1 за время phase (0..1)."""
    return math.sin(2 * math.pi * cycles * phase)


# --- Базовое положение «руки вниз» ----------------------------------------


def _side_sign(bone: str) -> int:
    """Знак вращения: правая рука +1, левая -1 (зеркально)."""
    return 1 if bone.startswith("right") else -1


def relaxed_pose() -> dict[str, Quat]:
    """Спокойное положение: руки опущены вдоль тела, лёгкий изгиб локтя."""
    down = math.radians(ARM_DOWN_DEG)
    elbow = math.radians(ELBOW_RELAX_DEG)
    # Правая рука опускается вращением вокруг +Z, левая — вокруг -Z:
    # в rest pose кости смотрят в стороны (+X и -X), и такой поворот
    # переводит их вниз вдоль тела.
    return {
        "leftUpperArm": quat_from_euler(0.0, 0.0, -down),
        "rightUpperArm": quat_from_euler(0.0, 0.0, down),
        "leftLowerArm": quat_from_euler(0.0, 0.0, elbow),
        "rightLowerArm": quat_from_euler(0.0, 0.0, -elbow),
    }


RELAXED = relaxed_pose()


def _base(bone: str) -> Quat:
    return RELAXED.get(bone, IDENTITY)


def _arm(side: str, *, lift: float = 0.0, out: float = 0.0, elbow: float = 0.0) -> dict[str, Quat]:
    """Поза руки: lift — поднять от «вниз» (градусы, 0 — вниз).

    ``out`` отводит руку в сторону (от тела), ``elbow`` сгибает локоть
    внутрь от спокойного положения. Правая рука опускается/поднимается
    вращением вокруг +Z, левая — вокруг -Z (зеркально).
    """
    sign = 1 if side == "right" else -1
    # Из «вниз» поднимаем руку обратно к горизонтали: угол уменьшается.
    shoulder_z = sign * (math.radians(ARM_DOWN_DEG) - math.radians(lift))
    shoulder_x = math.radians(out)
    upper = quat_mul(quat_from_euler(shoulder_x, 0.0, 0.0), quat_from_euler(0.0, 0.0, shoulder_z))
    elbow_z = -sign * (math.radians(ELBOW_RELAX_DEG) + math.radians(elbow))
    lower = quat_from_euler(0.0, 0.0, elbow_z)
    return {f"{side}UpperArm": upper, f"{side}LowerArm": lower}


# Тип позы: функция (кость) → кватернион (поза уже в «своём» положении).
Pose = Callable[[str], Quat]


def _merge(*parts: dict[str, Quat]) -> dict[str, Quat]:
    out: dict[str, Quat] = {}
    for part in parts:
        out.update(part)
    return out


def pose_wave(bone: str) -> Quat:
    """ПРИВЕТ: правая рука поднята, кисть машет (колебание даёт фаза)."""
    arm = _arm("right", lift=95.0, out=10.0, elbow=25.0)
    pose = _merge(arm, {"rightShoulder": quat_from_euler(0.0, 0.0, -math.radians(8))})
    return pose.get(bone, _base(bone))


def pose_bye(bone: str) -> Quat:
    """ПОКА: рука поднята чуть ниже и машет шире."""
    arm = _arm("right", lift=70.0, out=15.0, elbow=10.0)
    return _merge(arm, {}).get(bone, _base(bone))


def pose_yes(bone: str) -> Quat:
    """ДА: рука согнута у груди, кивок головой."""
    arm = _arm("right", lift=30.0, out=10.0, elbow=75.0)
    return _merge(arm, {}).get(bone, _base(bone))


def pose_no(bone: str) -> Quat:
    """НЕТ: рука у груди, указательный палец водит, голова поворачивается."""
    arm = _arm("right", lift=28.0, out=10.0, elbow=80.0)
    return _merge(arm, {}).get(bone, _base(bone))


def pose_thanks(bone: str) -> Quat:
    """СПАСИБО: рука от груди вперёд-вниз."""
    arm = _arm("right", lift=35.0, out=5.0, elbow=65.0)
    pose = _merge(arm, {"spine": quat_from_euler(math.radians(6), 0.0, 0.0)})
    return pose.get(bone, _base(bone))


def pose_please(bone: str) -> Quat:
    """ПОЖАЛУЙСТА: ладонь у груди, круговое движение (фаза)."""
    arm = _arm("right", lift=32.0, out=8.0, elbow=72.0)
    return _merge(arm, {}).get(bone, _base(bone))


def pose_ok(bone: str) -> Quat:
    """ХОРОШО: большой палец вверх, рука от груди."""
    arm = _arm("right", lift=25.0, out=8.0, elbow=70.0)
    pose = _merge(arm, {"rightThumbProximal": quat_from_euler(0.0, 0.0, -math.radians(25))})
    return pose.get(bone, _base(bone))


def pose_bad(bone: str) -> Quat:
    """ПЛОХО: рука у груди, кисть отталкивает вниз (фаза)."""
    arm = _arm("right", lift=30.0, out=8.0, elbow=65.0)
    return _merge(arm, {}).get(bone, _base(bone))


def pose_stop(bone: str) -> Quat:
    """СТОП: ладонь выставляется вперёд."""
    arm = _arm("right", lift=60.0, out=10.0, elbow=45.0)
    return _merge(arm, {}).get(bone, _base(bone))


def pose_question(bone: str) -> Quat:
    """ВОПРОС: поднятая ладонь и наклон головы."""
    arm = _arm("right", lift=65.0, out=12.0, elbow=40.0)
    return _merge(arm, {}).get(bone, _base(bone))


@dataclass(frozen=True)
class Gesture:
    """Одна запись в файле: имя-глосса, длительность и базовая поза."""

    name: str
    duration_s: float
    pose: Pose
    # Дополнительные повороты «поверх» позы, зависящие от фазы (движение).
    motion: Callable[[str, float], Quat] | None = None
    settle_s: float = 0.35


GESTURES: tuple[Gesture, ...] = (
    Gesture("ПРИВЕТ", 2.4, pose_wave, motion=lambda b, p: _wave_motion(b, p)),
    Gesture("ПОКА", 2.2, pose_bye, motion=lambda b, p: _wave_motion(b, p, wide=True)),
    Gesture("ДА", 1.6, pose_yes, motion=lambda b, p: _nod(b, p)),
    Gesture("НЕТ", 1.8, pose_no, motion=lambda b, p: _shake(b, p)),
    Gesture("СПАСИБО", 1.8, pose_thanks, motion=lambda b, p: _bow(b, p)),
    Gesture("ПОЖАЛУЙСТА", 2.4, pose_please, motion=lambda b, p: _circle(b, p)),
    Gesture("ХОРОШО", 1.8, pose_ok, motion=lambda b, p: _push(b, p)),
    Gesture("ПЛОХО", 1.8, pose_bad, motion=lambda b, p: _push_down(b, p)),
    Gesture("СТОП", 1.6, pose_stop, motion=lambda b, p: _push(b, p)),
    Gesture("ВОПРОС", 2.0, pose_question, motion=lambda b, p: _tilt(b, p)),
)


# --- Движение поверх позы (фаза p: 0..1) ----------------------------------


def _wave_motion(bone: str, p: float, *, wide: bool = False) -> Quat:
    amp = 40.0 if wide else 32.0
    if bone == "rightHand":
        return quat_from_euler(math.radians(amp) * sway(p, 2), 0.0, 0.0)
    if bone == "head":
        return quat_from_euler(0.0, 0.0, math.radians(5) * sway(p, 1))
    return IDENTITY


def _nod(bone: str, p: float) -> Quat:
    if bone == "head":
        return quat_from_euler(math.radians(16) * sway(p, 2), 0.0, 0.0)
    if bone == "neck":
        return quat_from_euler(math.radians(7) * sway(p, 2), 0.0, 0.0)
    return IDENTITY


def _shake(bone: str, p: float) -> Quat:
    if bone == "head":
        return quat_from_euler(0.0, math.radians(20) * sway(p, 2), 0.0)
    if bone == "neck":
        return quat_from_euler(0.0, math.radians(7) * sway(p, 2), 0.0)
    return IDENTITY


def _bow(bone: str, p: float) -> Quat:
    amount = math.radians(9) * ease(min(1.0, p * 2))
    if bone in ("spine", "chest"):
        return quat_from_euler(amount, 0.0, 0.0)
    if bone == "head":
        return quat_from_euler(amount, 0.0, 0.0)
    return IDENTITY


def _circle(bone: str, p: float) -> Quat:
    angle = 2 * math.pi * p
    if bone == "rightHand":
        return quat_from_euler(
            math.radians(22) * math.sin(angle), 0.0, math.radians(22) * math.cos(angle)
        )
    if bone == "head":
        return quat_from_euler(0.0, 0.0, math.radians(3) * math.sin(angle))
    return IDENTITY


def _push(bone: str, p: float) -> Quat:
    amount = math.radians(14) * ease(min(1.0, p * 2))
    if bone == "rightHand":
        return quat_from_euler(-amount, 0.0, 0.0)
    if bone == "head":
        return quat_from_euler(amount * 0.4, 0.0, 0.0)
    return IDENTITY


def _push_down(bone: str, p: float) -> Quat:
    amount = math.radians(22) * ease(min(1.0, p * 2))
    if bone == "rightHand":
        return quat_from_euler(amount, 0.0, 0.0)
    if bone == "head":
        return quat_from_euler(-math.radians(6) * ease(min(1.0, p * 2)), 0.0, 0.0)
    return IDENTITY


def _tilt(bone: str, p: float) -> Quat:
    if bone == "head":
        return quat_from_euler(0.0, 0.0, math.radians(12) * ease(min(1.0, p * 2)))
    return IDENTITY


# --- Сборка файла ---------------------------------------------------------


def gesture_phase(gesture: Gesture, t: float) -> tuple[float, float]:
    """Фазы (blend, inner) для момента t.

    ``blend`` — плавный вход/выход от «рук вниз» к позе жеста (0 — покой,
    1 — активная поза), ``inner`` — прогресс движения 0..1.
    """
    duration = gesture.duration_s
    settle = min(gesture.settle_s, duration / 3)
    if t <= 0 or t >= duration:
        return 0.0, 0.0
    if t < settle:
        blend = ease(t / settle)
    elif t > duration - settle:
        blend = ease((duration - t) / settle)
    else:
        blend = 1.0
    inner = (t - settle) / max(1e-6, duration - 2 * settle)
    inner = min(1.0, max(0.0, inner))
    return blend, inner


def slerp(a: Quat, b: Quat, t: float) -> Quat:
    """Сферическая интерполяция кватернионов (кратчайший путь)."""
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]
    if dot < 0:
        b = (-b[0], -b[1], -b[2], -b[3])
        dot = -dot
    if dot > 0.9995:
        return quat_normalize(
            (
                a[0] + (b[0] - a[0]) * t,
                a[1] + (b[1] - a[1]) * t,
                a[2] + (b[2] - a[2]) * t,
                a[3] + (b[3] - a[3]) * t,
            )
        )
    theta = math.acos(max(-1.0, min(1.0, dot)))
    sin_theta = math.sin(theta)
    wa = math.sin((1 - t) * theta) / sin_theta
    wb = math.sin(t * theta) / sin_theta
    return quat_normalize(
        (
            a[0] * wa + b[0] * wb,
            a[1] * wa + b[1] * wb,
            a[2] * wa + b[2] * wb,
            a[3] * wa + b[3] * wb,
        )
    )


def bone_quaternion(gesture: Gesture, bone: str, t: float) -> Quat:
    """Поворот кости: от «рук вниз» к позе жеста и обратно."""
    blend, inner = gesture_phase(gesture, t)
    target = gesture.pose(bone)
    if gesture.motion is not None:
        target = quat_mul(target, gesture.motion(bone, inner))
    base = _base(bone)
    if blend >= 1.0:
        return target
    if blend <= 0.0:
        return base
    return slerp(base, target, blend)


def build_vrma() -> bytes:
    """Собрать GLB с несколькими именованными VRMA-анимациями."""
    accessors: list[dict] = []
    buffer_views: list[dict] = []
    blob = bytearray()

    def add_buffer_view(data: bytes) -> int:
        offset = len(blob)
        blob.extend(data)
        while len(blob) % 4:
            blob.append(0)
        buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data)})
        return len(buffer_views) - 1

    def add_accessor(
        view: int, count: int, type_: str, *, times: bool = False, tmax: float = 0.0
    ) -> int:
        acc = {"bufferView": view, "componentType": 5126, "count": count, "type": type_}
        if times:
            acc["min"] = [0.0]
            acc["max"] = [tmax]
        accessors.append(acc)
        return len(accessors) - 1

    animations: list[dict] = []
    for gesture in GESTURES:
        frames = int(gesture.duration_s * FPS) + 1
        times = [i / FPS for i in range(frames)]
        time_view = add_buffer_view(struct.pack(f"<{frames}f", *times))
        time_acc = add_accessor(time_view, frames, "SCALAR", times=True, tmax=times[-1])

        samplers: list[dict] = []
        channels: list[dict] = []
        for bone in HUMANOID_BONES:
            values: list[float] = []
            for t in times:
                values.extend(bone_quaternion(gesture, bone, t))
            view = add_buffer_view(struct.pack(f"<{len(values)}f", *values))
            acc = add_accessor(view, frames, "VEC4")
            samplers.append({"input": time_acc, "output": acc, "interpolation": "LINEAR"})
            channels.append(
                {
                    "sampler": len(samplers) - 1,
                    "target": {"node": BONE_NODE[bone], "path": "rotation"},
                }
            )

        # Бёдрам задаём позицию: VRMA ожидает высоту бёдер в rest-позиции.
        trans_values = [0.0, 0.95, 0.0] * frames
        trans_view = add_buffer_view(struct.pack(f"<{len(trans_values)}f", *trans_values))
        trans_acc = add_accessor(trans_view, frames, "VEC3")
        samplers.append({"input": time_acc, "output": trans_acc, "interpolation": "LINEAR"})
        channels.append(
            {
                "sampler": len(samplers) - 1,
                "target": {"node": BONE_NODE["hips"], "path": "translation"},
            }
        )

        animations.append({"name": gesture.name, "samplers": samplers, "channels": channels})

    nodes = []
    for name in HUMANOID_BONES:
        node = {"name": name}
        if name == "hips":
            node["translation"] = [0.0, 0.95, 0.0]
        nodes.append(node)

    human_bones = {name: {"node": BONE_NODE[name]} for name in HUMANOID_BONES}

    payload = {
        "asset": {"version": "2.0", "generator": "make_gestures_vrma.py"},
        "scene": 0,
        "scenes": [{"nodes": list(BONE_NODE.values())}],
        "nodes": nodes,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(blob)}],
        "animations": animations,
        "extensionsUsed": ["VRMC_vrm_animation"],
        "extensions": {
            "VRMC_vrm_animation": {
                "specVersion": "1.0",
                "humanoid": {"humanBones": human_bones},
            }
        },
    }

    return pack_glb(payload, bytes(blob))


def pack_glb(payload: dict, bin_chunk: bytes) -> bytes:
    """Собрать GLB: заголовок, JSON-чанк, BIN-чанк."""
    json_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((-len(json_bytes)) % 4)
    bin_chunk += b"\x00" * ((-len(bin_chunk)) % 4)

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_chunk)
    out = bytearray()
    out += b"glTF"
    out += struct.pack("<II", 2, total)
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A)  # 'JSON'
    out += json_bytes
    out += struct.pack("<II", len(bin_chunk), 0x004E4942)  # 'BIN\0'
    out += bin_chunk
    return bytes(out)


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "assets" / "animations" / "gestures.vrma"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_vrma())
    names = ", ".join(gesture.name for gesture in GESTURES)
    print(f"Готово: {target} ({target.stat().st_size} байт)")
    print(f"Записей: {len(GESTURES)} — {names}")


if __name__ == "__main__":
    main()
