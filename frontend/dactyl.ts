/**
 * Дактиль (пальцевая азбука, C5) — чистая функция без Three.js и DOM.
 *
 * Требования ТЗ 5.4 и FR-9: для слов без жеста слово показывается **по буквам**,
 * отдельным клипом на каждую букву, склеенным укороченным блендингом. Здесь
 * живёт текстовая часть: русский алфавит дактиля, разбор слова на буквы, глоссы
 * букв (`ДАКТИЛЬ_А`) и тайминги склейки. Клипы букв пишет инструмент редактора
 * (блок D); модуль лишь описывает, какие клипы и в каком порядке нужны.
 *
 * Разбор слова и тайминги не зависят от браузера, поэтому тестируются в vitest
 * (критерий C5: «тест разбиения слова на буквы и тайминги»). Планировщик очереди
 * C4 переиспользуется в режиме `dactyl` (укороченный crossfade 0–250 мс).
 */

import {
  DACTYL_CROSSFADE_MS,
  clampSpeed,
  planQueue,
  type QueueClip,
  type QueuePlan,
  type QueuePlanOptions,
} from "./clip-queue";

/** Русский алфавит дактиля: 33 буквы, порядок как в азбуке. */
export const DACTYL_ALPHABET = [
  "А", "Б", "В", "Г", "Д", "Е", "Ё", "Ж", "З", "И", "Й", "К", "Л", "М", "Н",
  "О", "П", "Р", "С", "Т", "У", "Ф", "Х", "Ц", "Ч", "Ш", "Щ", "Ъ", "Ы", "Ь",
  "Э", "Ю", "Я",
] as const;

/** Цифры дактиля (0–9, ТЗ 15.2: «цифры 0-100» — старшая часть по буквам). */
export const DACTYL_DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"] as const;

/** Префикс глоссы буквы дактиля (совпадает с записью в словаре, блок D). */
export const DACTYL_GLOSS_PREFIX = "ДАКТИЛЬ_";

/** Префикс глоссы цифры дактиля. */
export const DIGIT_GLOSS_PREFIX = "ЦИФРА_";

/** Длительность показа буквы по умолчанию, мс (речь дактиля заметно медленнее). */
export const DACTYL_LETTER_MS = 420;

/** Пауза между словами (пробел), мс. */
export const DACTYL_WORD_GAP_MS = 320;

/** Тип знака в слове. */
export type DactylKind = "letter" | "digit" | "space";

/** Знак дактиля: буква, цифра или пробел. */
export type DactylChar = {
  /** Сам символ: буква (верхний регистр), цифра или пробел « ». */
  char: string;
  /** Тип знака. */
  kind: DactylKind;
  /** Глосса клипа (`ДАКТИЛЬ_А`, `ЦИФРА_5`) или `null` для пробела. */
  gloss: string | null;
};

/** Тайминг одного знака в разложенном слове. */
export type DactylTiming = DactylChar & {
  /** Индекс знака в разложенном слове. */
  index: number;
  /** Время начала показа, мс. */
  startMs: number;
  /** Время конца показа, мс. */
  endMs: number;
};

/** Разложенное слово: знаки по порядку и общая длительность. */
export type DactylTimeline = {
  /** Исходный текст. */
  text: string;
  /** Знаки (буквы, цифры, пробелы) по порядку. */
  chars: DactylChar[];
  /** Тайминги знаков по порядку. */
  items: DactylTiming[];
  /** Только буквы и цифры (без пробелов) — то, что озвучивается. */
  signs: DactylChar[];
  /** Общая длительность показа, мс. */
  totalMs: number;
};

/** Параметры раскладки слова по буквам. */
export type DactylTimelineOptions = {
  /** Длительность показа одной буквы, мс. */
  letterMs?: number;
  /** Пауза между словами (пробел), мс. */
  spaceMs?: number;
  /** Длина перехода между буквами, мс (укороченный блендинг, ТЗ 5.4). */
  crossfadeMs?: number;
  /** Скорость воспроизведения (0.6–1.3x). */
  speed?: number;
};

/** Латинские буквы, похожие на кириллические: раскладка/ввод могут путать. */
const LATIN_TO_CYRILLIC: Record<string, string> = {
  A: "А", B: "В", E: "Е", K: "К", M: "М", H: "Н", O: "О", P: "Р", C: "С",
  T: "Т", Y: "У", X: "Х",
};

const ALPHABET_SET = new Set<string>(DACTYL_ALPHABET);
const DIGIT_SET = new Set<string>(DACTYL_DIGITS);

/** Глосса буквы дактиля. Возвращает `null`, если это не буква алфавита. */
export function letterGloss(char: string): string | null {
  const normalized = normalizeChar(char);
  if (DIGIT_SET.has(normalized)) return `${DIGIT_GLOSS_PREFIX}${normalized}`;
  if (ALPHABET_SET.has(normalized)) return `${DACTYL_GLOSS_PREFIX}${normalized}`;
  return null;
}

/** Глосса цифры дактиля или `null`. */
export function digitGloss(char: string): string | null {
  const normalized = normalizeChar(char);
  return DIGIT_SET.has(normalized) ? `${DIGIT_GLOSS_PREFIX}${normalized}` : null;
}

/** Привести символ к верхнему регистру и заменить латинские похожие на кириллицу. */
export function normalizeChar(char: string): string {
  const upper = char.toUpperCase();
  return LATIN_TO_CYRILLIC[upper] ?? upper;
}

