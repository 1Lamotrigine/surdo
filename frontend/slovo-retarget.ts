import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import { Euler, Matrix4, Quaternion, Vector3 } from "three";

import { pointAt, type DecodedClip } from "./clip";
import type { BonePose, ClipParts, FingerPose, Landmark, RetargetedFrame } from "./retarget";

const ZERO = { x: 0, y: 0, z: 0 };
const X = new Vector3(1, 0, 0);
const SIDES = [
  { side: "left", prefix: "Left", part: "hand_l", pose: [11, 13, 15, 19, 17] },
  { side: "right", prefix: "Right", part: "hand_r", pose: [12, 14, 16, 20, 18] },
] as const;

// Имена выходных сегментов большого пальца соответствуют карте в vrm-rig.ts.
const FINGERS = [
  ["Thumb", 1, ["Metacarpal", "Proximal", "Distal"], ["Intermediate", "Proximal", "Distal"]],
  ["Index", 5, ["Proximal", "Intermediate", "Distal"]],
  ["Middle", 9, ["Proximal", "Intermediate", "Distal"]],
  ["Ring", 13, ["Proximal", "Intermediate", "Distal"]],
  ["Little", 17, ["Proximal", "Intermediate", "Distal"]],
] as const;

/** Старые клипы Slovo хранят позу в метрах без метки, а кисти в координатах кадра. */
export function slovoSpace(clip: DecodedClip): "world" | "legacy" | null {
  if (clip.coordinate_space === "mediapipe-world") return "world";
  const { pose, hand_l, hand_r, face } = clip.offsets;
  if (pose?.count !== 33 || hand_l?.count !== 21 || hand_r?.count !== 21 || face) return null;
  const middle = Math.floor(clip.frames / 2);
  const leftShoulder = pointAt(clip, middle, pose.start + 11)!;
  const rightShoulder = pointAt(clip, middle, pose.start + 12)!;
  const leftHip = pointAt(clip, middle, pose.start + 23)!;
  const rightHip = pointAt(clip, middle, pose.start + 24)!;
  const hipsCentered =
    Math.abs(leftHip[0] + rightHip[0]) < 0.2 && Math.abs(leftHip[1] + rightHip[1]) < 0.2;
  return hipsCentered && Math.max(leftShoulder[1], rightShoulder[1]) < -0.1 ? "legacy" : null;
}

/** MediaPipe: x вправо по кадру, y вниз, z от камеры. VRM смотрит вдоль +z. */
function vector(point: Landmark, legacyHand = false): Vector3 {
  // z экранной кисти измеряется в долях ширины, как x. Для старых клипов
  // ширина/высота не сохранены, используем типичный вертикальный кадр Slovo.
  return new Vector3(point.x, -point.y * (legacyHand ? 16 / 9 : 1), -point.z);
}

function direction(points: Vector3[], from: number, to: number): Vector3 {
  return points[to].clone().sub(points[from]);
}

function usable(v: Vector3): boolean {
  return Number.isFinite(v.lengthSq()) && v.lengthSq() > 1e-10;
}

function basis(forward: Vector3, across: Vector3): Quaternion | null {
  const x = forward.clone().normalize();
  const z = new Vector3().crossVectors(x, across);
  if (!usable(forward) || !usable(z)) return null;
  z.normalize();
  const y = new Vector3().crossVectors(z, x);
  return new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(x, y, z));
}

function aim(rest: Vector3, target: Vector3): Quaternion {
  const rotation = new Quaternion();
  if (usable(rest) && usable(target)) {
    rotation.setFromUnitVectors(rest.normalize(), target.clone().normalize());
  }
  return rotation;
}

function localRotation(parent: Quaternion, rotation: Quaternion) {
  const { x, y, z } = new Euler().setFromQuaternion(parent.clone().invert().multiply(rotation));
  return { x, y, z };
}

function restVector(vrm: VRM, name: VRMHumanBoneName): Vector3 {
  const position = vrm.humanoid.normalizedRestPose?.[name]?.position;
  return position ? new Vector3().fromArray(position) : new Vector3();
}

