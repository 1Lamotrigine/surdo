/**
 * Тест синтетического демо-клипа (C3): то, что страница собирает в браузере,
 * успешно декодируется (C2) и ретаргетится (C3).
 */

import { describe, expect, it } from "vitest";

import { decodeClipPayload } from "./clip";
import { DEMO_LAYOUT, encodeDemoClip } from "./demo-clip";
import { retargetFrame } from "./retarget";

describe("encodeDemoClip", () => {
  it("собирает валидный клип формата v1", async () => {
    const payload = await encodeDemoClip(12, 30);

    expect(payload.version).toBe(1);
    expect(payload.fps).toBe(30);
    expect(payload.frames).toBe(12);
    expect(payload.layout).toEqual(DEMO_LAYOUT);
    expect(typeof payload.data).toBe("string");
    expect((payload.data as string).length).toBeGreaterThan(0);
  });

  it("декодируется в массив нужного размера", async () => {
    const payload = await encodeDemoClip(6, 30);
    const clip = await decodeClipPayload(payload);

    const points = Object.values(DEMO_LAYOUT).reduce((sum, n) => sum + n, 0);
    expect(clip.points).toBe(points);
    expect(clip.data.length).toBe(6 * points * 3);
  });

  it("ретаргетится: рука и пальцы двигаются между кадрами", async () => {
    const clip = await decodeClipPayload(await encodeDemoClip(12, 30));

    const first = retargetFrame(clip, 0);
    expect(first.hasPose).toBe(true);
    expect(first.rightFingers).not.toBeNull();

    // Пальцы правой кисти сгибаются по ходу клипа (демо меняет curl):
    // собираем сгиб по всем кадрам и убеждаемся, что он не постоянный.
    const bends = Array.from({ length: clip.frames }, (_, f) =>
      Math.abs(retargetFrame(clip, f).rightFingers!.RightIndexIntermediate.z),
    );
    expect(Math.max(...bends) - Math.min(...bends)).toBeGreaterThan(0.05);
  });

  it("лицо присутствует и содержит форму рта", async () => {
    const clip = await decodeClipPayload(await encodeDemoClip(3, 30));
    const frame = retargetFrame(clip, 0);

    expect(frame.face).not.toBeNull();
    expect(frame.face?.mouth.shape).toHaveProperty("A");
  });
});
