/**
 * Тесты клипов живой фразы (E3): порядок ссылок, загрузка и очередь показа.
 */

import { describe, expect, it, vi } from "vitest";

import type { DecodedClip } from "./clip";
import {
  PhraseQueue,
  clipRefsFromEvent,
  loadClipQueue,
  type UtteranceEvent,
} from "./room-clips";

function decoded(gloss: string): DecodedClip {
  return {
    version: 1,
    gloss,
    fps: 30,
    frames: 30,
    points: 1,
    components: 3,
    layout: { pose: 1 },
    data: new Float32Array([0, 0, 0]),
    offsets: { pose: { start: 0, count: 1 } },
  };
}

const UTTERANCE: UtteranceEvent = {
  id: 1,
  seq: 1,
  text: "Учебник Иванов",
  degraded: false,
  ts: "2026-10-27T10:00:00+00:00",
  glosses: {
    text: "Учебник Иванов",
    tokens: [
      { type: "sign", gloss: "УЧЕБНИК", src: "Учебник" },
      { type: "fingerspell", letters: ["И", "В"], src: "Иванов" },
    ],
  },
  clips: [
    { token_index: 0, kind: "sign", gloss: "УЧЕБНИК", url: "/media/u.json.gz" },
    { token_index: 1, kind: "fingerspell", gloss: "ДАКТИЛЬ_И", url: "/media/i.json.gz" },
    { token_index: 1, kind: "fingerspell", gloss: "ДАКТИЛЬ_В", url: "/media/v.json.gz" },
  ],
};

describe("clipRefsFromEvent", () => {
  it("сохраняет серверный порядок и отбрасывает мусор", () => {
    const event = {
      ...UTTERANCE,
      clips: [
        UTTERANCE.clips?.[1],
        { token_index: "0", url: 42 },
        UTTERANCE.clips?.[0],
      ],
    } as unknown as UtteranceEvent;

    const refs = clipRefsFromEvent(event);

    expect(refs.map((ref) => ref.url)).toEqual([
      "/media/i.json.gz",
      "/media/u.json.gz",
    ]);
    expect(refs.map((ref) => ref.kind)).toEqual(["fingerspell", "sign"]);
  });

  it("без поля clips возвращает пустой список", () => {
    expect(clipRefsFromEvent({ ...UTTERANCE, clips: undefined })).toEqual([]);
  });
});

describe("loadClipQueue", () => {
  it("загружает клипы параллельно и сопоставляет их словам", async () => {
    const fetcher = vi.fn(async (url: string) => new Uint8Array([url.length]));
    const decoder = vi.fn(async () => decoded("X"));

    const loaded = await loadClipQueue(UTTERANCE, { fetcher, decoder });

    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/media/u.json.gz",
      "/media/i.json.gz",
      "/media/v.json.gz",
    ]);
    expect(loaded.map((item) => item.wordIndex)).toEqual([0, 1, 1]);
    expect(loaded.map((item) => item.ref.gloss)).toEqual([
      "УЧЕБНИК",
      "ДАКТИЛЬ_И",
      "ДАКТИЛЬ_В",
    ]);
  });

  it("пропускает битый клип, сохраняя остальные", async () => {
    const errors: string[] = [];
    const fetcher = vi.fn(async (url: string) => {
      if (url.includes("/i.")) throw new Error("404");
      return new Uint8Array([1]);
    });
    const decoder = vi.fn(async () => decoded("X"));

    const loaded = await loadClipQueue(UTTERANCE, {
      fetcher,
      decoder,
      onError: (ref) => errors.push(ref.url),
    });

    expect(errors).toEqual(["/media/i.json.gz"]);
    expect(loaded.map((item) => item.ref.url)).toEqual([
      "/media/u.json.gz",
      "/media/v.json.gz",
    ]);
  });
});

describe("PhraseQueue", () => {
  it("играет фразы строго по одной и отбрасывает повторы по seq", async () => {
    const seen: number[] = [];
    let active = 0;
    let maxActive = 0;
    const queue = new PhraseQueue<{ seq: number }>(async (item) => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      seen.push(item.seq);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active -= 1;
    });

    expect(queue.enqueue({ seq: 1 })).toBe(true);
    expect(queue.enqueue({ seq: 2 })).toBe(true);
    expect(queue.enqueue({ seq: 2 })).toBe(false);
    expect(queue.enqueue({ seq: 1 })).toBe(false);
    await queue.waitForIdle();

    expect(seen).toEqual([1, 2]);
    expect(maxActive).toBe(1);
  });

  it("после ошибки одной фразы продолжает очередь", async () => {
    const seen: number[] = [];
    const errors: number[] = [];
    const queue = new PhraseQueue<{ seq: number }>(
      async (item) => {
        seen.push(item.seq);
        if (item.seq === 1) throw new Error("broken clip");
      },
      { onError: (_error, item) => errors.push(item.seq) },
    );

    queue.enqueue({ seq: 1 });
    queue.enqueue({ seq: 2 });
    await queue.waitForIdle();

    expect(seen).toEqual([1, 2]);
    expect(errors).toEqual([1]);
  });
});
