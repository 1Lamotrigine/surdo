/**
 * Тесты дактиля (C5).
 *
 * Критерий этапа — «тест разбиения слова на буквы и тайминги». Здесь проверяются
 * русский алфавит, нормализация и разбор слова на знаки, глоссы букв и цифр,
 * тайминги склейки букв укороченным переходом и пауза между словами.
 */

import { describe, expect, it } from "vitest";

import { DACTYL_CROSSFADE_MS, planQueue } from "./clip-queue";
import {
  DACTYL_ALPHABET,
  DACTYL_DIGITS,
  DACTYL_GLOSS_PREFIX,
  DACTYL_LETTER_MS,
  DACTYL_WORD_GAP_MS,
  DIGIT_GLOSS_PREFIX,
  buildDactylQueue,
  dactylTimeline,
  digitGloss,
  isDactylDigit,
  isDactylLetter,
  letterGloss,
  normalizeChar,
  splitWord,
} from "./dactyl";

describe("DACTYL_ALPHABET", () => {
  it("содержит 33 буквы русского алфавита", () => {
    expect(DACTYL_ALPHABET).toHaveLength(33);
    for (const letter of "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ") {
      expect(DACTYL_ALPHABET).toContain(letter);
    }
  });

  it("содержит 10 цифр", () => {
    expect(DACTYL_DIGITS).toHaveLength(10);
  });
});

describe("normalizeChar", () => {
  it("переводит в верхний регистр", () => {
    expect(normalizeChar("а")).toBe("А");
    expect(normalizeChar("ё")).toBe("Ё");
    expect(normalizeChar("7")).toBe("7");
  });

  it("заменяет похожие латинские буквы на кириллицу", () => {
    expect(normalizeChar("a")).toBe("А");
    expect(normalizeChar("B")).toBe("В");
    expect(normalizeChar("c")).toBe("С");
  });
});

describe("isDactylLetter / isDactylDigit", () => {
  it("распознаёт буквы, цифры и прочее", () => {
    expect(isDactylLetter("я")).toBe(true);
    expect(isDactylLetter("A")).toBe(true); // латинская A → А
    expect(isDactylLetter("!")).toBe(false);
    expect(isDactylDigit("5")).toBe(true);
    expect(isDactylDigit("я")).toBe(false);
  });
});

describe("letterGloss / digitGloss", () => {
  it("строит глоссы буквы и цифры", () => {
    expect(letterGloss("а")).toBe(`${DACTYL_GLOSS_PREFIX}А`);
    expect(letterGloss("Ё")).toBe(`${DACTYL_GLOSS_PREFIX}Ё`);
    expect(letterGloss("7")).toBe(`${DIGIT_GLOSS_PREFIX}7`);
    expect(letterGloss("!")).toBeNull();
    expect(digitGloss("3")).toBe(`${DIGIT_GLOSS_PREFIX}3`);
    expect(digitGloss("а")).toBeNull();
  });
});

describe("splitWord", () => {
  it("разбирает слово на буквы верхнего регистра", () => {
    const chars = splitWord("Иванов");
    expect(chars.map((c) => c.char).join("")).toBe("ИВАНОВ");
    expect(chars.every((c) => c.kind === "letter")).toBe(true);
    expect(chars[0].gloss).toBe(`${DACTYL_GLOSS_PREFIX}И`);
  });

  it("вставляет один пробел между словами", () => {
    const chars = splitWord("Иван   Петров");
    const spaces = chars.filter((c) => c.kind === "space");
    expect(spaces).toHaveLength(1);
    expect(chars.find((c) => c.kind === "space")?.gloss).toBeNull();
  });

  it("отбрасывает пунктуацию", () => {
    const chars = splitWord("Да, нет!");
    expect(chars.map((c) => c.char).join("")).toBe("ДА НЕТ");
  });

  it("не оставляет пробел в конце и в начале", () => {
    expect(splitWord("  слово  ").map((c) => c.char).join("")).toBe("СЛОВО");
    expect(splitWord("слово ")[splitWord("слово ").length - 1].kind).toBe("letter");
  });

  it("распознаёт цифры", () => {
    const chars = splitWord("дом 42");
    const digits = chars.filter((c) => c.kind === "digit");
    expect(digits.map((c) => c.char).join("")).toBe("42");
    expect(digits[0].gloss).toBe(`${DIGIT_GLOSS_PREFIX}4`);
  });

  it("пустая строка даёт пустой список", () => {
    expect(splitWord("")).toEqual([]);
    expect(splitWord("   ")).toEqual([]);
    expect(splitWord("...")).toEqual([]);
  });
});

