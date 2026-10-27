import { describe, expect, it } from "vitest";

import { base64ToBytes, CLIP_VERSION, decodeClip, decodeClipPayload } from "./clip";
import {
  ClipEncodeError,
  bytesToBase64,
  encodeClipPayload,
  float32ToFloat16,
  gzip,
  layoutPoints,
  packClipFile,
} from "./clip-encode";

describe("float32ToFloat16", () => {
  it("кодирует известные half-precision значения little-endian", () => {
    const bytes = float32ToFloat16([1, 2, 0.5, -1.5]);

    expect(Array.from(bytes)).toEqual([0x00, 0x3c, 0x00, 0x40, 0x00, 0x38, 0x00, 0xbe]);
  });

  it("кодирует ноль, субнормальное значение и бесконечность", () => {
    const bytes = float32ToFloat16([0, 2 ** -24, Infinity]);
    const view = new DataView(bytes.buffer);

    expect(view.getUint16(0, true)).toBe(0);
    expect(view.getUint16(2, true)).toBe(1);
    expect(view.getUint16(4, true)).toBe(0x7c00);
  });
});

describe("base64 и gzip", () => {
  it("base64 → bytes → base64 сохраняет содержимое", () => {
    const original = new Uint8Array([0, 1, 2, 127, 128, 255]);
    const restored = base64ToBytes(bytesToBase64(original));

    expect(Array.from(restored)).toEqual(Array.from(original));
  });

  it("gzip распаковывается обратно", async () => {
    const text = new TextEncoder().encode("клип D2");
    const compressed = await gzip(text);

    expect(Array.from(compressed)).not.toEqual(Array.from(text));
  });
});

describe("encodeClipPayload", () => {
  const layout = { pose: 2, hand_l: 1 };

  it("собирает payload версии 1 и считает точки", async () => {
    const payload = await encodeClipPayload({
      gloss: "УЧЕБНИК",
      fps: 30,
      frames: 2,
      layout,
      values: Array.from({ length: 2 * 3 * 3 }, (_, index) => index / 10),
    });

    expect(payload.version).toBe(CLIP_VERSION);
    expect(payload.gloss).toBe("УЧЕБНИК");
    expect(payload.fps).toBe(30);
    expect(payload.frames).toBe(2);
    expect(payload.layout).toEqual(layout);
    expect(layoutPoints(layout)).toBe(3);
    expect(typeof payload.data).toBe("string");
  });

  it("упакованный payload декодируется C2 в исходные значения (в пределах half)", async () => {
    const values = [0, 0.5, -1, 2, 0.25, 8, -3, 4, 0.75];
    const payload = await encodeClipPayload({
      gloss: "ТЕСТ",
      fps: 30,
      frames: 1,
      layout: { pose: 1, hand_l: 1, face: 1 },
      values,
    });
    const clip = await decodeClipPayload(payload);

    expect(Array.from(clip.data)).toEqual([
      0, 0.5, -1, 2, 0.25, 8, -3, 4, 0.75,
    ]);
  });

  it("отклоняет неверное число значений", async () => {
    await expect(
      encodeClipPayload({
        gloss: "ТЕСТ",
        fps: 30,
        frames: 2,
        layout: { pose: 1 },
        values: [0, 0, 0],
      }),
    ).rejects.toThrow(ClipEncodeError);
  });

  it("файл .json.gz читается декодером C2", async () => {
    const payload = await encodeClipPayload({
      gloss: "ФАЙЛ",
      fps: 30,
      frames: 1,
      layout: { pose: 1 },
      values: [1, 2, 3],
    });
    const file = await packClipFile(payload);
    const decoded = await decodeClip(file);

    expect(decoded.gloss).toBe("ФАЙЛ");
    expect(decoded.frames).toBe(1);
    expect(Array.from(decoded.data)).toEqual([1, 2, 3]);
  });
});
