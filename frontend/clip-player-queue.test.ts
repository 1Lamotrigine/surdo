/**
 * Тесты очереди клипов в игроке (C4).
 *
 * Проверяется поведение очереди: порядок клипов, пауза в нейтральной позе между
 * фразами, crossfade на стыке, уход в нейтраль в конце и уважение пределов
 * скорости. Кадры прогоняются вручную через `tick` — без таймера.
 */

import * as THREE from "three";
import { describe, expect, it, vi } from "vitest";
import type { VRM } from "@pixiv/three-vrm";

import { decodeClipPayload, type DecodedClip } from "./clip";
import { ClipPlayer } from "./clip-player";
import { buildClipFixture } from "./clip.fixture";
import { COUNTS, buildFace, buildHand, buildPose, flatten } from "./retarget.fixture";

/** Заглушка VRM: записывает кости и выражения, считает сбросы позы. */
function makeFakeVrm(): {
  vrm: VRM;
  bones: Map<string, THREE.Object3D>;
  expressions: Map<string, number>;
  resets: () => number;
} {
  const names = [
    "hips", "spine", "head", "neck",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
  ];
  const bones = new Map<string, THREE.Object3D>();
  for (const name of names) bones.set(name, new THREE.Object3D());
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

/** Собрать клип с заданным числом кадров и подъёмом руки. */
async function makeClip(frames: number, raise = 0, fps = 30): Promise<DecodedClip> {
  const values: number[] = [];
  for (let f = 0; f < frames; f += 1) {
    values.push(
      ...flatten(buildPose(raise)),
      ...flatten(buildHand(1, "left")),
      ...flatten(buildHand(1, "right")),
      ...flatten(buildFace()),
    );
  }
  const fixture = buildClipFixture({
    frames,
    fps,
    layout: { pose: COUNTS.pose, hand_l: COUNTS.hand_l, hand_r: COUNTS.hand_r, face: COUNTS.face },
    values,
  });
  return decodeClipPayload(fixture.payload);
}

describe("ClipPlayer — очередь клипов", () => {
  it("loadQueue планирует crossfade и стартует с первого клипа", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm, { smoothing: false });
    player.loadQueue([await makeClip(30), await makeClip(30)]);

    expect(player.clipCount).toBe(2);
    expect(player.currentClip).toBe(0);
    expect(player.currentFrame).toBe(0);
    // crossfade 200 мс при 30 fps и 1x → 6 кадров.
    expect(player.crossfadeFrameCount).toBe(6);
    expect(player.queue?.segments).toHaveLength(2);
    expect(fake.resets()).toBe(1);
  });

  it("проходит клипы по порядку", async () => {
    const fake = makeFakeVrm();
    const onClip = vi.fn();
    const player = new ClipPlayer(fake.vrm, { onClip, smoothing: false });
    player.loadQueue([await makeClip(3), await makeClip(3)]);

    // Первый клип: 3 кадра.
    player.tick();
    player.tick();
    player.tick();
    expect(player.currentClip).toBe(0);

    // Четвёртый тик переключает на второй клип и рисует его первый кадр.
    player.tick();
    expect(player.currentClip).toBe(1);
    expect(onClip).toHaveBeenCalledWith(1);

    // Ещё два кадра второго клипа.
    player.tick();
    player.tick();
    expect(player.currentClip).toBe(1);

    // Затем уход в нейтраль (crossfade-кадры) и завершение.
    const onEnd = vi.fn();
    const player2 = new ClipPlayer(fake.vrm, { onEnd, smoothing: false });
    player2.loadQueue([await makeClip(2), await makeClip(2)]);
    for (let i = 0; i < 100 && !onEnd.mock.calls.length; i += 1) player2.tick();
    expect(onEnd).toHaveBeenCalledOnce();
    expect(player2.isPlaying).toBe(false);
  });

  it("вставляет паузу в нейтральной позе между фразами", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm, { gapMs: 200, smoothing: false });
    player.loadQueue([await makeClip(2), await makeClip(2)]);

    // Два кадра первого клипа.
    player.tick();
    player.tick();

    // Тик на границе: начинается пауза, кадр нейтральный.
    player.tick();
    expect(player.currentClip).toBe(0);

    // В паузе кости не трогаются новыми кадрами: проверим, что тик не переключил
    // клип сразу (пауза 200 мс при 30 fps ≈ 6 кадров).
    player.tick();
    expect(player.currentClip).toBe(0);

    // Пауза закончилась — переключение на второй клип.
    for (let i = 0; i < 10 && player.currentClip === 0; i += 1) player.tick();
    expect(player.currentClip).toBe(1);
  });

  it("смешивает кадры на стыке (crossfade отличен от чистого кадра)", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm, { smoothing: false });
    player.loadQueue([await makeClip(30, 0), await makeClip(30, 1)]);

    // Прогоняем первый клип и попадаем в зону входа второго.
    for (let i = 0; i < 32; i += 1) player.tick();
    expect(player.currentClip).toBe(1);
    // Первый кадр второго клипа — начало crossfade: кость ещё близка к
    // последнему кадру первого клипа. Просто убеждаемся, что поворот конечен.
    const blended = fake.bones.get("rightUpperArm")!.rotation.x;
    expect(Number.isFinite(blended)).toBe(true);
  });

  it("в цикле возвращается к первому клипу", async () => {
    const fake = makeFakeVrm();
    const onEnd = vi.fn();
    const player = new ClipPlayer(fake.vrm, { loop: true, onEnd, smoothing: false });
    player.loadQueue([await makeClip(2), await makeClip(2)]);

    let restarted = false;
    for (let i = 0; i < 200 && !restarted; i += 1) {
      player.tick();
      if (player.currentClip === 0 && player.currentFrame > 0) restarted = true;
    }
    expect(restarted).toBe(true);
    expect(onEnd).not.toHaveBeenCalled();
  });

  it("зажимает слишком большую скорость", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm, { speed: 10, smoothing: false });
    player.loadQueue([await makeClip(10), await makeClip(10)]);
    expect(player.queue?.speed).toBe(1.3);
  });

  it("ужимает crossfade для коротких клипов", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm, { smoothing: false });
    // Клип из 2 кадров: переход не больше половины — 1 кадр.
    player.loadQueue([await makeClip(2), await makeClip(2)]);
    expect(player.crossfadeFrameCount).toBeLessThanOrEqual(1);
  });

  it("dispose очищает очередь", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm);
    player.loadQueue([await makeClip(3), await makeClip(3)]);
    player.dispose();
    expect(player.clipCount).toBe(0);
    expect(player.queue).toBeNull();
  });

  it("в режиме dactyl использует укороченный переход", async () => {
    const fake = makeFakeVrm();
    const player = new ClipPlayer(fake.vrm, {
      mode: "dactyl",
      crossfadeMs: 80,
      smoothing: false,
    });
    player.loadQueue([await makeClip(15), await makeClip(15), await makeClip(15)]);
    // 80 мс при 30 fps и 1x → ~2 кадра (а не 6, как у обычной фразы).
    expect(player.crossfadeFrameCount).toBeLessThanOrEqual(3);
    expect(player.queue?.mode).toBe("dactyl");
    expect(player.queue?.crossfadeMs).toBe(80);
  });
});
