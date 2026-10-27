/**
 * Тесты применения позы к VRM (C3).
 *
 * Настоящий VRM в тестах не нужен: проверяется раскладка углов по костям и
 * выражениям. Используется структурная заглушка humanoid/expressionManager,
 * которая записывает, какие кости и выражения были тронуты.
 */

import * as THREE from "three";
import { describe, expect, it } from "vitest";
import type { VRM } from "@pixiv/three-vrm";

import { applyRetargetedFrame, resetToNeutral } from "./vrm-rig";
import type { RetargetedFrame } from "./retarget";

type FakeVrm = {
  vrm: VRM;
  bones: Map<string, THREE.Object3D>;
  expressions: Map<string, number>;
  resetPoseCalls: number;
};

/** Собрать заглушку VRM с костями и выражениями. */
function makeFakeVrm(boneNames: string[]): FakeVrm {
  const bones = new Map<string, THREE.Object3D>();
  for (const name of boneNames) {
    const node = new THREE.Object3D();
    node.name = name;
    bones.set(name, node);
  }

  const expressions = new Map<string, number>();
  const state = { resetPoseCalls: 0 };

  const humanoid = {
    getNormalizedBoneNode: (name: string) => bones.get(name) ?? null,
    setNormalizedPose: () => {
      state.resetPoseCalls += 1;
    },
    normalizedRestPose: {},
  };

  const expressionManager = {
    setValue: (name: string, weight: number) => {
      expressions.set(name, weight);
    },
  };

  const vrm = { humanoid, expressionManager } as unknown as VRM;
  return { vrm, bones, expressions, get resetPoseCalls() { return state.resetPoseCalls; } } as FakeVrm;
}

const ALL_BONES = [
  "hips",
  "spine",
  "head",
  "neck",
  "leftUpperArm",
  "leftLowerArm",
  "leftHand",
  "rightUpperArm",
  "rightLowerArm",
  "rightHand",
  "leftUpperLeg",
  "leftLowerLeg",
  "rightUpperLeg",
  "rightLowerLeg",
  "leftIndexProximal",
  "leftIndexIntermediate",
  "leftIndexDistal",
  "rightIndexProximal",
  "rightIndexIntermediate",
  "rightIndexDistal",
  "rightThumbMetacarpal",
  "rightThumbProximal",
  "rightThumbDistal",
];

function frameWithBones(): RetargetedFrame {
  const zero = { x: 0, y: 0, z: 0 };
  return {
    hasPose: true,
    bones: {
      RightUpperArm: { x: 0.5, y: 0, z: 0 },
      RightLowerArm: { x: 0, y: 0.4, z: 0 },
      LeftUpperArm: zero,
      LeftLowerArm: zero,
      RightHand: zero,
      LeftHand: zero,
      RightUpperLeg: zero,
      RightLowerLeg: zero,
      LeftUpperLeg: zero,
      LeftLowerLeg: zero,
      Hips: { position: { x: 0.2, y: -0.1, z: 0.3 }, rotation: zero },
      Spine: zero,
    },
    leftFingers: null,
    rightFingers: null,
    face: null,
  };
}

