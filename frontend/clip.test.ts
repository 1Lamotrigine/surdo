/**
 * Тесты декодера формата клипа (C2).
 *
 * Проверяют всю цепочку: `.json.gz` → JSON → base64 → gzip → Float16 → массивы,
 * а также точность Float16 → Float32 и ошибки формата.
 */

import { describe, expect, it } from "vitest";

import {
  CLIP_VERSION,
  ClipDecodeError,
  base64ToBytes,
  decodeClip,
  decodeClipPayload,
  float16ToFloat32,
  gunzip,
  pointAt,
  readFloat16,
} from "./clip";
import { buildClipFixture, float32ToFloat16Bytes, makeValues, totalPoints } from "./clip.fixture";

const LAYOUT = { pose: 4, hand_l: 3, hand_r: 3, face: 5 };
const POINTS = totalPoints(LAYOUT);
const FRAMES = 3;

function smallFixture() {
  const values = makeValues(FRAMES, POINTS);
  return buildClipFixture({ frames: FRAMES, layout: LAYOUT, values });
}

describe("Float16", () => {
  it("читает известные half-precision значения", () => {
    // Эталонные биты: 1.0 = 0x3C00, 2.0 = 0x4000, 0.5 = 0x3800, -1.5 = 0xBE00.
    const bytes = new Uint8Array([0x00, 0x3c, 0x00, 0x40, 0x00, 0x38, 0x00, 0xbe]);
    const view = new DataView(bytes.buffer);

    expect(readFloat16(view, 0)).toBe(1);
    expect(readFloat16(view, 2)).toBe(2);
    expect(readFloat16(view, 4)).toBe(0.5);
    expect(readFloat16(view, 6)).toBe(-1.5);
  });

  it("читает ноль и субнормальные значения", () => {
    const bytes = new Uint8Array([0x00, 0x00, 0x00, 0x80, 0x01, 0x00]);
    const view = new DataView(bytes.buffer);

    expect(readFloat16(view, 0)).toBe(0);
    expect(Object.is(readFloat16(view, 2), -0)).toBe(true);
    expect(readFloat16(view, 4)).toBeCloseTo(2 ** -24, 10);
  });

  it("переводит массив байтов в Float32Array", () => {
    const bytes = float32ToFloat16Bytes([1, -2, 0.25]);
    const result = float16ToFloat32(bytes);

    expect(Array.from(result)).toEqual([1, -2, 0.25]);
  });

  it("падает на нечётной длине буфера", () => {
    expect(() => float16ToFloat32(new Uint8Array([1, 2, 3]))).toThrow(ClipDecodeError);
  });

  it("roundtrip через фикстуру сохраняет значения (в пределах точности half)", () => {
    const values = [0, 1, -1, 0.5, 8.5];
    const decoded = float16ToFloat32(float32ToFloat16Bytes(values));

    expect(Array.from(decoded)).toEqual(values);

    // Большие значения теряют точность — проверяем относительную погрешность half.
    const big = float16ToFloat32(float32ToFloat16Bytes([123.456]));
    expect(Math.abs(big[0] - 123.456) / 123.456).toBeLessThan(2 ** -10);
  });
});

describe("base64", () => {
  it("декодирует в те же байты", () => {
    const original = new Uint8Array([0, 1, 2, 250, 255]);
    const base64 = Buffer.from(original).toString("base64");

    expect(Array.from(base64ToBytes(base64))).toEqual(Array.from(original));
  });

  it("игнорирует пробелы и переводы строк", () => {
    const base64 = Buffer.from(new Uint8Array([1, 2, 3])).toString("base64");
    const spaced = `${base64.slice(0, 2)}\n  ${base64.slice(2)}`;

    expect(Array.from(base64ToBytes(spaced))).toEqual([1, 2, 3]);
  });

  it("отклоняет пустую строку и мусор", () => {
    expect(() => base64ToBytes("")).toThrow(ClipDecodeError);
    expect(() => base64ToBytes("не base64!")).toThrow(ClipDecodeError);
  });
});

describe("gunzip", () => {
  it("распаковывает gzip-поток", async () => {
    const text = new TextEncoder().encode("привет, клип");
    const compressed = new Uint8Array(Buffer.from(await import("node:zlib").then((z) => z.gzipSync(text))));

    const restored = await gunzip(compressed);

    expect(new TextDecoder().decode(restored)).toBe("привет, клип");
  });
});

