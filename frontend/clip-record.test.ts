import { describe, expect, it } from "vitest";

import { decodeClip, decodeClipPayload } from "./clip";
import {
  ClipRecordError,
  RECORD_LAYOUT,
  RECORD_TOTAL_POINTS,
  autoTrimRange,
  clampTrimRange,
  encodeRecordedClip,
  frameHasBody,
  normalizeRecordedFrame,
  prepareRecordedFrames,
  resampleCapturedFrames,
  type CapturedFrame,
} from "./clip-record";
import { retargetFrame } from "./retarget";
import type { HolisticFrame, Landmark } from "./skeleton";

const STEP_MS = 1000 / 30;

function landmark(x: number, y = 0.5): Landmark {
  return { x, y, z: 0, visibility: 1 };
}

function frameAt(offset = 0, options: { empty?: boolean } = {}): HolisticFrame {
  if (options.empty) {
    return { pose: [], face: [], leftHand: [], rightHand: [] };
  }
  const pose = Array.from({ length: 33 }, (_, index) => landmark(0.25 + offset * 0.1 + index / 1000));
  const leftHand = Array.from({ length: 21 }, (_, index) =>
    landmark(0.2 + offset * 0.1 + index / 1000, 0.4),
  );
  const rightHand = Array.from({ length: 21 }, (_, index) =>
    landmark(0.7 + offset * 0.1 + index / 1000, 0.4),
  );
  const face = Array.from({ length: 468 }, (_, index) =>
    landmark(0.5 + offset * 0.01 + (index % 5) / 1000, 0.3),
  );
  return { pose, face, leftHand, rightHand };
}

function capture(
  count: number,
  options: { stepMs?: number; kind?: (index: number) => { empty?: boolean; offset?: number } } = {},
): CapturedFrame[] {
  const stepMs = options.stepMs ?? STEP_MS;
  return Array.from({ length: count }, (_, index) => {
    const spec = options.kind?.(index) ?? { offset: index };
    return {
      timeMs: index * stepMs,
      frame: frameAt(spec.offset ?? index, { empty: spec.empty }),
    };
  });
}

describe("frameHasBody", () => {
  it("считает тело найденным по позе или кисти", () => {
    expect(frameHasBody(frameAt(0))).toBe(true);
    expect(frameHasBody({ ...frameAt(0), pose: [], leftHand: [], rightHand: [] })).toBe(false);
    expect(frameHasBody({ ...frameAt(0), pose: [], rightHand: [] })).toBe(true);
    const hiddenPose = frameAt(0).pose.map((point) => ({ ...point, visibility: 0.1 }));
    expect(frameHasBody({ ...frameAt(0), pose: hiddenPose, leftHand: [], rightHand: [] })).toBe(
      false,
    );
  });
});

describe("autoTrimRange", () => {
  it("обрезает пустые кадры в начале и конце с запасом", () => {
    const frames = capture(9, {
      kind: (index) => ({ empty: index < 3 || index > 6, offset: index }),
    });

    expect(autoTrimRange(frames, { paddingFrames: 1 })).toEqual({ start: 2, end: 8 });
  });

  it("возвращает null, если человека не было", () => {
    const frames = capture(4, { kind: () => ({ empty: true }) });

    expect(autoTrimRange(frames)).toBeNull();
  });

  it("для короткого жеста добирает минимум кадров", () => {
    const frames = capture(5, {
      kind: (index) => ({ empty: index !== 2, offset: index }),
    });

    expect(autoTrimRange(frames, { paddingFrames: 0, minFrames: 3 })).toEqual({
      start: 2,
      end: 5,
    });
  });
});

describe("clampTrimRange", () => {
  it("держит диапазон внутри записи и не короче минимума", () => {
    expect(clampTrimRange({ start: -4, end: 99 }, 10, 2)).toEqual({ start: 0, end: 10 });
    expect(clampTrimRange({ start: 8, end: 8 }, 10, 2)).toEqual({ start: 8, end: 10 });
    expect(clampTrimRange({ start: 5, end: 3 }, 10, 2)).toEqual({ start: 5, end: 7 });
  });

  it("не падает на пустой записи", () => {
    expect(clampTrimRange({ start: 0, end: 4 }, 0)).toEqual({ start: 0, end: 0 });
  });
});

describe("resampleCapturedFrames", () => {
  it("переводит неравномерные кадры на 30 FPS", () => {
    // 11 кадров по 10 мс: 100 мс → 3 кадра при 30 FPS.
    const frames = capture(11, { stepMs: 10 });
    const resampled = resampleCapturedFrames(frames, 30);

    expect(resampled).toHaveLength(3);
    expect(resampled[0].timeMs).toBeCloseTo(0);
    expect(resampled[1].timeMs).toBeCloseTo(33.333, 2);
    expect(resampled[2].timeMs).toBeCloseTo(66.667, 2);
  });

  it("выбирает ближайший исходный кадр", () => {
    const frames = capture(11, { stepMs: 10 });
    const resampled = resampleCapturedFrames(frames, 30);

    expect(resampled.map((item) => item.frame.pose[0].x)).toEqual([
      frames[0].frame.pose[0].x,
      frames[3].frame.pose[0].x,
      frames[7].frame.pose[0].x,
    ]);
  });

  it("оставляет один кадр без движения", () => {
    expect(resampleCapturedFrames([capture(1)[0]], 30)).toHaveLength(1);
  });
});

