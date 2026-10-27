/**
 * Применение позы ретаргета к VRM (C3).
 *
 * Здесь Three.js и `@pixiv/three-vrm`: модуль берёт результат `retargetFrame`
 * (числа) и раскладывает его по костям humanoid и выражениям модели. Логика
 * ретаргета отделена (`retarget.ts`), поэтому смену аватара или улучшение углов
 * можно делать тут, не трогая формат клипа (ТЗ 5.4).
 *
 * Углы Kalidokit — относительные повороты суставов; VRM-кости имеют свою
 * ориентацию, поэтому для плеч/локтей/кистей применяется поворот, для головы —
 * с ограничением, а мимика идёт через выражения (blink, mouth).
 */

import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";

import type { BonePose, FingerPose, RetargetedFace, RetargetedFrame } from "./retarget";
import type { Vec3 } from "./one-euro";

/** Имя кости VRM (значения из `VRMHumanBoneName`). */
type VrmBone =
  | "hips"
  | "spine"
  | "head"
  | "neck"
  | "leftUpperArm"
  | "leftLowerArm"
  | "leftHand"
  | "rightUpperArm"
  | "rightLowerArm"
  | "rightHand"
  | "leftUpperLeg"
  | "leftLowerLeg"
  | "rightUpperLeg"
  | "rightLowerLeg";

/** Кости рук и ног туловища: имя ретаргета → имя кости VRM. */
const BONE_MAP: Record<string, VrmBone> = {
  RightUpperArm: "rightUpperArm",
  RightLowerArm: "rightLowerArm",
  RightHand: "rightHand",
  LeftUpperArm: "leftUpperArm",
  LeftLowerArm: "leftLowerArm",
  LeftHand: "leftHand",
  RightUpperLeg: "rightUpperLeg",
  RightLowerLeg: "rightLowerLeg",
  LeftUpperLeg: "leftUpperLeg",
  LeftLowerLeg: "leftLowerLeg",
  Spine: "spine",
};

/** Пальцы: префикс имени ретаргета → префикс костей VRM. */
const FINGER_SIDES = ["Left", "Right"] as const;

/** Сегменты пальцев: имя ретаргета → имя сегмента VRM. */
const FINGER_SEGMENTS: Record<string, string> = {
  Proximal: "Proximal",
  Intermediate: "Intermediate",
  Distal: "Distal",
};

/** Особый случай большого пальца: у VRM есть Metacarpal до Proximal. */
const THUMB_SEGMENTS: Record<string, string> = {
  Proximal: "Proximal",
  Intermediate: "Metacarpal",
  Distal: "Distal",
};

/** Свежее состояние костей в начале воспроизведения (без накопления). */
const _euler = new THREE.Euler();
const _quat = new THREE.Quaternion();

/** Ограничение угла: защищает от вывернутых суставов на «шумных» кадрах. */
function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Повернуть кость VRM по углам ретаргета (порядок XYZ, как у Kalidokit). */
function applyBoneRotation(vrm: VRM, name: VrmBone, rotation: Vec3, clampRad = Math.PI): void {
  const bone = vrm.humanoid.getNormalizedBoneNode(name);
  if (!bone) return;

  _euler.set(
    clamp(rotation.x, -clampRad, clampRad),
    clamp(rotation.y, -clampRad, clampRad),
    clamp(rotation.z, -clampRad, clampRad),
    "XYZ",
  );
  _quat.setFromEuler(_euler);
  bone.quaternion.copy(_quat);
}

/** Применить позы туловища и рук. */
function applyBones(vrm: VRM, bones: BonePose): void {
  for (const [source, target] of Object.entries(BONE_MAP)) {
    const rotation = bones[source as keyof BonePose] as Vec3 | undefined;
    if (!rotation) continue;
    applyBoneRotation(vrm, target, rotation);
  }

  // Бедра: смещение центра тела (небольшое, чтобы аватар не «улетал»).
  const hips = vrm.humanoid.getNormalizedBoneNode("hips");
  if (hips) {
    hips.position.set(bones.Hips.position.x * 0.1, bones.Hips.position.y * 0.1, 0);
  }
}

