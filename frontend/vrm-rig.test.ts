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
function makeFakeVrm(boneNames: string[], hipsRestY = 1.04): FakeVrm {
  const bones = new Map<string, THREE.Object3D>();
  for (const name of boneNames) {
    const node = new THREE.Object3D();
    node.name = name;
    bones.set(name, node);
  }
  // Как у настоящего VRM в нормализованном риге: узел `hips` стоит на мировой
  // высоте бёдер (~1.04), а не в начале координат.
  const hipsNode = bones.get("hips");
  if (hipsNode) hipsNode.position.set(0, hipsRestY, 0);

  const expressions = new Map<string, number>();
  const state = { resetPoseCalls: 0 };

  const humanoid = {
    getNormalizedBoneNode: (name: string) => bones.get(name) ?? null,
    setNormalizedPose: () => {
      state.resetPoseCalls += 1;
    },
    // Реальный API three-vrm: нейтраль ставит именно сброс нормализованной
    // позы (см. комментарий в vrm-rig.ts).
    resetNormalizedPose: () => {
      state.resetPoseCalls += 1;
      const hips = bones.get("hips");
      if (hips) hips.position.set(0, hipsRestY, 0);
    },
    // Узел `hips` нормализованного рига стоит на абсолютной высоте, и rest
    // pose хранит именно её — как у настоящего VRM.
    normalizedRestPose: {
      hips: { position: [0, hipsRestY, 0], rotation: [0, 0, 0, 1] },
    },
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

  it("переносит позицию бёдер как смещение от rest-высоты", () => {
    const fake = makeFakeVrm(ALL_BONES);

    applyRetargetedFrame(fake.vrm, frameWithBones());

    const hips = fake.bones.get("hips")!;
    // Rest-высота бёдер сохраняется, сверху идёт небольшое смещение.
    expect(hips.position.x).toBeCloseTo(0.02, 6);
    expect(hips.position.y).toBeCloseTo(1.04 - 0.01, 6);
  });

  it("не роняет модель вниз: бёдра остаются на rest-высоте", () => {
    const fake = makeFakeVrm(ALL_BONES);
    const restY = fake.bones.get("hips")!.position.y;
    expect(restY).toBeGreaterThan(1);

    // Кадр Slovo: Hips.position.y от Kalidokit всегда 0, x ≈ -0.5.
    const frame = frameWithBones();
    frame.bones!.Hips = { position: { x: -0.5, y: 0, z: 0 }, rotation: { x: 0, y: 0, z: 0 } };

    applyRetargetedFrame(fake.vrm, frame);

    const hips = fake.bones.get("hips")!;
    // Главное: высота бёдер не обнуляется — иначе модель «телепортируется»
    // вниз и из кадра видно только голову.
    expect(hips.position.y).toBeCloseTo(restY, 6);
    expect(hips.position.y).toBeGreaterThan(0.5);
  });

  it("поворачивает бёдра из кадра ретаргета", () => {
    const fake = makeFakeVrm(ALL_BONES);
    const frame = frameWithBones();
    frame.bones!.Hips.rotation = { x: 0, y: 0.25, z: 0 };

    applyRetargetedFrame(fake.vrm, frame);

    expect(fake.bones.get("hips")!.rotation.y).toBeCloseTo(0.25, 6);
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

  it("опускает руки вниз, а не оставляет T-позу", () => {
    const fake = makeFakeVrm(ALL_BONES);
    // До нейтрали руки стоят в T-позе (нулевой поворот).
    expect(fake.bones.get("rightUpperArm")!.quaternion.angleTo(new THREE.Quaternion())).toBeCloseTo(0);

    resetToNeutral(fake.vrm);

    // Плечи повёрнуты, и обе руки смотрят вниз. Правая кость направлена по
    // -X, левая — по +X (зеркально в T-позе), поэтому проверяем свой вектор.
    const right = fake.bones.get("rightUpperArm")!.quaternion;
    const left = fake.bones.get("leftUpperArm")!.quaternion;
    const rightArm = new THREE.Vector3(-1, 0, 0).applyQuaternion(right);
    const leftArm = new THREE.Vector3(1, 0, 0).applyQuaternion(left);
    expect(rightArm.y).toBeLessThan(-0.5); // правое плечо смотрит вниз
    expect(leftArm.y).toBeLessThan(-0.5); // левое плечо смотрит вниз
  });
});
