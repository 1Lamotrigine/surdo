/**
 * Субтитры (C6): соответствие токенов глосс словам текста и подсветка текущего
 * слова синхронно с аватаром (FR-10, ТЗ 7.2).
 *
 * Фраза приходит как объект глосс: `text` (исходный текст) и `tokens` — набор
 * токенов (`sign`, `number`, `fingerspell`). Субтитр показывает текст фразы и
 * подсвечивает слово, которое сейчас «проговаривается» аватаром.
 *
 * Здесь живёт **чистая** часть: сопоставление токена и слова исходного текста
 * (критерий C6 — «тест соответствия токена и слова»), раскладка токенов в
 * единицы показа (один клип = одна единица; дактиль — буква за буквой) и поиск
 * активного слова по времени очереди (`planQueue` C4 — единственный источник
 * таймингов). Отрисовка в DOM — тонкий слой `SubtitleView` поверх этих функций.
 */

import type { QueuePlan } from "./clip-queue";
import { segmentAt } from "./clip-queue";

/** Вид токена глосс (ТЗ 7.2). */
export type TokenKind = "sign" | "number" | "fingerspell";

/** Токен глосс: слово словаря, число или слово по буквам. */
export type GlossToken = {
  /** Вид токена. */
  type: TokenKind;
  /** Исходное слово из текста фразы (`src`). */
  src: string;
  /** Глосса жеста (`sign`). */
  gloss?: string;
  /** Значение числа (`number`). */
  value?: number;
  /** Буквы дактиля (`fingerspell`). */
  letters?: string[];
  /** Грамматические маркеры (`neg`, `q-yn`, `q-wh`, `cond`, `emph`). */
  markers?: string[];
};

/** Объект глосс фразы (подмножество, нужное субтитрам). */
export type UtteranceGlosses = {
  /** Исходный текст фразы. */
  text: string;
  /** Токены по порядку. */
  tokens: GlossToken[];
  /** Язык жестов (`rsl`/`ksl`). */
  lang?: string;
  /** Тип предложения (вопрос, повеление и т.д.). */
  sentence_type?: string;
};

/** Слово субтитра: диапазон в исходном тексте и связанный токен. */
export type SubtitleWord = {
  /** Исходное слово (как в тексте). */
  text: string;
  /** Индекс начала в `utterance.text` (по коду UTF-16). */
  start: number;
  /** Индекс конца (не включительно). */
  end: number;
  /** Индекс токена в `utterance.tokens`. */
  tokenIndex: number;
};

/** Единица показа: один клип, который аватар играет (C4). */
export type ShowUnit = {
  /** Индекс токена, которому принадлежит единица. */
  tokenIndex: number;
  /** Вид токена. */
  kind: TokenKind;
  /** Глосса клипа (`sign`/`number`/буква дактиля). */
  gloss: string;
};

/** Размеры субтитров (C6: «размер и контраст»). */
export type SubtitleSize = "small" | "medium" | "large";

/** Темы субтитров: тёмная/светлая подложка под текст. */
export type SubtitleTheme = "dark" | "light";

/** Доступные размеры субтитров. */
export const SUBTITLE_SIZES: SubtitleSize[] = ["small", "medium", "large"];

/** Доступные темы субтитров. */
export const SUBTITLE_THEMES: SubtitleTheme[] = ["dark", "light"];

/** Префикс глоссы буквы дактиля (совпадает с `dactyl.ts`). */
const DACTYL_GLOSS_PREFIX = "ДАКТИЛЬ_";

/** Префикс глоссы цифры дактиля. */
const DIGIT_GLOSS_PREFIX = "ЦИФРА_";

/** CSS-класс размера субтитров. */
export function subtitleSizeClass(size: SubtitleSize): string {
  return `subtitle-size-${size}`;
}

/** CSS-класс темы (контраста) субтитров. */
export function subtitleThemeClass(theme: SubtitleTheme): string {
  return `subtitle-theme-${theme}`;
}

/** Привести текст к сравнимому виду: нижний регистр, ё→е, только буквы и цифры. */
export function normalizeWord(word: string): string {
  return word
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(/[^\p{L}\p{N}]+/gu, "");
}

/**
 * Разобрать текст на слова с диапазонами. Пунктуация между словами не входит в
 * диапазон, поэтому подсветка обводит именно слово, а не запятую.
 */
export function splitTextWords(text: string): { word: string; start: number; end: number }[] {
  const words: { word: string; start: number; end: number }[] = [];
  const re = /[\p{L}\p{N}]+/gu;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    words.push({ word: match[0], start: match.index, end: match.index + match[0].length });
  }
  return words;
}

