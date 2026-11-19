/// <reference types="vite/client" />

import { decodeClip, pointAt, type DecodedClip } from "./clip";
import type { HolisticFrame, Landmark } from "./skeleton";

type SignFrame = Omit<HolisticFrame, "face">;
type Features = {
  arms: number[];
  hands: (number[] | null)[];
};

export type SignReference = { text: string; frames: Features[] };

const POSE_POINTS = [11, 12, 13, 14, 15, 16];
const SAMPLE_COUNT = 20;
const MIN_FRAMES = 6;
const MAX_DISTANCE = 0.30;
const MIN_MARGIN = 0.035;

function distance(a: Landmark, b: Landmark): number {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
}

function relative(point: Landmark, origin: Landmark, scale: number): number[] {
  return [(point.x - origin.x) / scale, (point.y - origin.y) / scale, (point.z - origin.z) / scale];
}

function handFeatures(hand: Landmark[]): number[] | null {
  if (hand.length !== 21) return null;
  const scale = distance(hand[0], hand[9]);
  if (!Number.isFinite(scale) || scale < 0.02) return null;
  return hand.slice(1).flatMap((point) => relative(point, hand[0], scale));
}

export function signFeatures(frame: SignFrame): Features | null {
  const joints = POSE_POINTS.map((index) => frame.pose[index]);
  if (joints.some((point) => !point)) return null;
  const [left, right] = joints;
  const scale = distance(left, right);
  if (!Number.isFinite(scale) || scale < 0.1) return null;
  const center = { x: (left.x + right.x) / 2, y: (left.y + right.y) / 2, z: (left.z + right.z) / 2 };
  const arms = joints.slice(2).flatMap((point) => relative(point, center, scale));
  const hands = [handFeatures(frame.leftHand), handFeatures(frame.rightHand)];
  if (![...arms, ...hands.flatMap((hand) => hand ?? [])].every(Number.isFinite)) return null;
  return { arms, hands };
}

function sample(frames: Features[]): Features[] {
  const first = frames.findIndex((frame) => frame.hands.some(Boolean));
  let last = frames.length - 1;
  while (last > first && !frames[last].hands.some(Boolean)) last -= 1;
  if (first < 0 || last - first + 1 < MIN_FRAMES) return [];
  return Array.from({ length: SAMPLE_COUNT }, (_, index) =>
    frames[first + Math.round(index * (last - first) / (SAMPLE_COUNT - 1))],
  );
}

function rms(a: number[], b: number[]): number {
  return Math.sqrt(a.reduce((sum, value, index) => sum + (value - b[index]) ** 2, 0) / a.length);
}

function frameDistance(a: Features, b: Features): number {
  const hands = a.hands.map((hand, index) => {
    const other = b.hands[index];
    if (hand && other) return rms(hand, other);
    return hand || other ? 0.35 : 0;
  });
  return rms(a.arms, b.arms) * 0.65 + (hands[0] + hands[1]) * 0.25;
}

/** Сравниваем траектории с небольшим допуском на темп исполнения. */
function sequenceDistance(a: Features[], b: Features[]): number {
  let previous = Array<number>(b.length + 1).fill(Infinity);
  previous[0] = 0;
  for (let i = 1; i <= a.length; i += 1) {
    const row = Array<number>(b.length + 1).fill(Infinity);
    for (let j = Math.max(1, i - 4); j <= Math.min(b.length, i + 4); j += 1) {
      row[j] = frameDistance(a[i - 1], b[j - 1]) +
        Math.min(previous[j - 1], previous[j] + 0.03, row[j - 1] + 0.03);
    }
    previous = row;
  }
  return previous[b.length] / a.length;
}

export function recognizeSign(frames: Features[], references: SignReference[]): string | null {
  if (frames.filter((frame) => frame.hands.some(Boolean)).length < MIN_FRAMES) return null;
  const observed = sample(frames);
  const [best, runnerUp] = references
    .map((reference) => ({ text: reference.text, score: sequenceDistance(observed, reference.frames) }))
    .sort((a, b) => a.score - b.score);
  if (!best || best.score > MAX_DISTANCE || (runnerUp && runnerUp.score - best.score < MIN_MARGIN)) {
    return null;
  }
  return best.text;
}

function clipPoints(clip: DecodedClip, frame: number, start: number, length: number): Landmark[] {
  return Array.from({ length }, (_, index) => {
    const [x, y, z] = pointAt(clip, frame, start + index)!;
    return { x, y, z };
  });
}

export function referenceFromClip(clip: DecodedClip): SignReference {
  const features: Features[] = [];
  for (let i = 0; i < clip.frames; i += 1) {
    const frame = signFeatures({
      pose: clipPoints(clip, i, 0, 33),
      leftHand: clipPoints(clip, i, 33, 21),
      rightHand: clipPoints(clip, i, 54, 21),
    });
    if (frame) features.push(frame);
  }
  const frames = sample(features);
  if (!frames.length) throw new Error("Эталон жеста не содержит достаточно кадров.");
  return { text: clip.gloss.toLocaleLowerCase("ru"), frames };
}

export async function loadSignReferences(signal?: AbortSignal): Promise<SignReference[]> {
  const urls = import.meta.glob<string>("./sign-references/*.json.gz", {
    eager: true, query: "?url&no-inline", import: "default",
  });
  return Promise.all(Object.values(urls).map(async (url) => {
    const response = await fetch(url, { signal });
    if (!response.ok) throw new Error("Не удалось загрузить эталоны жестов.");
    return referenceFromClip(await decodeClip(await response.arrayBuffer()));
  }));
}
