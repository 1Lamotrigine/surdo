/**
 * Декодер формата клипа (C2): `base64` → `gzip` → `Float16` в массивы.
 *
 * Формат файла (``docs/spec/clip-format.md``, 7.5):
 *
 * ```json
 * {
 *   "version": 1,
 *   "gloss": "УЧЕБНИК",
 *   "fps": 30,
 *   "frames": 54,
 *   "layout": {"pose": 33, "hand_l": 21, "hand_r": 21, "face": 468},
 *   "data": "<base64 gzip Float16 [frames x points x 3]>"
 * }
 * ```
 *
 * Модуль не зависит от Three.js и DOM: на вход байты или разобранный объект,
 * на выходе числа. Это делает его пригодным и в браузере, и в vitest.
 */

/** Поддерживаемая версия формата. Должна совпадать с `CLIP_VERSION` на сервере. */
export const CLIP_VERSION = 1;

/** Сколько компонент на точку: x, y, z. */
export const COMPONENTS_PER_POINT = 3;

/** Части скелета и число точек в каждой (ключи `layout`). */
export type ClipLayout = Record<string, number>;

/** Клип, разобранный в массивы, готовый к ретаргету (C3). */
export type DecodedClip = {
  version: number;
  gloss: string;
  fps: number;
  frames: number;
  /** Число точек на кадр (сумма `layout`). */
  points: number;
  /** Число компонент на точку (всегда 3). */
  components: number;
  layout: ClipLayout;
  coordinate_space?: "mediapipe-world";
  /**
   * Landmarks: `frames * points * components` чисел, по кадру за раз
   * (порядок точек — как в `layout`).
   */
  data: Float32Array;
  /** Смещения частей в точках: `start` и `count` для быстрого доступа. */
  offsets: Record<string, { start: number; count: number }>;
};

/** Ошибка формата клипа: файл не соответствует спецификации. */
export class ClipDecodeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ClipDecodeError";
  }
}

/**
 * Координаты точки `point` (в глобальной нумерации кадра) кадра `frame`
 * как `[x, y, z]`. Возвращает `null`, если индексы вне диапазона.
 */
export function pointAt(clip: DecodedClip, frame: number, point: number): [number, number, number] | null {
  if (frame < 0 || frame >= clip.frames) return null;
  if (point < 0 || point >= clip.points) return null;
  const base = (frame * clip.points + point) * clip.components;
  return [clip.data[base], clip.data[base + 1], clip.data[base + 2]];
}

/** Декодировать base64 в байты без зависимости от `atob` (работает и в Node). */
export function base64ToBytes(base64: string): Uint8Array {
  const normalized = base64.replace(/\s+/g, "");
  if (normalized.length === 0) {
    throw new ClipDecodeError("Поле data пустое.");
  }
  if (normalized.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(normalized)) {
    throw new ClipDecodeError("Поле data не является корректным base64.");
  }

  // Доступ к декодеру base64: `atob` в браузере, `Buffer` в Node (vitest).
  const bufferCtor = (globalThis as { Buffer?: { from(input: string, encoding: string): Uint8Array } })
    .Buffer;
  if (typeof globalThis.atob === "function") {
    const binary = globalThis.atob(normalized);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }
  if (bufferCtor) {
    return new Uint8Array(bufferCtor.from(normalized, "base64"));
  }
  throw new ClipDecodeError("Нет доступного декодера base64 (ни atob, ни Buffer).");
}

/** Распаковать gzip через нативный `DecompressionStream`. */
export async function gunzip(compressed: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([compressed as BlobPart])
    .stream()
    .pipeThrough(new DecompressionStream("gzip"));
  const buffer = await new Response(stream).arrayBuffer();
  return new Uint8Array(buffer);
}

/**
 * Прочитать Float16 (half precision) по смещению и вернуть число
 * одинарной точности. Реализация по IEEE 754 binary16.
 */
export function readFloat16(view: DataView, byteOffset: number): number {
  const bits = view.getUint16(byteOffset, true);
  const sign = bits & 0x8000 ? -1 : 1;
  const exponent = (bits >> 10) & 0x1f;
  const fraction = bits & 0x03ff;

  if (exponent === 0) {
    // Субнормальное число либо ноль.
    return sign * fraction * 2 ** -24;
  }
  if (exponent === 0x1f) {
    if (fraction === 0) return sign * Infinity;
    return Number.NaN;
  }
  const mantissa = 1 + fraction / 1024;
  return sign * mantissa * 2 ** (exponent - 15);
}