/**
 * Сопоставить токены глосс словам исходного текста в порядке следования.
 *
 * Каждому токену ищется слово в тексте, начиная от позиции прошлого совпадения
 * (курсор только вперёд): так повторяющиеся слова («дом ... дом») не путаются.
 * Если точного совпадения нет, берётся следующее слово текста (порядок важнее
 * формы — глосса может быть леммой: «УЧЕБНИК» ← «учебнике»). Токен, которому не
 * нашлось слово, пропускается.
 */
export function alignTokens(utterance: UtteranceGlosses): SubtitleWord[] {
  const words = splitTextWords(utterance.text);
  const result: SubtitleWord[] = [];
  let cursor = 0;

  utterance.tokens.forEach((token, tokenIndex) => {
    const source = splitTextWords(token.src).map((word) => normalizeWord(word.word));
    if (source.length === 0 || cursor >= words.length) return;

    let found = cursor;
    let length = 1;
    for (let i = cursor; i + source.length <= words.length; i += 1) {
      if (source.every((word, offset) => normalizeWord(words[i + offset].word) === word)) {
        found = i;
        length = source.length;
        break;
      }
    }

    const start = words[found].start;
    const end = words[found + length - 1].end;
    result.push({ text: utterance.text.slice(start, end), start, end, tokenIndex });
    cursor = found + length;
  });

  return result;
}

/** Глосса клипа для токена: жест, цифра/число или буква дактиля. */
export function tokenGloss(token: GlossToken): string | null {
  if (token.type === "sign") return token.gloss ?? null;
  if (token.type === "number") {
    if (typeof token.value === "number") return `${DIGIT_GLOSS_PREFIX}${token.value}`;
    return token.gloss ?? null;
  }
  // Дактиль: одна единица на букву (клип буквы).
  const first = token.letters?.[0];
  return first ? `${DACTYL_GLOSS_PREFIX}${first}` : (token.gloss ?? null);
}

/**
 * Разложить фразу на единицы показа — по одной на клип. Жест и число дают одну
 * единицу, слово по буквам (дактиль) — по единице на каждую букву. Порядок
 * единиц совпадает с порядком клипов в очереди C4.
 */
export function utteranceUnits(utterance: UtteranceGlosses): ShowUnit[] {
  const units: ShowUnit[] = [];
  utterance.tokens.forEach((token, tokenIndex) => {
    if (token.type === "fingerspell" && token.letters && token.letters.length > 0) {
      for (const letter of token.letters) {
        units.push({ tokenIndex, kind: "fingerspell", gloss: `${DACTYL_GLOSS_PREFIX}${letter}` });
      }
      return;
    }
    const gloss = tokenGloss(token);
    if (gloss) units.push({ tokenIndex, kind: token.type, gloss });
  });
  return units;
}

/**
 * Какие токены относятся к какому отрезку плана: `plan.segments[i]` ←
 * `units[i].tokenIndex`. Функция терпима к расхождению длин (единиц может быть
 * больше/меньше отрезков — часть клипов могла не найтись): лишние отбрасываются,
 * недостающие не подсвечивают ничего.
 */
export function segmentsToTokens(units: ShowUnit[], plan: QueuePlan): number[] {
  return plan.segments.map((segment) => units[segment.index]?.tokenIndex ?? -1);
}

/**
 * Индекс токена (а значит — слова субтитра), которое показывается в момент
 * `timeMs`, или `-1`. Тайминг берётся из плана очереди C4.
 */
export function activeTokenAt(
  utterance: UtteranceGlosses,
  plan: QueuePlan,
  timeMs: number,
): number {
  const units = utteranceUnits(utterance);
  const segment = segmentAt(plan, timeMs);
  if (!segment) return -1;
  return units[segment.index]?.tokenIndex ?? -1;
}

/** Индекс слова субтитра для токена (первое слово с этим токеном) или `-1`. */
export function wordIndexForToken(words: SubtitleWord[], tokenIndex: number): number {
  return words.findIndex((word) => word.tokenIndex === tokenIndex);
}

/**
 * Подсветка по времени: индекс активного слова субтитра или `-1`. Связывает
 * план очереди (C4), единицы показа и сопоставленные слова.
 */
export function activeWordAt(
  words: SubtitleWord[],
  units: ShowUnit[],
  plan: QueuePlan,
  timeMs: number,
): number {
  const segment = segmentAt(plan, timeMs);
  if (!segment) return -1;
  const tokenIndex = units[segment.index]?.tokenIndex ?? -1;
  if (tokenIndex < 0) return -1;
  return wordIndexForToken(words, tokenIndex);
}

