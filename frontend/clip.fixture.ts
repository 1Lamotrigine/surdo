/**
 * Фикстура клипа для тестов декодера (C2).
 *
 * Собирает настоящий файл формата `docs/spec/clip-format.md`:
 * Float16 landmarks → gzip → base64 → JSON → `.json.gz`.
 * Значения известны, поэтому тесты проверяют не только структуру,
 * но и точность Float16 → Float32.
 *
 * Файл рассчитан на окружение Node (vitest): gzip берётся из `node:zlib`.
 * В сборку клиента он не попадает — импортируется только из тестов.
 */

import { gzipSync } from "node:zlib";

/** Записать числа как Float16 (little-endian) по IEEE 754 binary16. */
export function float32ToFloat16Bytes(values: number[]): Uint8Array {
  const buffer = new ArrayBuffer(values.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < values.length; i += 1) {
    view.setUint16(i * 2, toFloat16Bits(values[i]), true);
  }
  return new Uint8Array(buffer);
}

/** Преобразовать число в 16-битное представление half precision. */
function toFloat16Bits(value: number): number {
  if (Number.isNaN(value)) return 0x7e00;
  if (value === Infinity) return 0x7c00;
  if (value === -Infinity) return 0xfc00;

  const sign = value < 0 || Object.is(value, -0) ? 0x8000 : 0;
  const abs = Math.abs(value);
  if (abs === 0) return sign;

  const exponent = Math.floor(Math.log2(abs));
  let e = exponent + 15;

  if (e >= 0x1f) return sign | 0x7c00; // переполнение → бесконечность
  if (e <= 0) {
    // Субнормальное число.
    return sign | Math.round(abs / 2 ** -24);
  }

  const mantissa = Math.round((abs / 2 ** exponent - 1) * 1024);
  if (mantissa === 1024) {
    e += 1;
    if (e >= 0x1f) return sign | 0x7c00;
    return sign | (e << 10);
  }
  return sign | (e << 10) | mantissa;
}

/** Сумма точек по всем частям `layout`. */
export function totalPoints(layout: Record<string, number>): number {
  return Object.values(layout).reduce((sum, count) => sum + count, 0);
}

/**
 * Построить предсказуемые значения landmark'ов: точка `p` кадра `f` имеет
 * координаты `(f + p/1000, p, -(f + p/1000))`. Легко проверять в тестах.
 */
export function makeValues(frames: number, points: number): number[] {
  const values: number[] = [];
  for (let f = 0; f < frames; f += 1) {
    for (let p = 0; p < points; p += 1) {
      values.push(f + p / 1000, p, -(f + p / 1000));
    }
  }
  return values;
}

export type FixtureSpec = {
  gloss?: string;
  fps?: number;
  frames: number;
  layout: Record<string, number>;
  /** Числа landmarks: длина должна быть `frames × sum(layout) × 3`. */
  values: number[];
};

export type ClipFixture = {
  /** Значения, записанные в клип. */
  values: number[];
  /** Объект клипа (то, что лежит в JSON внутри `.json.gz`). */
  payload: Record<string, unknown>;
  /** Содержимое файла `.json.gz`. */
  file: Uint8Array;
};

/** Собрать клип со всеми шагами формата и вернуть и payload, и файл. */
export function buildClipFixture(spec: FixtureSpec): ClipFixture {
  const expected = spec.frames * totalPoints(spec.layout) * 3;
  if (spec.values.length !== expected) {
    throw new Error(`values: ${spec.values.length} чисел вместо ${expected}.`);
  }

  const half = float32ToFloat16Bytes(spec.values);
  const data = Buffer.from(gzipSync(half)).toString("base64");

  const payload = {
    version: 1,
    gloss: spec.gloss ?? "ТЕСТ",
    fps: spec.fps ?? 30,
    frames: spec.frames,
    layout: spec.layout,
    data,
  };

  const file = new Uint8Array(gzipSync(Buffer.from(JSON.stringify(payload), "utf-8")));
  return { values: spec.values, payload, file };
}
