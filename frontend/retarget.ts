/**
 * Ретаргет landmarks клипа на позы скелета через Kalidokit (C3).
 *
 * Модуль — чистая функция над данными: на вход раскодированный клип (C2) и
 * номер кадра, на выходе позы костей в радианах (числа, без Three.js). Так
 * результат тестируется в vitest, а применение к VRM живёт отдельно
 * (`vrm-rig.ts`) и может быть заменено (ТЗ 5.4: «улучшить ретаргет без
 * перезаписи словаря»).
 *
 * Формат входа — MediaPipe Holistic: поза (33 точки), кисти (21), лицо (468),
 * каждое число `{x, y, z}` в диапазоне 0..1 (y вниз). Именно в таком виде
 * landmarks и хранятся в клипе, поэтому кадр отдаётся в Kalidokit напрямую.
 */

import { Face, Hand, Pose } from "kalidokit";

import type { DecodedClip } from "./clip";
import type { Vec3 } from "./one-euro";

/** Точка в формате MediaPipe: координаты и (для позы) видимость. */
export type Landmark = Vec3 & { visibility?: number };

/** Позы костей туловища и рук после ретаргета (радианы). */
export type BonePose = {
  RightUpperArm: Vec3;
  RightLowerArm: Vec3;
  LeftUpperArm: Vec3;
  LeftLowerArm: Vec3;
  RightHand: Vec3;
  LeftHand: Vec3;
  RightUpperLeg: Vec3;
  RightLowerLeg: Vec3;
  LeftUpperLeg: Vec3;
  LeftLowerLeg: Vec3;
  Hips: { position: Vec3; rotation: Vec3 };
  Spine: Vec3;
};

/** Позы костей пальцев: имя — сторона + палец + сегмент. */
export type FingerPose = Record<string, Vec3>;

/** Результат ретаргета одного кадра. */
export type RetargetedFrame = {
  /** Найден ли скелет в кадре (если нет — кадр пропускается). */
  hasPose: boolean;
  /** Позы туловища и рук. */
  bones: BonePose | null;
  /** Позы пальцев левой кисти. */
  leftFingers: FingerPose | null;
  /** Позы пальцев правой кисти. */
  rightFingers: FingerPose | null;
  /** Лицо (мимика, взгляд) или `null`, если лица в клипе нет. */
  face: RetargetedFace | null;
};

/** Мимика и поворот головы (подмножество ответа Kalidokit). */
export type RetargetedFace = {
  head: Vec3;
  eye: { l: number; r: number };
  brow: number;
  pupil: { x: number; y: number };
  mouth: { x: number; y: number; shape: { A: number; E: number; I: number; O: number; U: number } };
};

const BONE_NAMES: (keyof BonePose)[] = [
  "RightUpperArm",
  "RightLowerArm",
  "LeftUpperArm",
  "LeftLowerArm",
  "RightHand",
  "LeftHand",
  "RightUpperLeg",
  "RightLowerLeg",
  "LeftUpperLeg",
  "LeftLowerLeg",
  "Spine",
];

/** Имена частей клипа, которые понимает ретаргет. */
export type ClipParts = {
  pose?: Landmark[];
  hand_l?: Landmark[];
  hand_r?: Landmark[];
  face?: Landmark[];
};

/** Достать точки части кадра из `decoded.data` по её смещению. */
function readPart(frame: number, offsets: Record<string, { start: number; count: number }>, part: string, decoded: DecodedClip): Landmark[] | undefined {
  const offset = offsets[part];
  if (!offset) return undefined;

  const points: Landmark[] = [];
  for (let i = 0; i < offset.count; i += 1) {
    const point = offset.start + i;
    const base = (frame * decoded.points + point) * decoded.components;
    const landmark: Landmark = {
      x: decoded.data[base],
      y: decoded.data[base + 1],
      z: decoded.data[base + 2],
    };
    // Видимость в формате клипа не хранится: поза без visibility Kalidokit
    // трактует как «на экране» (проверка offscreen смотрит на visibility ?? 0 и
    // сбросила бы руки). Ставим 1, чтобы ретаргет не гасил руки.
    if (part === "pose") landmark.visibility = 1;
    points.push(landmark);
  }
  return points;
}

