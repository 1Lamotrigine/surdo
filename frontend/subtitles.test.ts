/**
 * Тесты субтитров (C6).
 *
 * Критерий этапа — «тест соответствия токена и слова». Здесь проверяются:
 * сопоставление токенов глосс словам исходного текста, раскладка токенов в
 * единицы показа (один клип = одна единица, дактиль по буквам), подсветка
 * текущего слова по времени очереди (C4) и размер/контраст (CSS-классы).
 */

import { describe, expect, it } from "vitest";

import { planQueue, type QueuePlan } from "./clip-queue";
import {
  SUBTITLE_SIZES,
  SUBTITLE_THEMES,
  activeTokenAt,
  activeWordAt,
  alignTokens,
  normalizeWord,
  segmentsToTokens,
  splitTextWords,
  subtitlePieces,
  subtitleSizeClass,
  subtitleThemeClass,
  tokenGloss,
  utteranceUnits,
  wordIndexForToken,
  type UtteranceGlosses,
} from "./subtitles";

/** Клип для планировщика: 1 секунда при 30 FPS. */
function clip() {
  return { duration: 1, fps: 30, frames: 30 };
}

/** План очереди из `n` клипов. */
function plan(n: number): QueuePlan {
  return planQueue(Array.from({ length: n }, clip));
}

const UTTERANCE: UtteranceGlosses = {
  text: "Откройте учебник на странице десять",
  lang: "rsl",
  sentence_type: "imperative",
  tokens: [
    { type: "sign", gloss: "ОТКРЫТЬ", src: "Откройте" },
    { type: "sign", gloss: "УЧЕБНИК", src: "учебник" },
    { type: "sign", gloss: "СТРАНИЦА", src: "странице" },
    { type: "number", value: 10, src: "десять" },
  ],
};

describe("normalizeWord", () => {
  it("приводит регистр, ё и убирает пунктуацию", () => {
    expect(normalizeWord("Учебник")).toBe("учебник");
    expect(normalizeWord("Всё,")).toBe("все");
    expect(normalizeWord("«книга»")).toBe("книга");
  });
});

describe("splitTextWords", () => {
  it("находит слова с диапазонами без пунктуации", () => {
    const words = splitTextWords("Да, нет! Иван.");
    expect(words.map((w) => w.word)).toEqual(["Да", "нет", "Иван"]);
    const [first] = words;
    expect(first.start).toBe(0);
    expect(first.end).toBe(2);
  });

  it("включает цифры", () => {
    expect(splitTextWords("дом 42").map((w) => w.word)).toEqual(["дом", "42"]);
  });
});

describe("alignTokens", () => {
  it("сопоставляет токены словам текста в порядке следования", () => {
    const words = alignTokens(UTTERANCE);
    expect(words.map((w) => w.text)).toEqual(["Откройте", "учебник", "странице", "десять"]);
    expect(words.map((w) => w.tokenIndex)).toEqual([0, 1, 2, 3]);
  });

  it("пропускает слова текста без жеста (на)", () => {
    const words = alignTokens(UTTERANCE);
    // «на» нет среди слов субтитра — оно не сопоставлено ни одному токену.
    expect(words.some((w) => w.text === "на")).toBe(false);
  });

  it("берёт точные диапазоны в тексте", () => {
    const words = alignTokens(UTTERANCE);
    const [first, second] = words;
    expect(UTTERANCE.text.slice(first.start, first.end)).toBe("Откройте");
    expect(UTTERANCE.text.slice(second.start, second.end)).toBe("учебник");
  });

  it("не путает повторяющиеся слова (курсор только вперёд)", () => {
    const utterance: UtteranceGlosses = {
      text: "дом и ещё дом",
      tokens: [
        { type: "sign", gloss: "ДОМ", src: "дом" },
        { type: "sign", gloss: "ЕЩЁ", src: "ещё" },
        { type: "sign", gloss: "ДОМ", src: "дом" },
      ],
    };
    const words = alignTokens(utterance);
    expect(words.map((w) => w.start)).toEqual([0, 6, 10]);
    expect(words[0].start).not.toBe(words[2].start);
  });

  it("мирится с леммой: порядок важнее формы", () => {
    const utterance: UtteranceGlosses = {
      text: "Учебник на столе",
      tokens: [
        { type: "sign", gloss: "УЧЕБНИК", src: "УЧЕБНИКЕ" },
        { type: "sign", gloss: "СТОЛ", src: "столе" },
      ],
    };
    const words = alignTokens(utterance);
    expect(words.map((w) => w.text)).toEqual(["Учебник", "столе"]);
  });

  it("пропускает токены без источника", () => {
    const utterance: UtteranceGlosses = {
      text: "Привет",
      tokens: [
        { type: "sign", gloss: "ПРИВЕТ", src: "Привет" },
        { type: "sign", gloss: "ПУСТОЙ", src: "" },
      ],
    };
    expect(alignTokens(utterance)).toHaveLength(1);
  });

  it("на пустом тексте даёт пустой список", () => {
    expect(alignTokens({ text: "", tokens: [{ type: "sign", gloss: "X", src: "X" }] })).toEqual([]);
  });
});

