import type { VRM } from "@pixiv/three-vrm";

import type { DecodedClip } from "./clip";
import { ease, lerpFrames } from "./clip-blend";
import { splitFrame, type Landmark, type RetargetedFrame } from "./retarget";
import { retargetSlovo } from "./slovo-retarget";

function trackedHand(hand: Landmark[] | undefined, legacy: boolean): hand is Landmark[] {
  if (hand?.length !== 21) return false;
  const wrist = hand[0];
  const middle = hand[9];
  return legacy
    ? hand.some((point) => Math.abs(point.z - wrist.z) > 1e-4)
    : Math.hypot(wrist.x - middle.x, wrist.y - middle.y, wrist.z - middle.z) > 1e-4;
}

function bridgeHand(before: Landmark[], after: Landmark[], t: number): Landmark[] {
  // Мировые точки кистей имеют собственное начало координат. Смешиваем форму
  // и ориентацию относительно запястья, положение берём из позы тела.
  return before.map((point, i) => ({
    x: (point.x - before[0].x) * (1 - t) + (after[i].x - after[0].x) * t,
    y: (point.y - before[0].y) * (1 - t) + (after[i].y - after[0].y) * t,
    z: (point.z - before[0].z) * (1 - t) + (after[i].z - after[0].z) * t,
  }));
}

function handTrack(hands: (Landmark[] | undefined)[], fps: number, legacy: boolean) {
  const bridgeLimit = Math.max(1, Math.round(fps * 0.13));
  const fade = Math.max(1, Math.round(fps * 0.10));
  const tracked = hands.map((hand) => trackedHand(hand, legacy) ? hand : undefined);
  const next = new Array<number>(tracked.length);
  let nearest = Infinity;
  for (let i = tracked.length - 1; i >= 0; i -= 1) {
    if (tracked[i]) nearest = i;
    next[i] = nearest;
  }

  let previous = -Infinity;
  return tracked.map((hand, i) => {
    if (hand) {
      previous = i;
      return { hand, weight: 1 };
    }
    const after = next[i];
    if (after - previous - 1 <= bridgeLimit) {
      return { hand: bridgeHand(tracked[previous]!, tracked[after]!, (i - previous) / (after - previous)), weight: 1 };
    }
    const closest = i - previous <= after - i ? previous : after;
    const distance = Math.abs(closest - i);
    return distance <= fade
      ? { hand: tracked[closest], weight: ease(1 - distance / (fade + 1)) }
      : { hand: undefined, weight: 0 };
  });
}

/** Подготовить дорожку одного клипа с доступом к соседним исходным кадрам. */
export function prepareSlovoMotion(vrm: VRM, clip: DecodedClip, legacy: boolean): RetargetedFrame[] {
  const frames = Array.from({ length: clip.frames }, (_, i) => splitFrame(clip, i));
  const tracks = (["hand_l", "hand_r"] as const).map((part) =>
    handTrack(frames.map((frame) => frame[part]), clip.fps, legacy),
  );
  const twist = {};
  const poses = frames.map((parts, i) => {
    const [left, right] = [tracks[0][i], tracks[1][i]];
    return retargetSlovo(
      vrm,
      { ...parts, hand_l: left.hand, hand_r: right.hand },
      legacy,
      { hand_l: left.weight, hand_r: right.weight },
      twist,
    );
  });
  // Симметричное окно на поворотах сглаживает шум после решения рига.
  return poses.map((pose, i) =>
    lerpFrames(pose, lerpFrames(poses[i - 1] ?? pose, poses[i + 1] ?? pose, 0.5), 0.36),
  );
}
