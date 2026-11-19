/** Тесты ленты расшифровки (C8): дубли, предел и прокрутка. */

import { describe, expect, it } from "vitest";

import {
  TRANSCRIPT_MAX_LINES,
  lastKnownSeq,
  prependTranscript,
  shouldStickToTop,
  transcriptText,
  type TranscriptLine,
} from "./transcript";

function lines(...items: [number, string][]): TranscriptLine[] {
  return items.map(([seq, text]) => ({ seq, text }));
}

describe("transcriptText", () => {
  it("сжимает пробелы и обрезает края", () => {
    expect(transcriptText("  привет   мир \n")).toBe("привет мир");
    expect(transcriptText("")).toBe("");
    expect(transcriptText("   ")).toBe("");
  });
});

describe("prependTranscript", () => {
  it("ставит свежие фразы сверху", () => {
    let all = prependTranscript([], { seq: 1, text: "первая" });
    all = prependTranscript(all, { seq: 2, text: "вторая" });

    expect(all).toEqual(lines([2, "вторая"], [1, "первая"]));
  });

  it("не повторяет фразу с тем же или меньшим номером", () => {
    const all = prependTranscript(lines([5, "пятая"]), { seq: 5, text: "пятая" });

    expect(all).toEqual(lines([5, "пятая"]));
  });

  it("заменяет безымянную строку, а не плодит дубли", () => {
    let all = prependTranscript([], { seq: 0, text: "распознаём…" });
    all = prependTranscript(all, { seq: 0, text: "распознано" });

    expect(all).toEqual(lines([0, "распознано"]));
  });

  it("заменяет безымянную строку нумерованной фразой", () => {
    let all = prependTranscript([], { seq: 0, text: "черновик" });
    all = prependTranscript(all, { seq: 1, text: "фраза" });

    expect(all).toEqual(lines([1, "фраза"]));
  });

  it("не дублирует одну фразу после asr_text и utterance", () => {
    let all = prependTranscript([], { seq: 3, text: "старая" });
    all = prependTranscript(all, { seq: 0, text: "Привет" });
    all = prependTranscript(all, { seq: 4, text: "Привет" });

    expect(all).toEqual(lines([4, "Привет"], [3, "старая"]));
  });

  it("пропускает пустой текст", () => {
    const all = prependTranscript(lines([1, "есть"]), { seq: 2, text: "   " });

    expect(all).toEqual(lines([1, "есть"]));
  });

  it("обрезает ленту до предела, оставляя свежие строки", () => {
    let all: TranscriptLine[] = [];
    for (let seq = 1; seq <= 5; seq += 1) {
      all = prependTranscript(all, { seq, text: `фраза ${seq}` }, 3);
    }

    expect(all.map((line) => line.seq)).toEqual([5, 4, 3]);
    expect(all).toHaveLength(3);
  });

  it("с нулевым пределом лента пуста", () => {
    expect(prependTranscript([], { seq: 1, text: "фраза" }, 0)).toEqual([]);
  });

  it("не бросает на отрицательном номере", () => {
    const all = prependTranscript([], { seq: -7, text: "фраза" });

    expect(all).toEqual(lines([0, "фраза"]));
  });

  it("по умолчанию предел равен TRANSCRIPT_MAX_LINES", () => {
    let all: TranscriptLine[] = [];
    for (let seq = 1; seq <= TRANSCRIPT_MAX_LINES + 10; seq += 1) {
      all = prependTranscript(all, { seq, text: `фраза ${seq}` });
    }

    expect(all).toHaveLength(TRANSCRIPT_MAX_LINES);
    expect(all[0].seq).toBe(TRANSCRIPT_MAX_LINES + 10);
    expect(all[TRANSCRIPT_MAX_LINES - 1].seq).toBe(11);
  });
});

describe("lastKnownSeq", () => {
  it("находит наибольший номер", () => {
    expect(lastKnownSeq(lines([1, "a"], [7, "b"], [3, "c"]))).toBe(7);
    expect(lastKnownSeq(lines([0, "a"]))).toBe(0);
    expect(lastKnownSeq([])).toBe(0);
  });
});

describe("shouldStickToTop", () => {
  it("наверху списка — прокручиваем", () => {
    expect(
      shouldStickToTop({ scrollTop: 0, scrollHeight: 1000, clientHeight: 100 }),
    ).toBe(true);
    expect(
      shouldStickToTop({ scrollTop: 40, scrollHeight: 1000, clientHeight: 100 }),
    ).toBe(true);
  });

  it("студент читает ниже — не дёргаем ленту", () => {
    expect(
      shouldStickToTop({ scrollTop: 900, scrollHeight: 2000, clientHeight: 400 }),
    ).toBe(false);
  });

  it("допуск задаётся в пикселях", () => {
    const metrics = { scrollTop: 100, scrollHeight: 1000, clientHeight: 400 };
    expect(shouldStickToTop(metrics, 200)).toBe(true);
    expect(shouldStickToTop(metrics, 50)).toBe(false);
  });

  it("лента короче окна считается прокручиваемой", () => {
    expect(
      shouldStickToTop({ scrollTop: 0, scrollHeight: 50, clientHeight: 300 }),
    ).toBe(true);
  });
});
