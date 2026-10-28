/** Тесты ленты расшифровки (C8): дубли, предел и прокрутка. */

import { describe, expect, it } from "vitest";

import {
  TRANSCRIPT_MAX_LINES,
  appendTranscript,
  lastKnownSeq,
  shouldStickToBottom,
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

describe("appendTranscript", () => {
  it("добавляет фразы по порядку номеров", () => {
    let all = appendTranscript([], { seq: 1, text: "первая" });
    all = appendTranscript(all, { seq: 2, text: "вторая" });

    expect(all).toEqual(lines([1, "первая"], [2, "вторая"]));
  });

  it("не повторяет фразу с тем же или меньшим номером", () => {
    const all = appendTranscript(lines([5, "пятая"]), { seq: 5, text: "пятая" });

    expect(all).toEqual(lines([5, "пятая"]));
  });

  it("заменяет безымянную строку, а не плодит дубли", () => {
    let all = appendTranscript([], { seq: 0, text: "распознаём…" });
    all = appendTranscript(all, { seq: 0, text: "распознано" });

    expect(all).toEqual(lines([0, "распознано"]));
  });

  it("сохраняет безымянную строку перед нумерованной", () => {
    let all = appendTranscript([], { seq: 0, text: "черновик" });
    all = appendTranscript(all, { seq: 1, text: "фраза" });

    expect(all).toEqual(lines([0, "черновик"], [1, "фраза"]));
  });

  it("пропускает пустой текст", () => {
    const all = appendTranscript(lines([1, "есть"]), { seq: 2, text: "   " });

    expect(all).toEqual(lines([1, "есть"]));
  });

  it("обрезает ленту до предела, оставляя свежие строки", () => {
    let all: TranscriptLine[] = [];
    for (let seq = 1; seq <= 5; seq += 1) {
      all = appendTranscript(all, { seq, text: `фраза ${seq}` }, 3);
    }

    expect(all.map((line) => line.seq)).toEqual([3, 4, 5]);
    expect(all).toHaveLength(3);
  });

  it("с нулевым пределом лента пуста", () => {
    expect(appendTranscript([], { seq: 1, text: "фраза" }, 0)).toEqual([]);
  });

  it("не бросает на отрицательном номере", () => {
    const all = appendTranscript([], { seq: -7, text: "фраза" });

    expect(all).toEqual(lines([0, "фраза"]));
  });

  it("по умолчанию предел равен TRANSCRIPT_MAX_LINES", () => {
    let all: TranscriptLine[] = [];
    for (let seq = 1; seq <= TRANSCRIPT_MAX_LINES + 10; seq += 1) {
      all = appendTranscript(all, { seq, text: `фраза ${seq}` });
    }

    expect(all).toHaveLength(TRANSCRIPT_MAX_LINES);
    expect(all[0].seq).toBe(11);
  });
});

describe("lastKnownSeq", () => {
  it("находит наибольший номер", () => {
    expect(lastKnownSeq(lines([1, "a"], [7, "b"], [3, "c"]))).toBe(7);
    expect(lastKnownSeq(lines([0, "a"]))).toBe(0);
    expect(lastKnownSeq([])).toBe(0);
  });
});

describe("shouldStickToBottom", () => {
  it("внизу списка — прокручиваем", () => {
    expect(
      shouldStickToBottom({ scrollTop: 900, scrollHeight: 1000, clientHeight: 100 }),
    ).toBe(true);
    expect(
      shouldStickToBottom({ scrollTop: 960, scrollHeight: 1000, clientHeight: 100 }),
    ).toBe(true);
  });

  it("студент читает выше — не дёргаем ленту", () => {
    expect(
      shouldStickToBottom({ scrollTop: 100, scrollHeight: 2000, clientHeight: 400 }),
    ).toBe(false);
  });

  it("допуск задаётся в пикселях", () => {
    const metrics = { scrollTop: 500, scrollHeight: 1000, clientHeight: 400 };
    expect(shouldStickToBottom(metrics, 200)).toBe(true);
    expect(shouldStickToBottom(metrics, 50)).toBe(false);
  });

  it("лента короче окна считается прокручиваемой", () => {
    expect(
      shouldStickToBottom({ scrollTop: 0, scrollHeight: 50, clientHeight: 300 }),
    ).toBe(true);
  });
});