/** Кусок текста субтитра: обычный фрагмент между словами или слово. */
export type SubtitlePiece =
  | { kind: "text"; text: string }
  | { kind: "word"; text: string; wordIndex: number };

/**
 * Разбить текст на куски для отрисовки: слова отдельно (их можно подсветить),
 * пробелы и пунктуация — как есть. Так подсветка не «съедает» запятые.
 */
export function subtitlePieces(utterance: UtteranceGlosses, words: SubtitleWord[]): SubtitlePiece[] {
  const pieces: SubtitlePiece[] = [];
  const byStart = new Map(words.map((word, index) => [word.start, index]));
  const text = utterance.text;
  let cursor = 0;

  // Слова уже упорядочены по позиции (alignTokens идёт вперёд).
  const ordered = [...words].sort((a, b) => a.start - b.start);
  for (const word of ordered) {
    if (word.start < cursor) continue;
    if (word.start > cursor) {
      pieces.push({ kind: "text", text: text.slice(cursor, word.start) });
    }
    const index = byStart.get(word.start) ?? -1;
    pieces.push({ kind: "word", text: text.slice(word.start, word.end), wordIndex: index });
    cursor = word.end;
  }
  if (cursor < text.length) {
    pieces.push({ kind: "text", text: text.slice(cursor) });
  }
  return pieces;
}

/** Параметры отрисовки субтитров. */
export type SubtitleViewOptions = {
  /** Размер субтитров (C6). */
  size?: SubtitleSize;
  /** Тема/контраст подложки (C6). */
  theme?: SubtitleTheme;
  /** Пометить фразу как упрощённую (только субтитры, `degraded`). */
  degraded?: boolean;
};

/**
 * Отрисовка субтитров: держит DOM-узлы слов и переключает подсветку текущего.
 * Чистые функции выше вычисляют, что показать; класс только обновляет разметку.
 */
export class SubtitleView {
  private readonly root: HTMLElement;
  private readonly wordsContainer: HTMLElement;
  private wordNodes: HTMLElement[] = [];
  private activeIndex = -1;

  constructor(root: HTMLElement, options: SubtitleViewOptions = {}) {
    this.root = root;
    this.applyStyles(options);
    this.wordsContainer = document.createElement("p");
    this.wordsContainer.className = "subtitle-line";
    this.root.replaceChildren(this.wordsContainer);
  }

  /** Применить размер и тему (контраст) к контейнеру субтитров. */
  applyStyles(options: SubtitleViewOptions): void {
    for (const size of SUBTITLE_SIZES) this.root.classList.remove(subtitleSizeClass(size));
    for (const theme of SUBTITLE_THEMES) this.root.classList.remove(subtitleThemeClass(theme));
    this.root.classList.add(subtitleSizeClass(options.size ?? "medium"));
    this.root.classList.add(subtitleThemeClass(options.theme ?? "dark"));
    this.root.classList.toggle("subtitle-degraded", options.degraded ?? false);
  }

  /** Показать фразу: собрать куски текста и запомнить узлы слов. */
  render(utterance: UtteranceGlosses, words: SubtitleWord[]): void {
    this.wordsContainer.replaceChildren();
    this.wordNodes = [];
    this.activeIndex = -1;

    for (const piece of subtitlePieces(utterance, words)) {
      if (piece.kind === "text") {
        this.wordsContainer.append(document.createTextNode(piece.text));
        continue;
      }
      const node = document.createElement("span");
      node.className = "subtitle-word";
      node.textContent = piece.text;
      node.dataset.wordIndex = String(piece.wordIndex);
      this.wordsContainer.append(node);
      this.wordNodes.push(node);
    }
  }

  /** Подсветить слово по индексу (`-1` снимает подсветку). */
  highlight(index: number): void {
    if (index === this.activeIndex) return;
    const previous = this.wordNodes[this.activeIndex];
    if (previous) {
      previous.classList.remove("subtitle-word-active");
      previous.removeAttribute("aria-current");
    }
    const next = this.wordNodes[index];
    if (next) {
      next.classList.add("subtitle-word-active");
      next.setAttribute("aria-current", "true");
    }
    this.activeIndex = index;
  }

  /** Очистить субтитры. */
  clear(): void {
    this.wordsContainer.replaceChildren();
    this.wordNodes = [];
    this.activeIndex = -1;
  }

  /** Индекс активного слова (для отладки и тестов). */
  get active(): number {
    return this.activeIndex;
  }
}
