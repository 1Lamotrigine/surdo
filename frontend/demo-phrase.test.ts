/**
 * Тесты синтетической фразы (C6): клипы совпадают с единицами показа и
 * сопоставлением слов субтитра.
 */

import { describe, expect, it } from "vitest";

import { decodeClipPayload } from "./clip";
import { DEMO_PHRASE, encodePhraseClips } from "./demo-phrase";
import { alignTokens, utteranceUnits, wordIndexForToken } from "./subtitles";

describe("DEMO_PHRASE", () => {
  it("содержит жест, число и дактиль", () => {
    const kinds = DEMO_PHRASE.tokens.map((t) => t.type);
    expect(kinds).toEqual(["sign", "sign", "sign", "number", "fingerspell"]);
  });

  it("единицы показывают жесты и слово по буквам", () => {
    const units = utteranceUnits(DEMO_PHRASE);
    // 3 жеста + число + 6 букв «Иванов» = 10 единиц.
    expect(units).toHaveLength(10);
    expect(units.filter((u) => u.kind === "fingerspell")).toHaveLength(6);
  });

  it("каждая единица находит слово субтитра", () => {
    const words = alignTokens(DEMO_PHRASE);
    const units = utteranceUnits(DEMO_PHRASE);
    const indexes = units.map((unit) => wordIndexForToken(words, unit.tokenIndex));
    // Все буквы дактиля ведут к слову «Иванов» (последнее слово).
    expect(indexes.every((index) => index >= 0)).toBe(true);
    expect(indexes.slice(-6).every((index) => index === indexes[indexes.length - 1])).toBe(true);
  });
});

describe("encodePhraseClips", () => {
  it("даёт клип на каждую единицу показа", async () => {
    const payloads = await encodePhraseClips();
    expect(payloads).toHaveLength(utteranceUnits(DEMO_PHRASE).length);
  });

  it("буквы дактиля получают глоссы ДАКТИЛЬ_", async () => {
    const payloads = await encodePhraseClips();
    const glosses = payloads.map((p) => p.gloss);
    expect(glosses).toContain("ДАКТИЛЬ_И");
    expect(glosses).toContain("ДАКТИЛЬ_В");
    // Жесты и число — синтетические демо-клипы.
    expect(glosses.filter((g) => typeof g === "string" && g.startsWith("ДЕМО")).length).toBe(4);
  });

  it("все клипы декодируются и ретаргетятся", async () => {
    const payloads = await encodePhraseClips();
    const clips = await Promise.all(payloads.map((p) => decodeClipPayload(p)));
    for (const clip of clips) {
      expect(clip.frames).toBeGreaterThan(0);
      expect(clip.data.length).toBe(clip.frames * clip.points * 3);
    }
  });
});