/** Разбить кадр клипа на части, которые понимает Kalidokit. */
export function splitFrame(decoded: DecodedClip, frame: number): ClipParts {
  const parts: ClipParts = {};
  for (const name of ["pose", "hand_l", "hand_r", "face"]) {
    const points = readPart(frame, decoded.offsets, name, decoded);
    if (points) {
      parts[name as keyof ClipParts] = points;
    }
  }
  return parts;
}

/** Привести `Vector`/`Euler` Kalidokit к простому `{x, y, z}`. */
function toVec3(value: unknown): Vec3 {
  const v = value as { x?: number; y?: number; z?: number } | null;
  return { x: v?.x ?? 0, y: v?.y ?? 0, z: v?.z ?? 0 };
}

/** Собрать позы пальцев из ответа `Hand.solve`. */
function fingersToPose(result: Record<string, Vec3> | undefined): FingerPose | null {
  if (!result) return null;
  const pose: FingerPose = {};
  for (const [name, value] of Object.entries(result)) {
    pose[name] = toVec3(value);
  }
  return pose;
}

/** Ретаргет уже разобранного кадра (для сглаженных landmarks). */
export function retargetParts(parts: ClipParts): RetargetedFrame {
  let bones: BonePose | null = null;
  if (parts.pose && parts.pose.length >= 25) {
    // Kalidokit ждёт 3D-позу; для 2D используем те же точки без z-масштаба.
    const solved = Pose.solve(parts.pose, parts.pose, { runtime: "mediapipe", enableLegs: false });
    if (solved) {
      bones = {
        RightUpperArm: toVec3(solved.RightUpperArm),
        RightLowerArm: toVec3(solved.RightLowerArm),
        LeftUpperArm: toVec3(solved.LeftUpperArm),
        LeftLowerArm: toVec3(solved.LeftLowerArm),
        RightHand: toVec3(solved.RightHand),
        LeftHand: toVec3(solved.LeftHand),
        RightUpperLeg: toVec3(solved.RightUpperLeg),
        RightLowerLeg: toVec3(solved.RightLowerLeg),
        LeftUpperLeg: toVec3(solved.LeftUpperLeg),
        LeftLowerLeg: toVec3(solved.LeftLowerLeg),
        Hips: {
          position: toVec3(solved.Hips?.position),
          rotation: toVec3(solved.Hips?.rotation),
        },
        Spine: toVec3(solved.Spine),
      };
    }
  }

  const leftFingers = parts.hand_l ? fingersToPose(Hand.solve(parts.hand_l, "Left")) : null;
  const rightFingers = parts.hand_r ? fingersToPose(Hand.solve(parts.hand_r, "Right")) : null;

  let face: RetargetedFace | null = null;
  if (parts.face) {
    const solved = Face.solve(parts.face, { runtime: "mediapipe", smoothBlink: true });
    if (solved) {
      face = {
        head: toVec3(solved.head),
        eye: { l: solved.eye.l, r: solved.eye.r },
        brow: solved.brow,
        pupil: { x: solved.pupil.x, y: solved.pupil.y },
        mouth: {
          x: solved.mouth.x,
          y: solved.mouth.y,
          shape: { ...solved.mouth.shape },
        },
      };
    }
  }

  return {
    hasPose: bones !== null,
    bones,
    leftFingers,
    rightFingers,
    face,
  };
}

/** Ретаргет одного кадра: landsmarks → позы костей. */
export function retargetFrame(decoded: DecodedClip, frame: number): RetargetedFrame {
  return retargetParts(splitFrame(decoded, frame));
}

/** Имена костей скелета, которые ретаргет умеет отдавать. */
export { BONE_NAMES };