describe("applyRetargetedFrame", () => {
  it("поворачивает кости туловища и рук", () => {
    const fake = makeFakeVrm(ALL_BONES);

    applyRetargetedFrame(fake.vrm, frameWithBones());

    const upperArm = fake.bones.get("rightUpperArm")!;
    // Поворот применён: кватернион отличается от единичного.
    expect(upperArm.quaternion.angleTo(new THREE.Quaternion())).toBeGreaterThan(0);
    expect(upperArm.rotation.x).toBeCloseTo(0.5, 6);
  });

  it("переносит позицию бёдер (в уменьшенном масштабе)", () => {
    const fake = makeFakeVrm(ALL_BONES);

    applyRetargetedFrame(fake.vrm, frameWithBones());

    const hips = fake.bones.get("hips")!;
    expect(hips.position.x).toBeCloseTo(0.02, 6);
    expect(hips.position.y).toBeCloseTo(-0.01, 6);
  });

  it("раскладывает пальцы по костям кистей", () => {
    const fake = makeFakeVrm(ALL_BONES);
    const frame = frameWithBones();
    frame.rightFingers = {
      RightIndexProximal: { x: 0, y: 0, z: 0.3 },
      RightIndexIntermediate: { x: 0, y: 0, z: 0.6 },
      RightIndexDistal: { x: 0, y: 0, z: 0.8 },
      RightThumbProximal: { x: 0.1, y: 0, z: 0.2 },
      RightThumbIntermediate: { x: 0, y: 0, z: 0.2 },
      RightThumbDistal: { x: 0, y: 0, z: 0.2 },
    };

    applyRetargetedFrame(fake.vrm, frame);

    expect(fake.bones.get("rightIndexProximal")!.rotation.z).toBeCloseTo(0.3, 6);
    expect(fake.bones.get("rightIndexIntermediate")!.rotation.z).toBeCloseTo(0.6, 6);
    // Большой палец: Intermediate у Kalidokit → Metacarpal у VRM.
    expect(fake.bones.get("rightThumbMetacarpal")!.rotation.z).toBeCloseTo(0.2, 6);
    expect(fake.bones.get("rightThumbProximal")!.rotation.x).toBeCloseTo(0.1, 6);
  });

  it("переводит мимику в выражения VRM", () => {
    const fake = makeFakeVrm(ALL_BONES);
    const frame = frameWithBones();
    frame.face = {
      head: { x: 0.1, y: 0.2, z: 0 },
      eye: { l: 0.25, r: 0.75 },
      brow: 0.5,
      pupil: { x: 0, y: 0 },
      mouth: { x: 0, y: 0, shape: { A: 0.4, E: 0, I: 0, O: 0.2, U: 0 } },
    };

    applyRetargetedFrame(fake.vrm, frame);

    // Раскрытый глаз (eye=1) → мигание 0; закрытый (eye=0.25) → 0.75.
    expect(fake.expressions.get("blinkRight")).toBeCloseTo(0.75, 6);
    expect(fake.expressions.get("blinkLeft")).toBeCloseTo(0.25, 6);
    expect(fake.expressions.get("aa")).toBeCloseTo(0.4, 6);
    expect(fake.expressions.get("oh")).toBeCloseTo(0.2, 6);
    expect(fake.expressions.get("ee")).toBe(0);
    expect(fake.bones.get("head")!.rotation.x).toBeCloseTo(0.1, 6);
  });

  it("ограничивает углы пальцев и головы", () => {
    const fake = makeFakeVrm(ALL_BONES);
    const frame = frameWithBones();
    frame.rightFingers = { RightIndexProximal: { x: 0, y: 0, z: 5 } };
    frame.face = {
      head: { x: 5, y: 0, z: 0 },
      eye: { l: 1, r: 1 },
      brow: 0,
      pupil: { x: 0, y: 0 },
      mouth: { x: 0, y: 0, shape: { A: 0, E: 0, I: 0, O: 0, U: 0 } },
    };

    applyRetargetedFrame(fake.vrm, frame);

    expect(fake.bones.get("rightIndexProximal")!.rotation.z).toBeLessThanOrEqual(Math.PI / 2 + 1e-6);
    expect(fake.bones.get("head")!.rotation.x).toBeLessThanOrEqual(Math.PI / 3 + 1e-6);
  });

  it("без позы не трогает кости, но применяет пальцы и лицо", () => {
    const fake = makeFakeVrm(ALL_BONES);
    const frame: RetargetedFrame = {
      hasPose: false,
      bones: null,
      leftFingers: null,
      rightFingers: { RightIndexProximal: { x: 0, y: 0, z: 0.4 } },
      face: null,
    };

    applyRetargetedFrame(fake.vrm, frame);

    expect(fake.bones.get("rightUpperArm")!.rotation.x).toBe(0);
    expect(fake.bones.get("rightIndexProximal")!.rotation.z).toBeCloseTo(0.4, 6);
  });

  it("не падает, если у модели нет кости", () => {
    const fake = makeFakeVrm(["rightUpperArm"]);

    expect(() => applyRetargetedFrame(fake.vrm, frameWithBones())).not.toThrow();
  });
});

describe("resetToNeutral", () => {
  it("возвращает rest pose и обнуляет мимику", () => {
    const fake = makeFakeVrm(ALL_BONES);
    fake.expressions.set("aa", 0.8);
    fake.expressions.set("blinkLeft", 0.5);

    resetToNeutral(fake.vrm);

    expect(fake.resetPoseCalls).toBe(1);
    expect(fake.expressions.get("aa")).toBe(0);
    expect(fake.expressions.get("blinkLeft")).toBe(0);
    expect(fake.expressions.get("ou")).toBe(0);
  });
});