describe("dactylTimeline", () => {
  it("буквы идут подряд с укороченным перекрытием", () => {
    const timeline = dactylTimeline("ИВАНОВ");
    expect(timeline.signs).toHaveLength(6);
    expect(timeline.items).toHaveLength(6);

    const step = DACTYL_LETTER_MS - DACTYL_CROSSFADE_MS;
    timeline.items.forEach((item, index) => {
      expect(item.startMs).toBeCloseTo(index * step, 6);
      expect(item.endMs).toBeCloseTo(index * step + DACTYL_LETTER_MS, 6);
    });
    expect(timeline.totalMs).toBeCloseTo(5 * step + DACTYL_LETTER_MS, 6);
  });

  it("пробел даёт паузу между словами", () => {
    const timeline = dactylTimeline("А В");
    expect(timeline.items).toHaveLength(3);
    const [a, space, v] = timeline.items;
    expect(a.kind).toBe("letter");
    expect(space.kind).toBe("space");
    expect(space.startMs).toBeCloseTo(a.endMs - DACTYL_CROSSFADE_MS, 6);
    expect(space.endMs).toBeCloseTo(space.startMs + DACTYL_WORD_GAP_MS, 6);
    expect(v.startMs).toBeCloseTo(space.endMs, 6);
    expect(timeline.totalMs).toBeCloseTo(v.endMs, 6);
  });

  it("скорость сокращает показ и переходы", () => {
    const slow = dactylTimeline("АБ", { speed: 1 });
    const fast = dactylTimeline("АБ", { speed: 1.3 });
    expect(fast.totalMs).toBeLessThan(slow.totalMs);
    expect(fast.totalMs).toBeCloseTo(slow.totalMs / 1.3, 3);
  });

  it("зажимает speed и длину перехода", () => {
    const fast = dactylTimeline("АБ", { speed: 5 });
    expect(fast.totalMs).toBeCloseTo(dactylTimeline("АБ", { speed: 1.3 }).totalMs, 6);

    // Переход не длиннее половины буквы.
    const long = dactylTimeline("АБ", { letterMs: 100, crossfadeMs: 500 });
    const step = 100 - 50; // crossfade ужат до letterMs/2
    expect(long.items[1].startMs).toBeCloseTo(step, 6);
  });

  it("цифры озвучиваются наравне с буквами", () => {
    const timeline = dactylTimeline("А1");
    expect(timeline.signs.map((s) => s.char)).toEqual(["А", "1"]);
    expect(timeline.signs[1].gloss).toBe(`${DIGIT_GLOSS_PREFIX}1`);
  });

  it("пустой текст даёт нулевую длительность", () => {
    const timeline = dactylTimeline("");
    expect(timeline.items).toEqual([]);
    expect(timeline.totalMs).toBe(0);
  });

  it("сохраняет исходный текст", () => {
    expect(dactylTimeline("Привет").text).toBe("Привет");
  });
});

describe("buildDactylQueue", () => {
  /** Резолвер: синтетический клип на каждую глоссу. */
  const resolve = (gloss: string) => ({ duration: 0.4, fps: 30, frames: 12, gloss });

  it("сопоставляет буквы клипам и планирует в режиме dactyl", () => {
    const queue = buildDactylQueue("ИВАН", resolve);
    expect(queue.signs.map((s) => s.char).join("")).toBe("ИВАН");
    expect(queue.clips).toHaveLength(4);
    expect(queue.plan.mode).toBe("dactyl");
    // Укороченный блендинг, а не общие 150–250 мс.
    expect(queue.plan.crossfadeMs).toBe(DACTYL_CROSSFADE_MS);
  });

  it("пропускает буквы без клипа у резолвера", () => {
    const only = (gloss: string) => (gloss.endsWith("А") ? { duration: 0.4, fps: 30, frames: 12 } : null);
    const queue = buildDactylQueue("АБА", only);
    expect(queue.signs.map((s) => s.char).join("")).toBe("АА");
    expect(queue.clips).toHaveLength(2);
  });

  it("игнорирует пробелы в очереди клипов", () => {
    const queue = buildDactylQueue("А В", resolve);
    expect(queue.signs.map((s) => s.char).join("")).toBe("АВ");
  });

  it("пустой резолвер даёт пустой план", () => {
    const queue = buildDactylQueue("ИВАН", () => null);
    expect(queue.clips).toEqual([]);
    expect(queue.plan.totalMs).toBe(0);
  });

  it("передаёт скорость в план", () => {
    const queue = buildDactylQueue("ИВАН", resolve, { speed: 1.3 });
    expect(queue.plan.speed).toBe(1.3);
  });
});

describe("режим dactyl в планировщике", () => {
  it("разрешает короткий переход, недоступный обычной фразе", () => {
    const clips = [
      { duration: 0.4, fps: 30, frames: 12 },
      { duration: 0.4, fps: 30, frames: 12 },
    ];
    const phrase = planQueue(clips, { crossfadeMs: DACTYL_CROSSFADE_MS });
    const dactyl = planQueue(clips, { mode: "dactyl", crossfadeMs: DACTYL_CROSSFADE_MS });
    // Обычная фраза зажимает 80 мс до 150; дактиль оставляет 80.
    expect(phrase.crossfadeMs).toBe(150);
    expect(dactyl.crossfadeMs).toBe(DACTYL_CROSSFADE_MS);
  });
});
