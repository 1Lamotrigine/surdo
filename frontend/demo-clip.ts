/**
 * Синтетический клип для ручной проверки ретаргета (C3).
 *
 * В репозитории нет записанных клипов (их пишет инструмент блока D), поэтому
 * тестовая страница `/avatar/` собирает клип прямо в браузере: машущая пальцами
 * рука на фоне нейтральной стойки. Формат — как у `docs/spec/clip-format.md`.
 */

import type { ClipLayout } from "./clip";

export const DEMO_LAYOUT: ClipLayout = {
  pose: 33,
  hand_l: 21,
  hand_r: 21,
  face: 468,
};

type Point = { x: number; y: number; z: number };

const POSE = 33;
const HAND = 21;
const FACE = 468;

/** Записать число как Float16 (little-endian). */
function writeFloat16(view: DataView, offset: number, value: number): void {
  if (Number.isNaN(value)) {
    view.setUint16(offset, 0x7e00, true);
    return;
  }
  if (value === Infinity) {
    view.setUint16(offset, 0x7c00, true);
    return;
  }
  if (value === -Infinity) {
    view.setUint16(offset, 0xfc00, true);
    return;
  }
  const sign = value < 0 || Object.is(value, -0) ? 0x8000 : 0;
  const abs = Math.abs(value);
  if (abs === 0) {
    view.setUint16(offset, sign, true);
    return;
  }
  const exponent = Math.floor(Math.log2(abs));
  let e = exponent + 15;
  if (e >= 0x1f) {
    view.setUint16(offset, sign | 0x7c00, true);
    return;
  }
  if (e <= 0) {
    view.setUint16(offset, sign | Math.round(abs / 2 ** -24), true);
    return;
  }
  const mantissa = Math.round((abs / 2 ** exponent - 1) * 1024);
  if (mantissa === 1024) {
    e += 1;
    if (e >= 0x1f) {
      view.setUint16(offset, sign | 0x7c00, true);
      return;
    }
    view.setUint16(offset, sign | (e << 10), true);
    return;
  }
  view.setUint16(offset, sign | (e << 10) | mantissa, true);
}

function flatten(points: Point[]): number[] {
  const values: number[] = [];
  for (const p of points) values.push(p.x, p.y, p.z);
  return values;
}

function at<T>(list: T[], index: number, value: T): void {
  list[index] = value;
}

/** Стойка (33 точки): правая рука поднята на `wave` ∈ [0, 1]. */
function poseFrame(wave: number): Point[] {
  const lm: Point[] = Array.from({ length: POSE }, () => ({ x: 0.5, y: 0.5, z: 0 }));
  const set = (i: number, x: number, y: number) => at(lm, i, { x, y, z: 0 });

  set(0, 0.5, 0.2);
  set(11, 0.42, 0.3); // правое плечо
  set(12, 0.58, 0.3); // левое плечо
  set(13, 0.4, 0.4); // правый локоть
  set(15, 0.4, 0.25 - wave * 0.05); // правая кисть (поднята)
  set(14, 0.6, 0.45);
  set(16, 0.6, 0.6);
  set(17, 0.4, 0.27);
  set(19, 0.4, 0.29);
  set(18, 0.6, 0.62);
  set(20, 0.6, 0.64);
  set(23, 0.44, 0.7);
  set(24, 0.56, 0.7);
  set(25, 0.44, 0.85);
  set(26, 0.56, 0.85);
  return lm;
}