describe("tokenGloss", () => {
  it("строит глоссы жеста, числа и буквы дактиля", () => {
    expect(tokenGloss({ type: "sign", gloss: "УЧЕБНИК", src: "учебник" })).toBe("УЧЕБНИК");
    expect(tokenGloss({ type: "number", value: 10, src: "десять" })).toBe("ЦИФРА_10");
    expect(tokenGloss({ type: "fingerspell", letters: ["И", "В"], src: "Ив" })).toBe("ДАКТИЛЬ_И");
  });

  it("возвращает null без глоссы", () => {
    expect(tokenGloss({ type: "sign", src: "x" })).toBeNull();
  });
});

describe("utteranceUnits", () => {
  it("даёт по единице на жест и на цифру", () => {
    const units = utteranceUnits(UTTERANCE);
    expect(units.map((u) => u.gloss)).toEqual(["ОТКРЫТЬ", "УЧЕБНИК", "СТРАНИЦА", "ЦИФРА_10"]);
    expect(units.map((u) => u.tokenIndex)).toEqual([0, 1, 2, 3]);
  });

  it("дактиль разворачивает в единицы по буквам", () => {
    const utterance: UtteranceGlosses = {
      text: "Иванов",
      tokens: [{ type: "fingerspell", letters: ["И", "В", "А", "Н", "О", "В"], src: "Иванов" }],
    };
    const units = utteranceUnits(utterance);
    expect(units).toHaveLength(6);
    expect(units.every((u) => u.tokenIndex === 0)).toBe(true);
    expect(units.map((u) => u.gloss)).toEqual([
      "ДАКТИЛЬ_И", "ДАКТИЛЬ_В", "ДАКТИЛЬ_А", "ДАКТИЛЬ_Н", "ДАКТИЛЬ_О", "ДАКТИЛЬ_В",
    ]);
  });
});

describe("segmentsToTokens", () => {
  it("отображает отрезки плана на токены", () => {
    const units = utteranceUnits(UTTERANCE);
    const tokens = segmentsToTokens(units, plan(4));
    expect(tokens).toEqual([0, 1, 2, 3]);
  });

  it("лишние отрезки не подсвечивают токен", () => {
    const units = utteranceUnits(UTTERANCE);
    const tokens = segmentsToTokens(units, plan(6));
    expect(tokens).toEqual([0, 1, 2, 3, -1, -1]);
  });

  it("дактильное слово: отрезки ведут к одному токену", () => {
    const utterance: UtteranceGlosses = {
      text: "Ива",
      tokens: [{ type: "fingerspell", letters: ["И", "В", "А"], src: "Ива" }],
    };
    const tokens = segmentsToTokens(utteranceUnits(utterance), plan(3));
    expect(tokens).toEqual([0, 0, 0]);
  });
});