/** Преобразовать буфер little-endian Float16 в `Float32Array`. */
export function float16ToFloat32(bytes: Uint8Array): Float32Array {
  if (bytes.byteLength % 2 !== 0) {
    throw new ClipDecodeError("Данные Float16 должны иметь чётную длину.");
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const count = bytes.byteLength / 2;
  const out = new Float32Array(count);
  // `readFloat16` читает по 2 байта за раз: цикл предсказуем для компилятора.
  for (let i = 0; i < count; i += 1) {
    out[i] = readFloat16(view, i * 2);
  }
  return out;
}

/** Проверить и нормализовать объект клипа (после `JSON.parse`). */
function validatePayload(payload: unknown): {
  version: number;
  gloss: string;
  fps: number;
  frames: number;
  layout: ClipLayout;
  coordinate_space?: "mediapipe-world";
  data: string;
} {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new ClipDecodeError("Ожидался JSON-объект клипа.");
  }
  const clip = payload as Record<string, unknown>;

  const version = clip.version;
  if (version !== CLIP_VERSION) {
    throw new ClipDecodeError(
      `Версия формата клипа ${String(version)} не поддерживается (ожидается ${CLIP_VERSION}).`,
    );
  }

  const fps = clip.fps;
  if (typeof fps !== "number" || !Number.isFinite(fps) || fps <= 0) {
    throw new ClipDecodeError("Поле fps должно быть положительным числом.");
  }

  const frames = clip.frames;
  if (typeof frames !== "number" || !Number.isInteger(frames) || frames <= 0) {
    throw new ClipDecodeError("Поле frames должно быть положительным целым числом.");
  }

  const layout = clip.layout;
  if (typeof layout !== "object" || layout === null || Array.isArray(layout)) {
    throw new ClipDecodeError("Поле layout должно быть непустым объектом.");
  }
  for (const [part, count] of Object.entries(layout as Record<string, unknown>)) {
    if (typeof count !== "number" || !Number.isInteger(count) || count <= 0) {
      throw new ClipDecodeError(`Часть layout «${part}» должна быть положительным целым числом.`);
    }
  }
  if (Object.keys(layout).length === 0) {
    throw new ClipDecodeError("Поле layout должно быть непустым объектом.");
  }

  const data = clip.data;
  if (typeof data !== "string" || data.length === 0) {
    throw new ClipDecodeError("Поле data должно быть непустой строкой base64.");
  }

  const gloss = typeof clip.gloss === "string" ? clip.gloss : "";

  return {
    version,
    gloss,
    fps,
    frames,
    layout: layout as ClipLayout,
    ...(clip.coordinate_space === "mediapipe-world" ? { coordinate_space: clip.coordinate_space } : {}),
    data,
  };
}

/** Посчитать смещения частей и общее число точек по `layout`. */
function computeOffsets(layout: ClipLayout): {
  offsets: DecodedClip["offsets"];
  points: number;
} {
  const offsets: DecodedClip["offsets"] = {};
  let start = 0;
  for (const [part, count] of Object.entries(layout)) {
    offsets[part] = { start, count };
    start += count;
  }
  return { offsets, points: start };
}

/**
 * Разобрать объект клипа (уже `JSON.parse`) в массивы.
 * Асинхронно: gzip распаковывается через `DecompressionStream`.
 * Проверяет размер данных: он должен совпадать с `frames * points * 3 * 2`.
 */
export async function decodeClipPayload(payload: unknown): Promise<DecodedClip> {
  const { data, ...metadata } = validatePayload(payload);
  const { offsets, points } = computeOffsets(metadata.layout);

  const compressed = base64ToBytes(data);
  const raw = await gunzip(compressed);
  const values = float16ToFloat32(raw);

  const expected = metadata.frames * points * COMPONENTS_PER_POINT;
  if (values.length !== expected) {
    throw new ClipDecodeError(
      `Число значений не совпадает с frames × points × 3: ${values.length} вместо ${expected}.`,
    );
  }

  return {
    ...metadata,
    points,
    components: COMPONENTS_PER_POINT,
    data: values,
    offsets,
  };
}

/**
 * Декодировать клип из содержимого файла `.json.gz`:
 * `gzip` → `JSON` → `decodeClipPayload`.
 */
export async function decodeClip(input: ArrayBuffer | Uint8Array): Promise<DecodedClip> {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  const json = await gunzip(bytes);
  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder().decode(json));
  } catch {
    throw new ClipDecodeError("Внутри клипа не JSON.");
  }
  return decodeClipPayload(payload);
}
