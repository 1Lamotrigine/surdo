import { describe, expect, it } from "vitest";

import {
  framePointCount,
  handsDetected,
  normalizeHolisticResult,
  normalizeLandmarkSet,
} from "./holistic";

const landmark = (x: number, y: number, z = 0) => ({ x, y, z, visibility: 0.9 });

describe("normalizeLandmarkSet", () => {
  it("берёт первый набор из ответа MediaPipe", () => {
    const points = normalizeLandmarkSet([[landmark(0.1, 0.2), landmark(0.3, 0.4)]]);

    expect(points).toHaveLength(2);
    expect(points[0]).toEqual({ x: 0.1, y: 0.2, z: 0, visibility: 0.9 });
  });

  it("понимает плоский массив точек", () => {
    const points = normalizeLandmarkSet([landmark(0.1, 0.2)]);

    expect(points).toHaveLength(1);
  });

  it("отбрасывает мусор и пустые ответы", () => {
    const points = normalizeLandmarkSet([
      { x: 0.2, y: 0.3 },
      { x: "bad", y: 0.3 },
      null,
      { y: 0.4 },
    ]);

    expect(points).toEqual([{ x: 0.2, y: 0.3, z: 0 }]);
    expect(normalizeLandmarkSet([])).toEqual([]);
    expect(normalizeLandmarkSet(undefined)).toEqual([]);
  });
});

describe("normalizeHolisticResult", () => {
  it("разбирает позу, лицо и обе кисти", () => {
    const hand = Array.from({ length: 21 }, () => landmark(0.5, 0.5));
    const frame = normalizeHolisticResult({
      poseLandmarks: [[landmark(0.1, 0.1)]],
      faceLandmarks: [[landmark(0.2, 0.2)]],
      leftHandLandmarks: [hand],
      rightHandLandmarks: [hand],
    });

    expect(frame.pose).toHaveLength(1);
    expect(frame.face).toHaveLength(1);
    expect(frame.leftHand).toHaveLength(21);
    expect(frame.rightHand).toHaveLength(21);
    expect(framePointCount(frame)).toBe(44);
  });

  it("возвращает пустой кадр, когда человека нет", () => {
    const frame = normalizeHolisticResult({
      poseLandmarks: [],
      faceLandmarks: [],
      leftHandLandmarks: [],
      rightHandLandmarks: [],
    });

    expect(framePointCount(frame)).toBe(0);
    expect(handsDetected(frame)).toEqual({ left: false, right: false });
  });

  it("считает кисть увиденной только при полном наборе", () => {
    const frame = normalizeHolisticResult({
      leftHandLandmarks: [Array.from({ length: 21 }, () => landmark(0.5, 0.5))],
      rightHandLandmarks: [Array.from({ length: 10 }, () => landmark(0.5, 0.5))],
    });

    expect(handsDetected(frame)).toEqual({ left: true, right: false });
  });
});