/** Применить позы пальцев одной кисти. */
function applyFingers(vrm: VRM, side: (typeof FINGER_SIDES)[number], fingers: FingerPose): void {
  for (const [joint, rotation] of Object.entries(fingers)) {
    if (!joint.startsWith(side)) continue;

    // Пример: RightIndexProximal → палец=Index, сегмент=Proximal.
    const rest = joint.slice(side.length);
    const finger = rest.replace(/(Proximal|Intermediate|Distal)$/, "");
    const segment = rest.slice(finger.length);
    const segments = finger === "Thumb" ? THUMB_SEGMENTS : FINGER_SEGMENTS;
    const vrmSegment = segments[segment];
    if (!finger || !vrmSegment) continue;

    // Пальцы сгибаются по z; x/y для них в Kalidokit нулевые или малы.
    const boneName = `${side[0].toLowerCase()}${side.slice(1)}${finger}${vrmSegment}` as VrmBone;
    applyBoneRotation(vrm, boneName, rotation, Math.PI / 2);
  }
}

/**
 * Мимика: взгляд вперёд, мигание, форма рта.
 * Kalidokit отдаёт «раскрытость» в условных единицах; преобразуем в вес 0..1.
 */
function applyFace(vrm: VRM, face: RetargetedFace): void {
  const expressions = vrm.expressionManager;
  if (!expressions) return;

  const blink = clamp(1 - face.eye.l, 0, 1);
  const blinkOther = clamp(1 - face.eye.r, 0, 1);
  expressions.setValue("blinkLeft", blinkOther);
  expressions.setValue("blinkRight", blink);

  // Форма рта: A/E/I/O/U в ответе Kalidokit — веса губ.
  expressions.setValue("aa", clamp(face.mouth.shape.A, 0, 1));
  expressions.setValue("ee", clamp(face.mouth.shape.E, 0, 1));
  expressions.setValue("ih", clamp(face.mouth.shape.I, 0, 1));
  expressions.setValue("oh", clamp(face.mouth.shape.O, 0, 1));
  expressions.setValue("ou", clamp(face.mouth.shape.U, 0, 1));

  // Поворот головы: наклон и поворот из углов Kalidokit.
  applyBoneRotation(vrm, "head", face.head, Math.PI / 3);
  applyBoneRotation(vrm, "neck", { x: face.head.x * 0.5, y: face.head.y * 0.5, z: 0 }, Math.PI / 4);
}

/**
 * Применить кадр ретаргета к модели. Без позы (нет скелета) кости не трогаются,
 * но пальцы и лицо применяются, если они есть — так короткие клипы не «замирают»
 * в промежуточной позе.
 */
export function applyRetargetedFrame(vrm: VRM, frame: RetargetedFrame): void {
  if (frame.bones) applyBones(vrm, frame.bones);
  if (frame.leftFingers) applyFingers(vrm, "Left", frame.leftFingers);
  if (frame.rightFingers) applyFingers(vrm, "Right", frame.rightFingers);
  if (frame.face) applyFace(vrm, frame.face);
}

/**
 * Вернуть модель в нейтральную позу: rest pose и нулевая мимика.
 * Используется между клипами (ТЗ 5.4: нейтральная поза в начале и конце).
 */
export function resetToNeutral(vrm: VRM): void {
  vrm.humanoid.setNormalizedPose(vrm.humanoid.normalizedRestPose);

  const expressions = vrm.expressionManager;
  if (!expressions) return;
  for (const name of ["blinkLeft", "blinkRight", "aa", "ee", "ih", "oh", "ou"]) {
    expressions.setValue(name, 0);
  }
}