/** Кисть (21 точка): пальцы сгибаются на `curl` ∈ [0, 1]. */
function handFrame(curl: number, side: "left" | "right"): Point[] {
  const sign = side === "right" ? 1 : -1;
  const lm: Point[] = Array.from({ length: HAND }, () => ({ x: 0.5, y: 0.5, z: 0 }));
  const set = (i: number, x: number, y: number) => at(lm, i, { x, y, z: 0 });

  // Кисть в поднятом положении (совпадает с позой 15/16).
  set(0, 0.4, 0.2);
  const fingers: [number, number, number, number, number][] = [
    [1, 2, 3, 4, 0.06],
    [5, 6, 7, 8, 0.02],
    [9, 10, 11, 12, 0.0],
    [13, 14, 15, 16, -0.02],
    [17, 18, 19, 20, -0.04],
  ];
  for (const [mcp, pip, dip, tip, offset] of fingers) {
    const x = 0.4 + sign * offset;
    set(mcp, x, 0.2);
    // curl=0 — ладонь раскрыта, curl=1 — пальцы согнуты к ладони.
    set(pip, x, 0.17 + 0.02 * curl);
    set(dip, x + 0.02 * curl, 0.15 + 0.05 * curl);
    set(tip, x + 0.01 * curl, 0.13 + 0.08 * curl);
  }
  return lm;
}

/** Лицо (468 точек): глаза открыты, рот закрыт. */
function faceFrame(): Point[] {
  const lm: Point[] = Array.from({ length: FACE }, () => ({ x: 0.5, y: 0.25, z: 0 }));
  const set = (i: number, x: number, y: number) => at(lm, i, { x, y, z: 0 });

  set(21, 0.44, 0.19);
  set(251, 0.56, 0.19);
  set(397, 0.56, 0.31);
  set(172, 0.44, 0.31);
  set(13, 0.5, 0.28);
  set(14, 0.5, 0.3);
  set(61, 0.47, 0.29);
  set(291, 0.53, 0.29);
  set(133, 0.48, 0.25);
  set(362, 0.52, 0.25);
  set(130, 0.46, 0.25);
  set(263, 0.54, 0.25);
  return lm;
}

/** Числа кадров демо-клипа: раскрытие/сжатие пальцев и покачивание кисти. */
function demoValues(frames: number): number[] {
  const values: number[] = [];
  for (let f = 0; f < frames; f += 1) {
    const phase = (f / frames) * Math.PI * 2;
    const wave = 0.5 + 0.5 * Math.sin(phase);
    const curl = 0.5 + 0.5 * Math.sin(phase * 2);
    values.push(
      ...flatten(poseFrame(wave)),
      ...flatten(handFrame(curl, "left")),
      ...flatten(handFrame(1 - curl, "right")),
      ...flatten(faceFrame()),
    );
  }
  return values;
}

/** Записать числа как Float16 (little-endian). */
function encodeFloat16(values: number[]): Uint8Array {
  const buffer = new ArrayBuffer(values.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < values.length; i += 1) writeFloat16(view, i * 2, values[i]);
  return new Uint8Array(buffer);
}

/**
 * Собрать клип «машущая рука»: пальцы раскрываются и сжимаются, кисть чуть
 * покачивается. Возвращает объект клипа, готовый к загрузке через `decodeClip`
 * после gzip (см. `encodeDemoClip`).
 */
export function buildDemoClipPayload(frames = 45, fps = 30): Record<string, unknown> {
  return {
    version: 1,
    gloss: "ДЕМО",
    fps,
    frames,
    layout: DEMO_LAYOUT,
    data: "",
  };
}

/** Собрать готовый объект клипа с base64-данными (gzip в браузере). */
export async function encodeDemoClip(frames = 45, fps = 30): Promise<Record<string, unknown>> {
  const payload = buildDemoClipPayload(frames, fps);
  const compressed = await gzip(encodeFloat16(demoValues(frames)));
  payload.data = bytesToBase64(compressed);
  return payload;
}

/** gzip через нативный `CompressionStream`. */
async function gzip(bytes: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([bytes as BlobPart]).stream().pipeThrough(new CompressionStream("gzip"));
  const buffer = await new Response(stream).arrayBuffer();
  return new Uint8Array(buffer);
}

/** base64 без внешних зависимостей. */
function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
