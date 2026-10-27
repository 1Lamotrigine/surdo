import { describe, expect, it } from "vitest";

import {
  PhraseUploadError,
  encodeWav,
  uploadPhrase,
} from "./audio-phrase";

function readAscii(view: DataView, offset: number, length: number): string {
  return Array.from({ length }, (_, index) =>
    String.fromCharCode(view.getUint8(offset + index)),
  ).join("");
}

describe("encodeWav", () => {
  it("собирает PCM16 mono WAV 16 кГц", () => {
    const wav = encodeWav(new Float32Array([0, 1, -1, 0.5, -0.5]));
    const view = new DataView(wav.buffer);

    expect(wav.length).toBe(44 + 5 * 2);
    expect(readAscii(view, 0, 4)).toBe("RIFF");
    expect(view.getUint32(4, true)).toBe(36 + 10);
    expect(readAscii(view, 8, 4)).toBe("WAVE");
    expect(readAscii(view, 12, 4)).toBe("fmt ");
    expect(view.getUint32(16, true)).toBe(16);
    expect(view.getUint16(20, true)).toBe(1);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint32(28, true)).toBe(32_000);
    expect(view.getUint16(32, true)).toBe(2);
    expect(view.getUint16(34, true)).toBe(16);
    expect(readAscii(view, 36, 4)).toBe("data");
    expect(view.getUint32(40, true)).toBe(10);
    expect(view.getInt16(44, true)).toBe(0);
    expect(view.getInt16(46, true)).toBe(32_767);
    expect(view.getInt16(48, true)).toBe(-32_768);
    expect(view.getInt16(50, true)).toBe(16_384);
    expect(view.getInt16(52, true)).toBe(-16_384);
  });

  it("обрезает выход за диапазон и заменяет NaN тишиной", () => {
    const wav = encodeWav(new Float32Array([2, -2, Number.NaN, Infinity]));
    const view = new DataView(wav.buffer);

    expect(view.getInt16(44, true)).toBe(32_767);
    expect(view.getInt16(46, true)).toBe(-32_768);
    expect(view.getInt16(48, true)).toBe(0);
    expect(view.getInt16(50, true)).toBe(0);
  });

  it("поддерживает другую частоту и пустой фрагмент", () => {
    const wav = encodeWav(new Float32Array(0), 8_000);
    const view = new DataView(wav.buffer);

    expect(wav.length).toBe(44);
    expect(view.getUint32(24, true)).toBe(8_000);
    expect(view.getUint32(28, true)).toBe(16_000);
    expect(view.getUint32(40, true)).toBe(0);
  });

  it("отклоняет некорректную частоту", () => {
    expect(() => encodeWav(new Float32Array(0), 0)).toThrow(RangeError);
    expect(() => encodeWav(new Float32Array(0), 16_000.5)).toThrow(RangeError);
  });
});

describe("uploadPhrase", () => {
  it("отправляет multipart с полем audio, CSRF и same-origin cookies", async () => {
    let capturedUrl = "";
    let capturedInit: RequestInit | undefined;
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedInit = init;
      return new Response(JSON.stringify({ status: "accepted" }), { status: 202 });
    }) as typeof fetch;

    await uploadPhrase({
      url: "/api/rooms/ABCDEF/phrase/",
      csrfToken: "token-123",
      audio: new Uint8Array([0x52, 0x49, 0x46, 0x46]),
      filename: "fragment.wav",
      fetchImpl,
    });

    expect(capturedUrl).toBe("/api/rooms/ABCDEF/phrase/");
    expect(capturedInit?.method).toBe("POST");
    expect(capturedInit?.credentials).toBe("same-origin");
    expect((capturedInit?.headers as Record<string, string>)["X-CSRFToken"]).toBe(
      "token-123",
    );
    const form = capturedInit?.body as FormData;
    const file = form.get("audio") as File;
    expect(file.name).toBe("fragment.wav");
    expect(file.type).toBe("audio/wav");
    expect(Array.from(new Uint8Array(await file.arrayBuffer()))).toEqual([
      0x52, 0x49, 0x46, 0x46,
    ]);
  });

  it("показывает текст ошибки API и её статус", async () => {
    const fetchImpl = (async () =>
      new Response(JSON.stringify({ detail: "Комната закрыта." }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      })) as typeof fetch;

    await expect(
      uploadPhrase({
        url: "/api/rooms/ABCDEF/phrase/",
        csrfToken: "token",
        audio: new Uint8Array([1]),
        fetchImpl,
      }),
    ).rejects.toMatchObject({
      name: "PhraseUploadError",
      message: "Комната закрыта.",
      status: 404,
    });
  });

  it("не теряет код ответа, если тело не JSON", async () => {
    const fetchImpl = (async () =>
      new Response("bad gateway", { status: 502 })) as typeof fetch;

    await expect(
      uploadPhrase({
        url: "/phrase/",
        csrfToken: "token",
        audio: new Uint8Array([1]),
        fetchImpl,
      }),
    ).rejects.toMatchObject({
      message: "Сервер ответил 502.",
      status: 502,
    });
  });

  it("превращает обрыв сети в понятную ошибку", async () => {
    const fetchImpl = (async () => {
      throw new TypeError("Failed to fetch");
    }) as typeof fetch;

    await expect(
      uploadPhrase({
        url: "/phrase/",
        csrfToken: "token",
        audio: new Uint8Array([1]),
        fetchImpl,
      }),
    ).rejects.toThrow(PhraseUploadError);
  });
});