describe("activeTokenAt / activeWordAt", () => {
  const words = alignTokens(UTTERANCE);
  const units = utteranceUnits(UTTERANCE);
  const queuePlan = plan(4);

  it("подсвечивает слово, которое играет аватар", () => {
    // Клипы по 1 с: первый 0–1000, второй 800–1800, третий 1600–2600, четвёртый 2400–3400.
    expect(activeWordAt(words, units, queuePlan, 100)).toBe(0);
    expect(activeWordAt(words, units, queuePlan, 1000)).toBe(1);
    expect(activeWordAt(words, units, queuePlan, 2000)).toBe(2);
    expect(activeWordAt(words, units, queuePlan, 3000)).toBe(3);
  });

  it("возвращает индекс токена по времени", () => {
    expect(activeTokenAt(UTTERANCE, queuePlan, 2000)).toBe(2);
  });

  it("до начала и после конца — -1/последнее слово", () => {
    // Ровно в начале первого отрезка активен первый токен.
    expect(activeWordAt(words, units, queuePlan, 0)).toBe(0);
    // В пустом плане активного слова нет.
    expect(activeWordAt(words, units, planQueue([]), 0)).toBe(-1);
  });

  it("активное слово меняется по ходу очереди", () => {
    const seen = new Set<number>();
    for (let t = 0; t < queuePlan.totalMs; t += 100) {
      const index = activeWordAt(words, units, queuePlan, t);
      if (index >= 0) seen.add(index);
    }
    expect([...seen].sort()).toEqual([0, 1, 2, 3]);
  });
});

describe("wordIndexForToken", () => {
  it("находит слово по токену", () => {
    const words = alignTokens(UTTERANCE);
    expect(wordIndexForToken(words, 2)).toBe(2);
    expect(wordIndexForToken(words, 99)).toBe(-1);
  });
});

describe("subtitlePieces", () => {
  it("делит текст на слова и промежутки, сохраняя пунктуацию", () => {
    const utterance: UtteranceGlosses = {
      text: "Да, нет!",
      tokens: [
        { type: "sign", gloss: "ДА", src: "Да" },
        { type: "sign", gloss: "НЕТ", src: "нет" },
      ],
    };
    const words = alignTokens(utterance);
    const pieces = subtitlePieces(utterance, words);
    expect(pieces).toEqual([
      { kind: "word", text: "Да", wordIndex: 0 },
      { kind: "text", text: ", " },
      { kind: "word", text: "нет", wordIndex: 1 },
      { kind: "text", text: "!" },
    ]);
  });

  it("склеивает весь текст обратно", () => {
    const words = alignTokens(UTTERANCE);
    const pieces = subtitlePieces(UTTERANCE, words);
    expect(pieces.map((p) => p.text).join("")).toBe(UTTERANCE.text);
  });

  it("несопоставленные слова остаются обычным текстом", () => {
    const words = alignTokens(UTTERANCE);
    const pieces = subtitlePieces(UTTERANCE, words);
    const texts = pieces.filter((p) => p.kind === "text").map((p) => p.text).join("");
    expect(texts).toContain("на");
  });
});

describe("размер и контраст", () => {
  it("даёт CSS-классы размера и темы", () => {
    expect(subtitleSizeClass("large")).toBe("subtitle-size-large");
    expect(subtitleThemeClass("light")).toBe("subtitle-theme-light");
  });

  it("списки размеров и тем непустые и уникальные", () => {
    expect(new Set(SUBTITLE_SIZES).size).toBe(SUBTITLE_SIZES.length);
    expect(new Set(SUBTITLE_THEMES).size).toBe(SUBTITLE_THEMES.length);
    expect(SUBTITLE_SIZES).toContain("medium");
    expect(SUBTITLE_THEMES).toContain("dark");
  });
});
