import type { VRM } from "@pixiv/three-vrm";
import { Object3D, Vector3 } from "three";
import { expect, it } from "vitest";

import { decodeClipPayload } from "./clip";
import { buildClipFixture } from "./clip.fixture";
import { ClipPlayer } from "./clip-player";
import { slovoSpace } from "./slovo-retarget";

it.each([true, false])("переносит движение на правую руку (метка координат: %s)", async (marked) => {
  const spine = new Object3D();
  const bones: Record<string, Object3D> = { spine };
  for (const [side, sign] of [["left", 1], ["right", -1]] as const) {
    let parent = spine;
    for (const name of ["UpperArm", "LowerArm", "Hand"]) {
      const bone = new Object3D();
      bone.position.set(sign, 0, 0);
      parent.add(bone);
      bones[side + name] = parent = bone;
    }
  }
  for (const [finger, x, z] of [["Index", -0.2, -0.1], ["Middle", -0.2, 0], ["Little", -0.2, 0.1]] as const) {
    const bone = new Object3D();
    bone.position.set(x, 0, z);
    bones.rightHand.add(bone);
    bones[`right${finger}Proximal`] = bone;
  }
  const rest = Object.fromEntries(Object.entries(bones).map(([name, bone]) => [
    name, { position: bone.position.toArray() },
  ]));
  const vrm = {
    humanoid: {
      normalizedRestPose: rest,
      resetNormalizedPose: () => {},
      getNormalizedBoneNode: (name: string) => bones[name],
    },
  } as unknown as VRM;

  const points = Array.from({ length: 33 }, () => [0, 0, 0]);
  points[11] = [0.2, -0.4, 0]; // левая рука опущена
  points[13] = [0.2, -0.2, 0];
  points[15] = [0.2, 0.1, 0];
  points[12] = [-0.2, -0.4, 0]; // правый локоть в сторону, предплечье вверх и вперёд
  points[14] = [-0.4, -0.4, 0];
  points[16] = [-0.4, -0.6, -0.2];
  points[23] = [0.1, 0, 0];
  points[24] = [-0.1, 0, 0];

  const hand = Array.from({ length: 21 }, () => [0, 0, 0]);
  hand[9] = [0.2, 0, 0];
  hand[5] = [0.2, 0, 0.1];
  hand[17] = [0.2, 0, -0.1];
  const { payload } = buildClipFixture({
    frames: 1,
    layout: { pose: 33, hand_l: 21, hand_r: 21 },
    values: [...points.flat(), ...Array(63).fill(0), ...hand.flat()],
  });
  const clip = await decodeClipPayload(marked ? { ...payload, coordinate_space: "mediapipe-world" } : payload);
  expect(slovoSpace(clip)).toBe(marked ? "world" : "legacy");

  const player = new ClipPlayer(vrm);
  player.load(clip);
  player.tick();
  const forearm = (side: string) => bones[side + "Hand"].getWorldPosition(new Vector3())
    .sub(bones[side + "LowerArm"].getWorldPosition(new Vector3()))
    .normalize();

  expect(forearm("left").dot(new Vector3(0, -1, 0))).toBeCloseTo(1);
  expect(forearm("right").dot(new Vector3(0, 1, 1).normalize())).toBeCloseTo(1);
  const palm = bones.rightMiddleProximal.getWorldPosition(new Vector3())
    .sub(bones.rightHand.getWorldPosition(new Vector3())).normalize();
  expect(palm.x).toBeCloseTo(1);
  const across = bones.rightLittleProximal.getWorldPosition(new Vector3())
    .sub(bones.rightIndexProximal.getWorldPosition(new Vector3())).normalize();
  expect(across.z).toBeCloseTo(1);
});
