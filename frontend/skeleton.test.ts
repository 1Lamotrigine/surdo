import { describe, expect, it } from "vitest";

import {
  coverTransform,
  mapLandmark,
  skeletonSegments,
  type HolisticFrame,
  type Landmark,
  type Viewport,
} from "./skeleton";

function point(x: number, y: number, visibility = 1): Landmark {
  return { x, y, z: 0, visibility };
}

function frame(partial: Partial<HolisticFrame> = {}): HolisticFrame {
  return {
    pose: [],
    face: [],
    leftHand: [],
    rightHand: [],
    ...partial,
  };
}

function poseWith(index: number, landmark: Landmark): Landmark[] {
  const points = Array.from({ length: 33 }, () => point(0.5, 0.5));
  points[index] = landmark;
  return points;
}

const viewport: Viewport = {
  width: 800,
  height: 600,
  videoWidth: 1280,
  videoHeight: 720,
  mirror: false,
};

describe("coverTransform", () => {
  it("вписывает кадр 16:9 в холст 4:3 по большей стороне", () => {
    const { scale, offsetX, offsetY } = coverTransform(viewport);

    expect(scale).toBeCloseTo(600 / 720);
    expect(offsetX).toBeCloseTo((800 - 1280 * (600 / 720)) / 2);
    expect(offsetY).toBeCloseTo(0);
  });

  it("не делит на ноль при пустом видео", () => {
    const { scale } = coverTransform({ ...viewport, videoWidth: 0, videoHeight: 0 });

    expect(Number.isFinite(scale)).toBe(true);
    expect(scale).toBeGreaterThan(0);
  });
});

describe("mapLandmark", () => {
  it("переводит нормализованную точку в пиксели с учётом полей", () => {
    const mapped = mapLandmark(point(0.5, 0.5), viewport);

    expect(mapped.x).toBeCloseTo(400);
    expect(mapped.y).toBeCloseTo(300);
  });

  it("отражает x для зеркальной камеры", () => {
    const left = mapLandmark(point(0.25, 0.5), viewport);
    const mirrored = mapLandmark(point(0.25, 0.5), { ...viewport, mirror: true });

    expect(mirrored.x).toBeCloseTo(800 - left.x);
    expect(mirrored.y).toBeCloseTo(left.y);
  });
});

describe("skeletonSegments", () => {
  it("строит ребро позы по двум точкам", () => {
    const pose = poseWith(11, point(0.25, 0.5));
    pose[12] = point(0.75, 0.5);

    const segments = skeletonSegments(frame({ pose }), viewport, { groups: ["pose"] });
    const left = mapLandmark(point(0.25, 0.5), viewport);
    const right = mapLandmark(point(0.75, 0.5), viewport);
    const shoulders = segments.find(
      (segment) =>
        segment.group === "pose" &&
        Math.abs(segment.x1 - left.x) < 0.01 &&
        Math.abs(segment.x2 - right.x) < 0.01,
    );

    expect(shoulders).toBeDefined();
    expect(shoulders?.y1).toBeCloseTo(300);
  });

  it("пропускает точки ниже порога видимости", () => {
    const pose = poseWith(11, point(0.25, 0.5, 0.1));
    pose[12] = point(0.75, 0.5);

    const segments = skeletonSegments(frame({ pose }), viewport, {
      groups: ["pose"],
      minVisibility: 0.5,
    });

    const left = mapLandmark(point(0.25, 0.5), viewport);
    const right = mapLandmark(point(0.75, 0.5), viewport);
    expect(
      segments.some(
        (segment) =>
          Math.abs(segment.x1 - left.x) < 0.01 && Math.abs(segment.x2 - right.x) < 0.01,
      ),
    ).toBe(false);
  });

  it("рисует обе кисти по 21 точке", () => {
    const hand = Array.from({ length: 21 }, (_, index) => point(index / 21, 0.5));

    const segments = skeletonSegments(
      frame({ leftHand: hand, rightHand: hand }),
      viewport,
      { groups: ["hand"] },
    );

    // 21 связь на кисть из HAND_CONNECTIONS.
    expect(segments).toHaveLength(42);
    expect(segments.every((segment) => segment.group === "hand")).toBe(true);
  });

  it("не рисует связи, если точки части скелета нет", () => {
    expect(skeletonSegments(frame(), viewport)).toEqual([]);
  });

  it("фильтрует группы по запросу", () => {
    const face = Array.from({ length: 468 }, () => point(0.5, 0.5));
    const segments = skeletonSegments(frame({ face }), viewport, { groups: ["face"] });

    expect(segments.length).toBeGreaterThan(0);
    expect(segments.every((segment) => segment.group === "face")).toBe(true);
  });
});
