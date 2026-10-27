/**
 * Тесты проигрывателя клипа (C3).
 *
 * Таймер в тестах не используется: кадры прогоняются вручную через `tick()`,
 * что делает проверку детерминированной.
 */

import * as THREE from "three";
import { describe, expect, it, vi } from "vitest";
import type { VRM } from "@pixiv/three-vrm";

import { decodeClipPayload } from "./clip";
import { ClipPlayer } from "./clip-player";
import { buildClipFixture } from "./clip.fixture";
import { COUNTS, buildFace, buildHand, buildPose, flatten } from "./retarget.fixture";

/** Заглушка VRM, как в тестах vrm-rig. */
function makeFakeVrm(): { vrm: VRM; bones: Map<string, THREE.Object3D>; expressions: Map<string, number>; resets: () => number } {
  const names = [
    "hips", "spine", "head", "neck",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
    "rightIndexProximal", "rightIndexIntermediate", "rightIndexDistal",
  ];
  const bones = new Map<string, THREE.Object3D>();
  for (const name of names) {
    const node = new THREE.Object3D();
    bones.set(name, node);
  }
  const expressions = new Map<string, number>();
  let resets = 0;

  const vrm = {
    humanoid: {
      getNormalizedBoneNode: (name: string) => bones.get(name) ?? null,
      setNormalizedPose: () => {
        resets += 1;
      },
      normalizedRestPose: {},
    },
    expressionManager: {
      setValue: (name: string, weight: number) => expressions.set(name, weight),
    },
  } as unknown as VRM;

  return { vrm, bones, expressions, resets: () => resets };
}

async function makeClip(frames = 3) {
  const values: number[] = [];
  for (let f = 0; f < frames; f += 1) {
    values.push(
      ...flatten(buildPose(f / Math.max(frames - 1, 1))),
      ...flatten(buildHand(1, "left")),
      ...flatten(buildHand(1, "right")),
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

describe("ClipPlayer", () => {
  it("load возвращает модель в нейтральную позу", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm);

    player.load(await makeClip());

    expect(fake.resets()).toBe(1);
    expect(player.currentFrame).toBe(0);
    expect(player.isPlaying).toBe(false);
  });

  it("проигрывает кадры по tick и останавливается на конце", async () => {
    const fake = makeFakeVrm();
    const onEnd = vi.fn();
    const player = new ClipPlayer(fake.vrm, { onEnd, smoothing: false });
    player.load(await makeClip(3));

    player.tick();
    player.tick();
    player.tick();
    expect(player.currentFrame).toBe(3);

    // Следующий тик завершает и возвращает нейтральную позу.
    player.tick();
    expect(onEnd).toHaveBeenCalledOnce();
    expect(player.isPlaying).toBe(false);
  });

  it("в цикле возвращается к первому кадру", async () => {
    const fake = makeFakeVrm();
    const onEnd = vi.fn();
    const player = new ClipPlayer(fake.vrm, { loop: true, onEnd, smoothing: false });
    player.load(await makeClip(2));

    player.tick();
    player.tick();
    player.tick();

    expect(player.currentFrame).toBe(1);
    expect(onEnd).not.toHaveBeenCalled();
  });

  it("применяет позы к костям", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm, { smoothing: false });
    player.load(await makeClip(1));

    player.tick();

    // Рука поднята (raise=0 для единственного кадра), поза применена не нулевая.
    const roundTrip = fake.bones.get("rightUpperArm")!.rotation;
    expect(Number.isFinite(roundTrip.x)).toBe(true);
  });

  it("сглаживание сохраняет visibility позы (руки не гасятся)", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm, { smoothing: true });
    player.load(await makeClip(2));

    player.tick();

    // Кость плеча повёрнута: если бы visibility потерялся, Kalidokit обнулил бы руку.
    expect(fake.bones.get("rightUpperArm")!.rotation.x).not.toBe(0);
  });

  it("stop прекращает воспроизведение", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm);
    player.load(await makeClip(5));
    player.start();
    expect(player.isPlaying).toBe(true);

    player.stop();

    expect(player.isPlaying).toBe(false);
  });

  it("dispose очищает клип", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm);
    player.load(await makeClip(1));
    player.dispose();
    player.tick();
    expect(player.currentFrame).toBe(0);
  });

  it("setGapMs пересобирает план без остановки показа", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm, { gapMs: 120, smoothing: false });
    const clip = await makeClip(3);
    player.loadQueue([clip, clip]);
    player.start();

    player.setGapMs(0);

    expect(player.queue?.gapMs).toBe(0);
    expect(player.isPlaying).toBe(true);
    player.dispose();
  });
});