describe("decodeClipPayload", () => {
  it("разбирает layout в точки и смещения", async () => {
    const fixture = smallFixture();
    const clip = await decodeClipPayload(fixture.payload);

    expect(clip.version).toBe(CLIP_VERSION);
    expect(clip.fps).toBe(30);
    expect(clip.frames).toBe(FRAMES);
    expect(clip.points).toBe(POINTS);
    expect(clip.components).toBe(3);
    expect(clip.layout).toEqual(LAYOUT);
    expect(clip.offsets).toEqual({
      pose: { start: 0, count: 4 },
      hand_l: { start: 4, count: 3 },
      hand_r: { start: 7, count: 3 },
      face: { start: 10, count: 5 },
    });
  });

  it("восстанавливает значения landmark'ов по кадрам", async () => {
    const fixture = smallFixture();
    const clip = await decodeClipPayload(fixture.payload);

    expect(clip.data.length).toBe(FRAMES * POINTS * 3);
    // Точка 0 кадра 2: (2, 0, -2).
    expect(pointAt(clip, 2, 0)).toEqual([2, 0, -2]);
    // Точка 5 кадра 1: (1.005, 5, -1.005) — в пределах точности half.
    const point = pointAt(clip, 1, 5);
    expect(point?.[0]).toBeCloseTo(1.005, 2);
    expect(point?.[1]).toBe(5);
    expect(point?.[2]).toBeCloseTo(-1.005, 2);
  });

  it("возвращает null для точки вне диапазона", async () => {
    const clip = await decodeClipPayload(smallFixture().payload);

    expect(pointAt(clip, FRAMES, 0)).toBeNull();
    expect(pointAt(clip, 0, POINTS)).toBeNull();
    expect(pointAt(clip, -1, 0)).toBeNull();
  });

  it("сохраняет глоссу и язык метаданных", async () => {
    const fixture = buildClipFixture({
      gloss: "УЧЕБНИК",
      frames: 1,
      layout: { pose: 1 },
      values: [1, 2, 3],
    });
    const clip = await decodeClipPayload(fixture.payload);

    expect(clip.gloss).toBe("УЧЕБНИК");
  });
});

describe("decodeClip (файл .json.gz)", () => {
  it("читает файл целиком: gzip → JSON → массивы", async () => {
    const fixture = smallFixture();
    const clip = await decodeClip(fixture.file);

    expect(clip.frames).toBe(FRAMES);
    expect(clip.points).toBe(POINTS);
    // Точка 0 кадра 0: (0, 0, -0) — отрицательный ноль сохраняется Float16.
    expect(pointAt(clip, 0, 0)?.slice(0, 2)).toEqual([0, 0]);
    expect(pointAt(clip, 0, 0)?.[2]).toBeCloseTo(0, 10);
    expect(clip.gloss).toBe("ТЕСТ");
  });

  it("принимает ArrayBuffer", async () => {
    const fixture = smallFixture();
    const buffer = fixture.file.buffer.slice(
      fixture.file.byteOffset,
      fixture.file.byteOffset + fixture.file.byteLength,
    ) as ArrayBuffer;

    const clip = await decodeClip(buffer);

    expect(clip.frames).toBe(FRAMES);
  });
});

describe("ошибки формата", () => {
  it("отклоняет неподдерживаемую версию", async () => {
    const fixture = smallFixture();
    const payload = { ...fixture.payload, version: 99 };

    await expect(decodeClipPayload(payload)).rejects.toThrow(ClipDecodeError);
  });

  it("отклоняет отрицательный fps и нецелые frames", async () => {
    const fixture = smallFixture();

    await expect(decodeClipPayload({ ...fixture.payload, fps: 0 })).rejects.toThrow(
      ClipDecodeError,
    );
    await expect(decodeClipPayload({ ...fixture.payload, frames: 1.5 })).rejects.toThrow(
      ClipDecodeError,
    );
  });

  it("отклоняет пустой layout", async () => {
    const fixture = smallFixture();

    await expect(decodeClipPayload({ ...fixture.payload, layout: {} })).rejects.toThrow(
      ClipDecodeError,
    );
  });

  it("отклоняет нечисловые значения в layout", async () => {
    const fixture = smallFixture();

    await expect(
      decodeClipPayload({ ...fixture.payload, layout: { pose: "много" } }),
    ).rejects.toThrow(ClipDecodeError);
  });

  it("отклоняет пустые data", async () => {
    const fixture = smallFixture();

    await expect(decodeClipPayload({ ...fixture.payload, data: "" })).rejects.toThrow(
      ClipDecodeError,
    );
  });

  it("отклоняет данные, не совпадающие с frames × points × 3", async () => {
    const fixture = smallFixture();
    // Меньше чисел, чем требует layout.
    const short = buildClipFixture({
      frames: 1,
      layout: { pose: 1 },
      values: [1, 2, 3],
    });
    const payload = { ...short.payload, frames: 10 };

    await expect(decodeClipPayload(payload)).rejects.toThrow(/frames × points × 3/);
    // Исходная фикстура остаётся валидной.
    await expect(decodeClipPayload(fixture.payload)).resolves.toBeTruthy();
  });

  it("отклоняет не-gzip файл", async () => {
    const notGzip = new TextEncoder().encode("это не gzip");

    await expect(decodeClip(notGzip)).rejects.toThrow();
  });

  it("отклоняет gzip с не-JSON внутри", async () => {
    const { gzipSync } = await import("node:zlib");
    const file = new Uint8Array(gzipSync(Buffer.from("не json", "utf-8")));

    await expect(decodeClip(file)).rejects.toThrow(ClipDecodeError);
  });

  it("отклоняет массив вместо объекта", async () => {
    await expect(decodeClipPayload([1, 2, 3])).rejects.toThrow(ClipDecodeError);
  });
});
