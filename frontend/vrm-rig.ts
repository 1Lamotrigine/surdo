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

/**
 * Rest-позиция бёдер из нормализованного рига.
 *
 * Узел `hips` нормализованного рига стоит на **абсолютной** мировой высоте
 * (~1.04 в единицах модели), а не в начале координат. Значение берётся из
 * `normalizedRestPose`, поэтому не зависит от того, в какой позе сейчас модель.
 */
function hipsRestPosition(vrm: VRM): Vec3 | null {
  const rest = vrm.humanoid.normalizedRestPose?.hips?.position as number[] | undefined;
  if (!rest) return null;
  return { x: rest[0], y: rest[1], z: rest[2] };
}

/** Применить позы туловища и рук. */
function applyBones(vrm: VRM, bones: BonePose): void {
  for (const [source, target] of Object.entries(BONE_MAP)) {
    const rotation = bones[source as keyof BonePose] as Vec3 | undefined;
    if (!rotation) continue;
    applyBoneRotation(vrm, target, rotation);
  }

  // Бедра: Kalidokit отдаёт *смещение* центра тела, а не абсолютную позицию.
  // Писать его вместо rest-высоты нельзя: модель падает в начало координат
  // (≈1.04 вниз) и из кадра видна только голова.
  const hips = vrm.humanoid.getNormalizedBoneNode("hips");
  if (hips) {
    const rest = hipsRestPosition(vrm);
    // Смещение малое: x в Kalidokit доходит до ±0.5, поэтому масштаб 0.1.
    const dx = bones.Hips.position.x * 0.1;
    const dy = bones.Hips.position.y * 0.1;
    if (rest) {
      hips.position.set(rest.x + dx, rest.y + dy, rest.z);
    } else {
      // Модель без `normalizedRestPose`: сохраняем текущую высоту как опору.
      hips.position.x += dx;
      hips.position.y += dy;
    }
    const rotation = bones.Hips.rotation;
    _euler.set(
      clamp(rotation.x, -Math.PI, Math.PI),
      clamp(rotation.y, -Math.PI, Math.PI),
      clamp(rotation.z, -Math.PI, Math.PI),
      "XYZ",
    );
    _quat.setFromEuler(_euler);
    hips.quaternion.copy(_quat);
  }
}

/** Применить позы пальцев одной кисти. */
function applyFingers(vrm: VRM, side: (typeof FINGER_SIDES)[number], fingers: FingerPose, limit: number): void {
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
    applyBoneRotation(vrm, boneName, rotation, limit);
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
  const fingerLimit = frame.world ? Math.PI : Math.PI / 2;
  if (frame.leftFingers) applyFingers(vrm, "Left", frame.leftFingers, fingerLimit);
  if (frame.rightFingers) applyFingers(vrm, "Right", frame.rightFingers, fingerLimit);
  if (frame.face) applyFace(vrm, frame.face);
}

/**
 * Угол наклона плеча из T-позы в положение «руки вниз» и лёгкий изгиб локтя.
 *
 * У VRM rest pose — руки в стороны (T-поза). Без этих поворотов аватар стоит
 * «буквой Т» и до первой фразы, и между жестами. Значения подобраны под
 * VRM-модель проекта (руки идут вниз вдоль тела, кисти чуть от корпуса).
 */
const ARM_DOWN = THREE.MathUtils.degToRad(80);
const ELBOW_RELAX = THREE.MathUtils.degToRad(15);
export const RELAXED_ARM_ROTATIONS: Partial<Record<keyof BonePose, Vec3>> = {
  RightUpperArm: { x: 0, y: 0, z: ARM_DOWN },
  LeftUpperArm: { x: 0, y: 0, z: -ARM_DOWN },
  RightLowerArm: { x: 0, y: 0, z: -ELBOW_RELAX },
  LeftLowerArm: { x: 0, y: 0, z: ELBOW_RELAX },
};

/**
 * Поставить руки вниз — спокойное положение вместо T-позы.
 *
 * Вызывать после `resetNormalizedPose()`: тот возвращает rest pose, а эта
 * функция опускает плечи. Понимает только humanoid-кости рук, остальное
 * (таз, корпус, голова) остаётся в rest.
 */
export function applyRelaxedArms(vrm: VRM): void {
  for (const [source, rotation] of Object.entries(RELAXED_ARM_ROTATIONS)) {
    applyBoneRotation(vrm, BONE_MAP[source], rotation);
  }
}

/**
 * Вернуть модель в нейтральную позу: руки вниз и нулевая мимика.
 * Используется при загрузке и между клипами (ТЗ 5.4: нейтральная поза).
 */
export function resetToNeutral(vrm: VRM): void {
  // `resetNormalizedPose`, а не `setNormalizedPose(rest)`: rest pose передан
  // относительными трансформами даёт задвоение и модель вырастает вдвое.
  vrm.humanoid.resetNormalizedPose();
  // Rest pose — T-поза; опускаем руки, чтобы аватар стоял спокойно.
  applyRelaxedArms(vrm);

  const expressions = vrm.expressionManager;
  if (!expressions) return;
  for (const name of ["blinkLeft", "blinkRight", "aa", "ee", "ih", "oh", "ou"]) {
    expressions.setValue(name, 0);
  }
}
