import type { VRM } from "@pixiv/three-vrm";
import { Euler, Object3D, Quaternion } from "three";
import { expect, it, vi } from "vitest";

import { decodeClipPayload } from "./clip";
import { buildClipFixture } from "./clip.fixture";
import { ClipPlayer } from "./clip-player";
import { prepareSlovoMotion } from "./slovo-motion";

function makeVrm() {
  const rightLowerArm = new Object3D();
  const vrm = {
    humanoid: {
      normalizedRestPose: {},
      resetNormalizedPose: () => rightLowerArm.quaternion.identity(),
      getNormalizedBoneNode: (name: string) => name === "rightLowerArm" ? rightLowerArm : null,
    },
  } as unknown as VRM;
  return { vrm, rightLowerArm };
}

function makeClip(wristHeights: number[], missingHands: number[] = []) {
  const values = wristHeights.flatMap((height, i) => {
    const pose = Array.from({ length: 33 }, () => [0, 0, 0]);
    pose[11] = [0.2, -0.4, 0];
    pose[12] = [-0.2, -0.4, 0];
    pose[13] = [0.2, -0.2, 0];
    pose[14] = [-0.4, -0.4, 0];
    pose[15] = [0.2, 0.1, 0];
    pose[16] = [-0.4, height, -0.2];
    const hand = Array.from({ length: 21 }, () => [0, 0, 0]);
    if (!missingHands.includes(i)) {
      hand[5] = [0.2, 0, 0.1];
      hand[9] = [0.2, 0, 0];
      hand[17] = [0.2, 0, -0.1];
    }
    return [...pose.flat(), ...hand.flat()];
  });
  const { payload } = buildClipFixture({
    frames: wristHeights.length, layout: { pose: 33, hand_r: 21 }, values,
  });
  return decodeClipPayload({ ...payload, coordinate_space: "mediapipe-world" });
}

it("сохраняет ориентацию кисти при коротком пропуске трекинга", async () => {
  const { vrm } = makeVrm();
  const clip = await makeClip([-0.6, -0.6, -0.6], [1]);
  const poses = prepareSlovoMotion(vrm, clip, false);
  const wrist = (i: number) => {
    const { x, y, z } = poses[i].bones!.RightHand;
    return new Quaternion().setFromEuler(new Euler(x, y, z));
  };
  expect(wrist(1).angleTo(wrist(0))).toBeCloseTo(0);
  expect(wrist(1).angleTo(wrist(2))).toBeCloseTo(0);
});

it("обновляет кости между соседними кадрами записи и останавливает отрисовку", async () => {
  const callbacks = new Map<number, FrameRequestCallback>();
  let nextId = 0;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callbacks.set(++nextId, callback);
    return nextId;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => callbacks.delete(id));
  const render = (time: number) => {
    const [id, callback] = callbacks.entries().next().value!;
    callbacks.delete(id);
    callback(time);
  };

  try {
    const { vrm, rightLowerArm } = makeVrm();
    const player = new ClipPlayer(vrm, { smoothing: false });
    player.load(await makeClip([0.1, 0, -0.1, -0.2, -0.3, -0.4]));
    player.start();
    render(0);
    render(130);
    render(177);
    const previous = rightLowerArm.quaternion.clone();
    const frame = player.currentFrame;
    render(190);
    expect(player.currentFrame).toBe(frame);
    expect(rightLowerArm.quaternion.angleTo(previous)).toBeGreaterThan(0.01);
    player.stop();
    expect(callbacks.size).toBe(0);
  } finally {
    vi.unstubAllGlobals();
  }
});