export function retargetSlovo(
  vrm: VRM,
  parts: ClipParts,
  legacy: boolean,
  weights: Partial<Record<"hand_l" | "hand_r", number>> = {},
  previousTwist: Partial<Record<"left" | "right", number>> = {},
): RetargetedFrame {
  const frame: RetargetedFrame = {
    hasPose: false,
    bones: null,
    leftFingers: null,
    rightFingers: null,
    face: null,
    world: true,
  };
  if (parts.pose?.length !== 33) return frame;

  const pose = parts.pose.map((point) => vector(point));
  const center = (a: number, b: number) => pose[a].clone().lerp(pose[b], 0.5);
  const body = basis(direction(pose, 12, 11), center(11, 12).sub(center(23, 24))) ?? new Quaternion();
  const bones: BonePose = {
    Hips: { position: ZERO, rotation: ZERO },
    Spine: localRotation(new Quaternion(), body),
    LeftUpperLeg: ZERO, LeftLowerLeg: ZERO, RightUpperLeg: ZERO, RightLowerLeg: ZERO,
    LeftUpperArm: ZERO, LeftLowerArm: ZERO, LeftHand: ZERO,
    RightUpperArm: ZERO, RightLowerArm: ZERO, RightHand: ZERO,
  };

  for (const { side, prefix, part, pose: [shoulder, elbow, wrist, index, little] } of SIDES) {
    const upper = direction(pose, shoulder, elbow);
    const lower = direction(pose, elbow, wrist);
    const outward = X.clone().multiplyScalar(side === "left" ? 1 : -1);
    const upperRest = restVector(vrm, `${side}LowerArm`);
    const lowerRest = restVector(vrm, `${side}Hand`);
    const upperQ = aim(usable(upperRest) ? upperRest : outward.clone(), upper);
    const lowerQ = aim(usable(lowerRest) ? lowerRest : outward.clone(), lower);

    const hand = parts[part]?.map((point) => vector(point, legacy));
    // Кисть, синтезированная старым конвертером, лежит в одной плоскости z.
    const detected = hand?.length === 21 &&
      (!legacy || hand.some((point) => Math.abs(point.z - hand[0].z) > 1e-4))
      ? basis(direction(hand, 0, 9), direction(hand, 5, 17))
      : null;
    const posePalm =
      basis(pose[index].clone().lerp(pose[little], 0.5).sub(pose[wrist]), direction(pose, index, little));
    const middleRest = restVector(vrm, `${side}MiddleProximal`);
    const acrossRest = restVector(vrm, `${side}LittleProximal`).sub(restVector(vrm, `${side}IndexProximal`));
    const restPalm = basis(middleRest, acrossRest) ??
      basis(outward, new Vector3(0, 0, side === "left" ? -1 : 1))!;
    restPalm.invert();
    const fallbackQ = posePalm?.multiply(restPalm) ?? lowerQ.clone();
    const weight = weights[part] ?? 1;
    const handQ = detected ? fallbackQ.slerp(detected.multiply(restPalm), weight) : fallbackQ;
    // Пронация распределяется между предплечьем и кистью. Скручивание вокруг
    // продольной оси не меняет направления от локтя к запястью.
    const axis = lower.clone().normalize();
    const roll = handQ.clone().multiply(lowerQ.clone().invert());
    const projection = axis.x * roll.x + axis.y * roll.y + axis.z * roll.z;
    const lastTwist = previousTwist[side] ?? 0;
    const angle = 2 * Math.atan2(projection, roll.w);
    const turn = 2 * Math.PI;
    const continuous = angle + turn * Math.round((lastTwist - angle) / turn);
    previousTwist[side] = continuous;
    const twist = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, continuous / 2));
    lowerQ.premultiply(new Quaternion().setFromAxisAngle(axis, twist));

    bones[`${prefix}UpperArm`] = localRotation(body, upperQ);
    bones[`${prefix}LowerArm`] = localRotation(upperQ, lowerQ);
    bones[`${prefix}Hand`] = localRotation(lowerQ, handQ);

    const fingers: FingerPose = {};
    for (const [finger, first, segments, output = segments] of FINGERS) {
      let parent = detected ?? handQ;
      for (let joint = 0; joint < segments.length; joint += 1) {
        // У дистальной кости нет humanoid-узла кончика пальца.
        const next = segments[joint === 2 ? joint : joint + 1];
        const rest = restVector(vrm, `${side}${finger}${next}` as VRMHumanBoneName);
        const target = detected && hand ? direction(hand, first + joint, first + joint + 1) : new Vector3();
        const rotation = aim(rest, target.applyQuaternion(parent.clone().invert()));
        const softened = new Quaternion().slerp(rotation, weight);
        fingers[`${prefix}${finger}${output[joint]}`] = localRotation(new Quaternion(), softened);
        parent = parent.clone().multiply(rotation);
      }
    }
    if (side === "left") frame.leftFingers = fingers;
    else frame.rightFingers = fingers;
  }

  frame.hasPose = true;
  frame.bones = bones;
  return frame;
}