/** Является ли символ буквой дактиля. */
export function isDactylLetter(char: string): boolean {
  return ALPHABET_SET.has(normalizeChar(char));
}

/** Является ли символ цифрой дактиля. */
export function isDactylDigit(char: string): boolean {
  return DIGIT_SET.has(normalizeChar(char));
}

/**
 * Разобрать текст на знаки дактиля: буквы (верхний регистр, с заменой похожих
 * латинских), цифры и пробелы (пауза между словами). Прочая пунктуация
 * отбрасывается, пробельные последовательности схлопываются в один пробел.
 */
export function splitWord(text: string): DactylChar[] {
  const chars: DactylChar[] = [];
  let lastSpace = false;

  for (const raw of text) {
    const char = normalizeChar(raw);
    if (DIGIT_SET.has(char)) {
      chars.push({ char, kind: "digit", gloss: `${DIGIT_GLOSS_PREFIX}${char}` });
      lastSpace = false;
    } else if (ALPHABET_SET.has(char)) {
      chars.push({ char, kind: "letter", gloss: `${DACTYL_GLOSS_PREFIX}${char}` });
      lastSpace = false;
    } else if (/\s/.test(raw)) {
      // Пробел — пауза между словами; несколько подряд схлопываем в один.
      if (!lastSpace && chars.length > 0) {
        chars.push({ char: " ", kind: "space", gloss: null });
        lastSpace = true;
      }
    }
    // Пунктуация и прочие символы не озвучиваются.
  }

  // Пробел в конце не нужен: пауза после последнего слова не имеет смысла.
  if (chars.length > 0 && chars[chars.length - 1].kind === "space") {
    chars.pop();
  }
  return chars;
}

/**
 * Разложить слово по буквам и посчитать тайминги: буквы идут подряд с
 * укороченным переходом (буквы перекрываются на `crossfadeMs`), пробелы дают
 * паузу `spaceMs`. Скорость сокращает и показ букв, и переходы.
 */
export function dactylTimeline(text: string, options: DactylTimelineOptions = {}): DactylTimeline {
  const chars = splitWord(text);
  const speed = clampSpeed(options.speed ?? 1);
  const letterMs = Math.max(0, options.letterMs ?? DACTYL_LETTER_MS) / speed;
  const spaceMs = Math.max(0, options.spaceMs ?? DACTYL_WORD_GAP_MS) / speed;
  const crossfadeMs = Math.max(
    0,
    Math.min(options.crossfadeMs ?? DACTYL_CROSSFADE_MS, letterMs / 2),
  ) / speed;

  const items: DactylTiming[] = [];
  let cursorMs = 0;

  for (let i = 0; i < chars.length; i += 1) {
    const char = chars[i];
    if (char.kind === "space") {
      // Пауза между словами: аватар стоит в нейтральной позе.
      const startMs = cursorMs;
      const endMs = startMs + spaceMs;
      items.push({ ...char, index: i, startMs, endMs });
      cursorMs = endMs;
      continue;
    }

    // Буква/цифра: показывается `letterMs`, перекрывается со следующей на
    // `crossfadeMs`. Следующий знак начнётся раньше конца текущего.
    const startMs = cursorMs;
    const endMs = startMs + letterMs;
    items.push({ ...char, index: i, startMs, endMs });
    cursorMs = endMs - crossfadeMs;
  }

  const totalMs = items.length > 0 ? items[items.length - 1].endMs : 0;
  const signs = chars.filter((char) => char.kind !== "space");
  return { text, chars, items, signs, totalMs };
}

/**
 * Резолвер клипа по глоссе: возвращает описание клипа для планировщика. Клипов
 * букв в репозитории нет (их пишет блок D), поэтому конкретную реализацию задаёт
 * вызывающий: тестовая страница собирает синтетические, сервер в блоке E — из
 * словаря. Отсутствующая буква (`null`) пропускается.
 */
export type DactylClipResolver = (gloss: string) => QueueClip | null;

/** Результат сборки дактиль-очереди: знаки, клипы и план. */
export type DactylQueue = {
  /** Знаки с глоссами (без пробелов), по порядку; `signs[i]` → `clips[i]`. */
  signs: DactylChar[];
  /** Клипы, готовые для `planQueue` (по одному на знак, который нашёлся). */
  clips: QueueClip[];
  /** План очереди в режиме `dactyl`. */
  plan: QueuePlan;
};

/**
 * Собрать дактиль-очередь: сопоставить буквы клипам через резолвер и
 * спланировать их с укороченным блендингом. Пробелы пропускаются — их паузу
 * задаёт `dactylTimeline` (в очереди клипов пауза между словами не нужна, если
 * слова играются отдельными планами).
 */
export function buildDactylQueue(
  text: string,
  resolve: DactylClipResolver,
  options: QueuePlanOptions = {},
): DactylQueue {
  const chars = splitWord(text);
  const signs: DactylChar[] = [];
  const clips: QueueClip[] = [];

  for (const char of chars) {
    if (char.kind === "space" || !char.gloss) continue;
    const clip = resolve(char.gloss);
    if (!clip) continue;
    signs.push(char);
    clips.push(clip);
  }

  const plan = planQueue(clips, {
    mode: "dactyl",
    speed: options.speed,
    crossfadeMs: options.crossfadeMs ?? DACTYL_CROSSFADE_MS,
    gapMs: options.gapMs ?? 0,
  });

  return { signs, clips, plan };
}
