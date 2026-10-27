/**
 * Тесты блендинга кадров ретаргета (C4).
 *
 * Проверяется смешивание двух кадров и уход в нейтральную позу: значения
 * линейно интерполируются, `t` зажимается, отсутствующие части не ломают слияние.
 */

import { describe, expect, it } from "vitest";

import { crossfade, ease, fadeToNeutral, lerpFrames, neutralFrame } from "./clip-blend";
import type { BonePose, RetargetedFace, RetargetedFrame } from "./retarget";

const zero = { x: 0, y: 0, z: 0 };

/** Кадр с одной ненулевой костью и мимикой. */
function frameWith(value: number): RetargetedFrame {
  const bones: BonePose = {
    RightUpperArm: { x: value, y: 0, z: 0 },
    RightLowerArm: zero,
    LeftUpperArm: zero,
    LeftLowerArm: zero,
    RightHand: zero,
    LeftHand: zero,
    RightUpperLeg: zero,
    RightLowerLeg: zero,
    LeftUpperLeg: zero,
    LeftLowerLeg: zero,
    Hips: { position: zero, rotation: zero },
    Spine: zero,
  };
  const face: RetargetedFace = {
    head: { x: value, y: 0, z: 0 },
    eye: { l: value, r: value },
    brow: value,
    pupil: { x: value, y: value },
    mouth: { x: value, y: value, shape: { A: value, E: value, I: value, O: value, U: value } },
  };
  return {
    hasPose: true,
    bones,
    leftFingers: { LeftIndexProximal: { x: 0, y: 0, z: value } },
    rightFingers: { RightIndexProximal: { x: 0, y: 0, z: value } },
    face,
  };
}

describe("ease", () => {
  it("сглаживает границы и проходит через середину", () => {
    expect(ease(0)).toBe(0);
    expect(ease(1)).toBe(1);
    expect(ease(0.5)).toBeCloseTo(0.5, 6);
    // S-образная кривая: в начале роста медленнее линейной.
    expect(ease(0.1)).toBeLessThan(0.1);
    expect(ease(0.9)).toBeGreaterThan(0.9);
  });

  it("зажимает вход в 0..1", () => {
    expect(ease(-5)).toBe(0);
    expect(ease(5)).toBe(1);
    expect(ease(Number.NaN)).toBe(0);
  });
});

describe("lerpFrames", () => {
  it("возвращает исходные кадры на границах", () => {
    const a = frameWith(0.2);
    const b = frameWith(0.8);
    expect(lerpFrames(a, b, 0).bones?.RightUpperArm.x).toBeCloseTo(0.2, 6);
    expect(lerpFrames(a, b, 1).bones?.RightUpperArm.x).toBeCloseTo(0.8, 6);
  });

  it("интерполирует кости, пальцы и мимику", () => {
    const merged = lerpFrames(frameWith(0), frameWith(1), 0.25);
    expect(merged.bones?.RightUpperArm.x).toBeCloseTo(0.25, 6);
    expect(merged.leftFingers?.LeftIndexProximal.z).toBeCloseTo(0.25, 6);
    expect(merged.rightFingers?.RightIndexProximal.z).toBeCloseTo(0.25, 6);
    expect(merged.face?.head.x).toBeCloseTo(0.25, 6);
    expect(merged.face?.eye.l).toBeCloseTo(0.25, 6);
    expect(merged.face?.mouth.shape.A).toBeCloseTo(0.25, 6);
  });

  it("зажимает t в 0..1", () => {
    expect(lerpFrames(frameWith(0), frameWith(1), -1).bones?.RightUpperArm.x).toBe(0);
    expect(lerpFrames(frameWith(0), frameWith(1), 5).bones?.RightUpperArm.x).toBe(1);
  });

  it("сливает кадр с нейтральной позой", () => {
    const merged = lerpFrames(frameWith(1), neutralFrame(), 0.5);
    expect(merged.bones?.RightUpperArm.x).toBeCloseTo(0.5, 6);
    expect(merged.face?.head.x).toBeCloseTo(0.5, 6);
  });

  it("сохраняет союз ключей пальцев", () => {
    const a: RetargetedFrame = { hasPose: false, bones: null, leftFingers: null, rightFingers: { RightIndexProximal: { x: 0, y: 0, z: 1 } }, face: null };
    const b: RetargetedFrame = { hasPose: false, bones: null, leftFingers: null, rightFingers: { RightThumbProximal: { x: 0, y: 0, z: 1 } }, face: null };
    const merged = lerpFrames(a, b, 0.5);
    expect(merged.rightFingers?.RightIndexProximal.z).toBeCloseTo(0.5, 6);
    expect(merged.rightFingers?.RightThumbProximal.z).toBeCloseTo(0.5, 6);
  });
});

describe("crossfade", () => {
  it("применяет сглаживание к прогрессу", () => {
    // Прогресс 0.1 → ease(0.1) ≈ 0.028 — движение начинается медленно.
    const merged = crossfade(frameWith(0), frameWith(1), 0.1);
    expect(merged.bones?.RightUpperArm.x).toBeCloseTo(ease(0.1), 6);
    expect(merged.bones?.RightUpperArm.x).toBeLessThan(0.1);
  });

  it("на границах даёт исходные кадры", () => {
    const a = frameWith(0.3);
    const b = frameWith(0.7);
    expect(crossfade(a, b, 0).bones?.RightUpperArm.x).toBeCloseTo(0.3, 6);
    expect(crossfade(a, b, 1).bones?.RightUpperArm.x).toBeCloseTo(0.7, 6);
  });
});

describe("fadeToNeutral", () => {
  it("ведёт кадр к нулю", () => {
    expect(fadeToNeutral(frameWith(1), 0).bones?.RightUpperArm.x).toBeCloseTo(1, 6);
    expect(fadeToNeutral(frameWith(1), 1).bones?.RightUpperArm.x).toBeCloseTo(0, 6);
    expect(fadeToNeutral(frameWith(1), 0.5).bones?.RightUpperArm.x).toBeCloseTo(0.5, 6);
    expect(fadeToNeutral(frameWith(1), 1).face?.head.x).toBeCloseTo(0, 6);
  });
});

describe("neutralFrame", () => {
  it("пустой: без поз, пальцев и мимики", () => {
    const neutral = neutralFrame();
    expect(neutral.hasPose).toBe(false);
    expect(neutral.bones).toBeNull();
    expect(neutral.leftFingers).toBeNull();
    expect(neutral.rightFingers).toBeNull();
    expect(neutral.face).toBeNull();
  });
});
