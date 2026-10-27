/**
 * Тесты ретаргета landmarks → позы костей (C3).
 *
 * Kalidokit превращает landmarks MediaPipe в углы Эйлера. Тесты проверяют
 * структуру результата, разбиение кадра по частям и то, что изменение позы
 * входных landmarks меняет соответствующие углы (ретаргет реагирует).
 */

import { describe, expect, it } from "vitest";

import { decodeClipPayload } from "./clip";
import { buildClipFixture } from "./clip.fixture";
import { retargetFrame, splitFrame } from "./retarget";
import { COUNTS, buildFace, buildHand, buildPose, flatten } from "./retarget.fixture";

/** Собрать клип с одной позой (или кадром) и раскодировать его. */
async function decodeSkeleton(opts: { raise?: number; spread?: number; withFace?: boolean; frames?: number } = {}) {
  const frames = opts.frames ?? 1;
  const values: number[] = [];
  for (let f = 0; f < frames; f += 1) {
    values.push(
      ...flatten(buildPose(opts.raise ?? 0)),
      ...flatten(buildHand(opts.spread ?? 1, "left")),
      ...flatten(buildHand(opts.spread ?? 1, "right")),
      ...flatten(buildFace()),
    );
  }
  const fixture = buildClipFixture({
    frames,
    layout: { pose: COUNTS.pose, hand_l: COUNTS.hand_l, hand_r: COUNTS.hand_r, face: COUNTS.face },
    values,
  });
  return decodeClipPayload(fixture.payload);
}

describe("splitFrame", () => {
  it("разбивает кадр на части по layout", async () => {
    const clip = await decodeSkeleton();
    const parts = splitFrame(clip, 0);

    expect(parts.pose).toHaveLength(COUNTS.pose);
    expect(parts.hand_l).toHaveLength(COUNTS.hand_l);
    expect(parts.hand_r).toHaveLength(COUNTS.hand_r);
    expect(parts.face).toHaveLength(COUNTS.face);
  });

  it("ставит visibility=1 для позы и не ставит для кистей", async () => {
    const parts = splitFrame(await decodeSkeleton(), 0);

    expect(parts.pose?.[0].visibility).toBe(1);
    expect(parts.hand_l?.[0].visibility).toBeUndefined();
  });

  it("берёт точки нужного кадра", async () => {
    const clip = await decodeSkeleton({ frames: 2 });
    const first = splitFrame(clip, 0).pose?.[0];
    const second = splitFrame(clip, 1).pose?.[0];

    // Кадры фикстуры одинаковы, но смещение читается верно (не выходит за массив).
    expect(first).toEqual(second);
    expect(first?.x).toBeCloseTo(0.5, 5);
  });
});

describe("retargetFrame", () => {
  it("возвращает позы костей при наличии позы", async () => {
    const result = retargetFrame(await decodeSkeleton(), 0);

    expect(result.hasPose).toBe(true);
    expect(result.bones).not.toBeNull();
    for (const key of [
      "RightUpperArm",
      "RightLowerArm",
      "LeftUpperArm",
      "LeftLowerArm",
      "RightHand",
      "LeftHand",
      "Spine",
    ] as const) {
      const bone = result.bones?.[key];
      expect(bone).toBeDefined();
      expect(Number.isFinite(bone?.x)).toBe(true);
      expect(Number.isFinite(bone?.y)).toBe(true);
      expect(Number.isFinite(bone?.z)).toBe(true);
    }
    expect(result.bones?.Hips.position).toBeDefined();
    expect(result.bones?.Hips.rotation).toBeDefined();
  });

  it("считает позы пальцев обеих кистей", async () => {
    const result = retargetFrame(await decodeSkeleton({ spread: 1 }), 0);

    expect(result.leftFingers).not.toBeNull();
    expect(result.rightFingers).not.toBeNull();
    expect(result.rightFingers?.RightIndexProximal).toBeDefined();
    expect(result.leftFingers?.LeftIndexProximal).toBeDefined();
  });

  it("реагирует на подъём руки: угол правой руки меняется", async () => {
    const down = retargetFrame(await decodeSkeleton({ raise: 0 }), 0);
    const up = retargetFrame(await decodeSkeleton({ raise: 1 }), 0);

    const changed =
      down.bones!.RightUpperArm.x !== up.bones!.RightUpperArm.x ||
      down.bones!.RightUpperArm.y !== up.bones!.RightUpperArm.y ||
      down.bones!.RightUpperArm.z !== up.bones!.RightUpperArm.z;

    expect(changed).toBe(true);
  });

  it("разжимает пальцы: кулак сгибает средний сустав, ладонь — нет", async () => {
    const fist = retargetFrame(await decodeSkeleton({ spread: 0 }), 0);
    const open = retargetFrame(await decodeSkeleton({ spread: 1 }), 0);

    // Средний сустав пальца: у кулака согнут заметно, у ладони почти прямой.
    const fistBend = Math.abs(fist.rightFingers!.RightIndexIntermediate.z);
    const openBend = Math.abs(open.rightFingers!.RightIndexIntermediate.z);
    expect(fistBend).toBeGreaterThan(0.3);
    expect(openBend).toBeLessThan(0.05);
  });

  it("считает лицо, когда оно есть в клипе", async () => {
    const result = retargetFrame(await decodeSkeleton({ withFace: true }), 0);

    expect(result.face).not.toBeNull();
    expect(Number.isFinite(result.face?.head.y)).toBe(true);
    expect(result.face?.mouth.shape).toHaveProperty("A");
    expect(Number.isFinite(result.face?.eye.l)).toBe(true);
  });

  it("без позы возвращает hasPose=false и не падает", async () => {
    const values = flatten(buildHand(1, "right"));
    const fixture = buildClipFixture({
      frames: 1,
      layout: { hand_r: COUNTS.hand_r },
      values,
    });
    const clip = await decodeClipPayload(fixture.payload);

    const result = retargetFrame(clip, 0);

    expect(result.hasPose).toBe(false);
    expect(result.bones).toBeNull();
    expect(result.rightFingers).not.toBeNull();
    expect(result.face).toBeNull();
  });

  it("короткая поза (<25 точек) не считается скелетом", async () => {
    const pose = flatten(buildPose().slice(0, 20));
    const fixture = buildClipFixture({ frames: 1, layout: { pose: 20 }, values: pose });
    const clip = await decodeClipPayload(fixture.payload);

    expect(retargetFrame(clip, 0).hasPose).toBe(false);
  });
});
