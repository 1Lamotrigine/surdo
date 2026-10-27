/**
 * Блендинг кадров ретаргета (C4) — чистая функция без Three.js.
 *
 * Crossfade между клипами (ТЗ 5.4) склеивает два кадра ретаргета: соседние
 * кости получают взвешенную сумму углов, мимика — взвешенную сумму весов. Те же
 * функции смешивают клип со **нейтральной позой** в начале и конце каждого
 * клипа (FR-12): нейтраль — это пустой кадр (`neutralFrame`), поэтому переход к
 * ней всегда идёт через те же `lerpFrames`/`ease`.
 *
 * Работать с числами (`RetargetedFrame`), а не с кватернионами VRM, выгодно:
 * ретаргет уже посчитан, а `vrm-rig.ts` принимает именно эти числа. Плавность
 * достигается тем, что смешанные углы монотонно меняются от кадра A к кадру B.
 */

import type { BonePose, FingerPose, RetargetedFace, RetargetedFrame } from "./retarget";
import type { Vec3 } from "./one-euro";

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

/** Слить две позы туловища: отсутствующая сторона считается нейтральной (нули). */
function lerpBones(a: BonePose | null, b: BonePose | null, t: number): BonePose | null {
  if (!a && !b) return null;
  const from = a;
  const to = b;
  const bone = (get: (pose: BonePose) => Vec3): Vec3 =>
    lerpVec3(from ? get(from) : ZERO, to ? get(to) : ZERO, t);
  const hips = (key: "position" | "rotation"): Vec3 =>
    lerpVec3(from?.Hips?.[key] ?? ZERO, to?.Hips?.[key] ?? ZERO, t);
  return {
    RightUpperArm: bone((p) => p.RightUpperArm),
    RightLowerArm: bone((p) => p.RightLowerArm),
    LeftUpperArm: bone((p) => p.LeftUpperArm),
    LeftLowerArm: bone((p) => p.LeftLowerArm),
    RightHand: bone((p) => p.RightHand),
    LeftHand: bone((p) => p.LeftHand),
    RightUpperLeg: bone((p) => p.RightUpperLeg),
    RightLowerLeg: bone((p) => p.RightLowerLeg),
    LeftUpperLeg: bone((p) => p.LeftUpperLeg),
    LeftLowerLeg: bone((p) => p.LeftLowerLeg),
    Hips: { position: hips("position"), rotation: hips("rotation") },
    Spine: bone((p) => p.Spine),
  };
}

/** Слить две позы пальцев: союз ключей, отсутствующий считается нейтральным. */
function lerpFingers(a: FingerPose | null, b: FingerPose | null, t: number): FingerPose | null {
  if (!a && !b) return null;
  const keys = new Set([...Object.keys(a ?? {}), ...Object.keys(b ?? {})]);
  const merged: FingerPose = {};
  for (const key of keys) {
    merged[key] = lerpVec3(a?.[key] ?? ZERO, b?.[key] ?? ZERO, t);
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
  return {
    hasPose: a.hasPose || b.hasPose,
    bones: lerpBones(a.bones, b.bones, k),
    leftFingers: lerpFingers(a.leftFingers, b.leftFingers, k),
    rightFingers: lerpFingers(a.rightFingers, b.rightFingers, k),
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