describe("normalizeRecordedFrame", () => {
  it("добивает отсутствующие кисти и лицо до полного layout", () => {
    const normalized = normalizeRecordedFrame({
      pose: frameAt(0).pose,
      face: [],
      leftHand: [],
      rightHand: [],
    });

    expect(normalized.pose).toHaveLength(33);
    expect(normalized.leftHand).toHaveLength(21);
    expect(normalized.rightHand).toHaveLength(21);
    expect(normalized.face).toHaveLength(468);
  });

  it("берёт пропавшую кисть из предыдущего кадра", () => {
    const previous = frameAt(1);
    const normalized = normalizeRecordedFrame(
      { ...frameAt(2), leftHand: [], rightHand: [] },
      previous,
    );

    expect(normalized.leftHand[0].x).toBeCloseTo(previous.leftHand[0].x);
    expect(normalized.rightHand[0].x).toBeCloseTo(previous.rightHand[0].x);
  });
});

describe("prepareRecordedFrames", () => {
  it("возвращает полный layout и сглаживает джиттер", () => {
    const jittery = capture(20, {
      kind: (index) => ({ offset: index % 2 === 0 ? 0 : 0.02 }),
    });
    const raw = prepareRecordedFrames(jittery, 30, { smooth: false });
    const smoothed = prepareRecordedFrames(jittery, 30, { smooth: true });

    expect(raw).toHaveLength(20);
    expect(raw[0].pose).toHaveLength(33);
    expect(raw[0].face).toHaveLength(468);
    expect(smoothed[10].pose[0].x).not.toBe(raw[10].pose[0].x);
  });
});

describe("encodeRecordedClip", () => {
  it("собирает клип, который декодируется C2 без потерь структуры", async () => {
    const frames = capture(40);
    const result = await encodeRecordedClip({
      frames,
      range: { start: 0, end: 40 },
      gloss: "ПРИВЕТ",
    });
    const fromPayload = await decodeClipPayload(result.payload);
    const fromFile = await decodeClip(result.file);

    expect(result.payload.version).toBe(1);
    expect(result.payload.fps).toBe(30);
    expect(result.payload.layout).toEqual(RECORD_LAYOUT);
    expect(fromPayload.points).toBe(RECORD_TOTAL_POINTS);
    expect(fromPayload.frames).toBe(result.frameCount);
    expect(fromFile.frames).toBe(fromPayload.frames);
    expect(Array.from(fromFile.data)).toEqual(Array.from(fromPayload.data));
    expect(result.file.byteLength).toBeGreaterThan(0);
    expect(fromPayload.frames).toBe(39);
  });

  it("сохраняет значения landmark'ов в пределах точности Float16", async () => {
    const frames = capture(10);
    const result = await encodeRecordedClip({
      frames,
      range: { start: 2, end: 8 },
      smooth: false,
      gloss: "ТЕСТ",
    });
    const clip = await decodeClipPayload(result.payload);

    const expected = frames[2].frame.pose[0].x;
    // Decoded value лежит в первом канале точки 0 первого кадра.
    expect(clip.data[0]).toBeCloseTo(expected, 3);
    expect(Number.isFinite(clip.data[0])).toBe(true);
  });

  it("ограничивает длину клипа лимитом кадров", async () => {
    const result = await encodeRecordedClip({
      frames: capture(400),
      range: { start: 0, end: 400 },
      maxFrames: 50,
    });

    expect(result.frameCount).toBe(50);
    expect(result.payload.frames).toBe(50);
  });

  it("не содержит NaN и ретаргетится как обычный клип", async () => {
    const result = await encodeRecordedClip({
      frames: capture(20),
      range: { start: 0, end: 20 },
    });
    const clip = await decodeClipPayload(result.payload);
    const frame = retargetFrame(clip, Math.floor(clip.frames / 2));

    expect(Array.from(clip.data).every(Number.isFinite)).toBe(true);
    expect(frame.hasPose).toBe(true);
    expect(frame.bones).not.toBeNull();
    expect(frame.leftFingers).not.toBeNull();
    expect(frame.rightFingers).not.toBeNull();
    expect(frame.face).not.toBeNull();
  });

  it("отклоняет пустую запись и диапазон без позы", async () => {
    await expect(
      encodeRecordedClip({ frames: [], range: { start: 0, end: 0 } }),
    ).rejects.toThrow(ClipRecordError);

    const withGap = capture(5, {
      kind: (index) => ({ empty: index > 1, offset: index }),
    });
    await expect(
      encodeRecordedClip({ frames: withGap, range: { start: 3, end: 5 } }),
    ).rejects.toThrow(/нет позы или кистей/);
  });
});
