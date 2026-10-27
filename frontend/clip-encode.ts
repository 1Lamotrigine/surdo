/**
 * Упаковка клипа (D2): landmarks → Float16 → gzip → base64 → JSON.
 *
 * Обратная сторона декодера C2 (`frontend/clip.ts`). Формат совпадает с
 * `docs/spec/clip-format.md`: версия 1, layout по частям скелета, данные
 * little-endian Float16. Модуль работает в браузере и в Node (vitest):
 * gzip — через нативный `CompressionStream`, base64 — через `btoa`/`Buffer`.
 */

import { CLIP_VERSION, type ClipLayout } from "./clip";

export type ClipPayload = {
  version: number;
  gloss: string;
  fps: number;
  frames: number;
  layout: ClipLayout;
  data: string;
};

export type EncodeClipOptions = {
  gloss: string;
  fps: number;
  frames: number;
  layout: ClipLayout;
  /** Плоский список `frames × points × 3` чисел в порядке layout. */
  values: ArrayLike<number>;
};

export class ClipEncodeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ClipEncodeError";
  }
}

/** Сумма точек по всем частям layout. */
export function layoutPoints(layout: ClipLayout): number {
  return Object.values(layout).reduce((sum, count) => sum + count, 0);
}

/** Число в 16-битное представление half precision (IEEE 754 binary16). */
function toFloat16Bits(value: number): number {
  if (Number.isNaN(value)) return 0x7e00;
  if (value === Infinity) return 0x7c00;
  if (value === -Infinity) return 0xfc00;

  const sign = value < 0 || Object.is(value, -0) ? 0x8000 : 0;
  const abs = Math.abs(value);
  if (abs === 0) return sign;

  const exponent = Math.floor(Math.log2(abs));
  let halfExponent = exponent + 15;

  if (halfExponent >= 0x1f) return sign | 0x7c00;
  if (halfExponent <= 0) {
    // Субнормальное число: мантисса без неявной единицы.
    return sign | Math.round(abs / 2 ** -24);
  }

  const mantissa = Math.round((abs / 2 ** exponent - 1) * 1024);
  if (mantissa === 1024) {
    halfExponent += 1;
    if (halfExponent >= 0x1f) return sign | 0x7c00;
    return sign | (halfExponent << 10);
  }
  return sign | (halfExponent << 10) | mantissa;
}

/** Записать числа как little-endian Float16. */
export function float32ToFloat16(values: ArrayLike<number>): Uint8Array {
  const buffer = new ArrayBuffer(values.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < values.length; i += 1) {
    view.setUint16(i * 2, toFloat16Bits(values[i]), true);
  }
  return new Uint8Array(buffer);
}

/** gzip через нативный `CompressionStream`. */
export async function gzip(bytes: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([bytes as BlobPart])
    .stream()
    .pipeThrough(new CompressionStream("gzip"));
  const buffer = await new Response(stream).arrayBuffer();
  return new Uint8Array(buffer);
}

/** base64 без внешних зависимостей; строку собираем кусками. */
export function bytesToBase64(bytes: Uint8Array): string {
  const bufferCtor = (globalThis as { Buffer?: { from(input: Uint8Array): { toString(encoding: string): string } } })
    .Buffer;
  if (!(globalThis as { btoa?: unknown }).btoa && bufferCtor) {
    return bufferCtor.from(bytes).toString("base64");
  }

  let binary = "";
  const chunk = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    const slice = bytes.subarray(offset, offset + chunk);
    binary += String.fromCharCode(...slice);
  }
  return btoa(binary);
}

/**
 * Собрать объект клипа с base64-данными. Проверяет размер: он должен быть
 * `frames × points × 3`, иначе клип не декодируется на другой стороне.
 */
export async function encodeClipPayload(options: EncodeClipOptions): Promise<ClipPayload> {
  const points = layoutPoints(options.layout);
  const expected = options.frames * points * 3;
  if (!Number.isInteger(options.frames) || options.frames <= 0) {
    throw new ClipEncodeError("Число кадров должно быть положительным целым.");
  }
  if (options.values.length !== expected) {
    throw new ClipEncodeError(
      `Число значений не совпадает с frames × points × 3: ${options.values.length} вместо ${expected}.`,
    );
  }

  const compressed = await gzip(float32ToFloat16(options.values));
  return {
    version: CLIP_VERSION,
    gloss: options.gloss,
    fps: options.fps,
    frames: options.frames,
    layout: { ...options.layout },
    data: bytesToBase64(compressed),
  };
}

/** Собрать содержимое файла `.json.gz` (JSON внутри gzip). */
export async function packClipFile(payload: ClipPayload): Promise<Uint8Array> {
  const json = new TextEncoder().encode(JSON.stringify(payload));
  return gzip(json);
}
