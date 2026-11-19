/**
 * Блендинг кадров ретаргета (C4) — чистая функция без Three.js.
 *
 * Crossfade между клипами (ТЗ 5.4) склеивает два кадра ретаргета: соседние
 * кости интерполируются по углам или кватернионам, мимика — по весам. Те же
 * функции смешивают клип со **нейтральной позой** в начале и конце каждого
 * клипа (FR-12): нейтраль — это пустой кадр (`neutralFrame`), поэтому переход к
 * ней всегда идёт через те же `lerpFrames`/`ease`.
 *
 */

import { Euler, Quaternion } from "three";

import type { BonePose, FingerPose, RetargetedFace, RetargetedFrame } from "./retarget";
import type { Vec3 } from "./one-euro";
import { RELAXED_ARM_ROTATIONS } from "./vrm-rig";

/** Пустой кадр ретаргета: соответствует нейтральной позе VRM. */
export function neutralFrame(): RetargetedFrame {
  return {
    hasPose: false,
    bones: null,
    leftFingers: null,
    rightFingers: null,
    face: null,
  };
}

/** Плавная функция сглаживания (smoothstep) для crossfade. */
export function ease(t: number): number {
  const x = clamp01(t);
  return x * x * (3 - 2 * x);
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

/** Взвешенная сумма двух векторов: `a*(1-t) + b*t`. */
function lerpVec3(a: Vec3, b: Vec3, t: number): Vec3 {
  return {
    x: a.x + (b.x - a.x) * t,
    y: a.y + (b.y - a.y) * t,
    z: a.z + (b.z - a.z) * t,
  };
}

/** Нулевой вектор (нейтральное значение кости и пальца). */
const ZERO: Vec3 = { x: 0, y: 0, z: 0 };

/** Кватернионы проводят пространственный поворот по кратчайшей дуге. */
function slerpRotation(a: Vec3, b: Vec3, t: number): Vec3 {
  const from = new Quaternion().setFromEuler(new Euler(a.x, a.y, a.z));
  const to = new Quaternion().setFromEuler(new Euler(b.x, b.y, b.z));
  const { x, y, z } = new Euler().setFromQuaternion(from.slerp(to, t));
  return { x, y, z };
}

function lerpBones(a: BonePose | null, b: BonePose | null, t: number, world: boolean): BonePose | null {
  if (!a && !b) return null;
  const mix = world ? slerpRotation : lerpVec3;
  const bone = (name: Exclude<keyof BonePose, "Hips">): Vec3 => {
    const neutral = world ? RELAXED_ARM_ROTATIONS[name] ?? ZERO : ZERO;
    return mix(a?.[name] ?? neutral, b?.[name] ?? neutral, t);
  };
  return {
    RightUpperArm: bone("RightUpperArm"),
    RightLowerArm: bone("RightLowerArm"),
    LeftUpperArm: bone("LeftUpperArm"),
    LeftLowerArm: bone("LeftLowerArm"),
    RightHand: bone("RightHand"),
    LeftHand: bone("LeftHand"),
    RightUpperLeg: bone("RightUpperLeg"),
    RightLowerLeg: bone("RightLowerLeg"),
    LeftUpperLeg: bone("LeftUpperLeg"),
    LeftLowerLeg: bone("LeftLowerLeg"),
    Hips: {
      position: lerpVec3(a?.Hips.position ?? ZERO, b?.Hips.position ?? ZERO, t),
      rotation: mix(a?.Hips.rotation ?? ZERO, b?.Hips.rotation ?? ZERO, t),
    },
    Spine: bone("Spine"),
  };
}

function lerpFingers(a: FingerPose | null, b: FingerPose | null, t: number, world: boolean): FingerPose | null {
  if (!a && !b) return null;
  const mix = world ? slerpRotation : lerpVec3;
  const keys = new Set([...Object.keys(a ?? {}), ...Object.keys(b ?? {})]);
  const merged: FingerPose = {};
  for (const key of keys) {
    merged[key] = mix(a?.[key] ?? ZERO, b?.[key] ?? ZERO, t);
  }
  return merged;
}

/** Слить два лица: отсутствующая мимика считается нейтральной (нули). */
function lerpFace(a: RetargetedFace | null, b: RetargetedFace | null, t: number): RetargetedFace | null {
  if (!a && !b) return null;
  const v = (get: (face: RetargetedFace) => number): number =>
    (a ? get(a) : 0) + ((b ? get(b) : 0) - (a ? get(a) : 0)) * t;
  const vec = (get: (face: RetargetedFace) => Vec3): Vec3 =>
    lerpVec3(a ? get(a) : ZERO, b ? get(b) : ZERO, t);
  return {
    head: vec((f) => f.head),
    eye: { l: v((f) => f.eye.l), r: v((f) => f.eye.r) },
    brow: v((f) => f.brow),
    pupil: vec((f) => ({ x: f.pupil.x, y: f.pupil.y, z: 0 })),
    mouth: {
      x: v((f) => f.mouth.x),
      y: v((f) => f.mouth.y),
      shape: {
        A: v((f) => f.mouth.shape.A),
        E: v((f) => f.mouth.shape.E),
        I: v((f) => f.mouth.shape.I),
        O: v((f) => f.mouth.shape.O),
        U: v((f) => f.mouth.shape.U),
      },
    },
  };
}

/**
 * Смешать два кадра ретаргета: `t = 0` — кадр `a`, `t = 1` — кадр `b`.
 * `t` зажимается в [0, 1]; для crossfade передавайте уже сглаженное `ease(t)`.
 *
 * Отсутствующая часть кадра считается нейтральной (нули), поэтому смешение
 * кадра с `neutralFrame()` даёт явные нулевые углы — поза действительно уходит
 * в нейтраль, а не «застывает» (важно для ухода в нейтраль в конце очереди).
 */
export function lerpFrames(a: RetargetedFrame, b: RetargetedFrame, t: number): RetargetedFrame {
  const k = clamp01(t);
  const world = Boolean(a.world || b.world);
  return {
    ...(world ? { world } : {}),
    hasPose: a.hasPose || b.hasPose,
    bones: lerpBones(a.bones, b.bones, k, world),
    leftFingers: lerpFingers(a.leftFingers, b.leftFingers, k, world),
    rightFingers: lerpFingers(a.rightFingers, b.rightFingers, k, world),
    face: lerpFace(a.face, b.face, k),
  };
}

/**
 * Crossfade между двумя кадрами с плавным сглаживанием по времени:
 * обёртка над `lerpFrames`, принимающая прогресс 0..1 и применяющая `ease`.
 */
export function crossfade(a: RetargetedFrame, b: RetargetedFrame, progress: number): RetargetedFrame {
  return lerpFrames(a, b, ease(progress));
}

/** Плавно вернуть кадр в нейтральную позу: `t = 0` — кадр, `t = 1` — нейтраль. */
export function fadeToNeutral(frame: RetargetedFrame, progress: number): RetargetedFrame {
  return lerpFrames(frame, neutralFrame(), ease(progress));
}
