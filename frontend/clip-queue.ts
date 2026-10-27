/**
 * Планировщик очереди клипов (C4) — чистая функция без Three.js и DOM.
 *
 * Требования ТЗ (FR-12, FR-14, FR-16, `docs/spec/clip-format.md` 5.4):
 * - клипы идут подряд с плавным переходом (crossfade 150–250 мс);
 * - в начале и конце очереди аватар стоит в нейтральной позе (нейтральная поза
 *   между фразами);
 * - скорость воспроизведения ограничена 0.6–1.3x.
 *
 * Модуль только считает тайминги: на вход список клипов и параметры, на выходе
 * отрезки (`Segment`) с временем показа, длительностью crossfade и зонами
 * блендинга. Никакой отрисовки — поэтому планировщик тестируется в vitest, а
 * игрок (`clip-player.ts`) и интерфейс переиспользуют одни и те же числа.
 *
 * Модель времени: каждый клип показывается `durationMs` (длительность при 1x,
 * делённая на скорость). Соседние клипы пересекаются на `crossfadeMs`: голова
 * клипа `i+1` совпадает с хвостом клипа `i`, поэтому суммарное время меньше
 * суммы длительностей. В зоне пересечения игрок смешивает кадры двух клипов.
 */

import type { DecodedClip } from "./clip";

/** Минимальная скорость воспроизведения (FR-13, FR-16). */
export const MIN_SPEED = 0.6;

/** Максимальная скорость воспроизведения (FR-16: ускорение до 1.3x). */
export const MAX_SPEED = 1.3;

/** Длина crossfade по умолчанию, мс (ТЗ 5.4: 150–250 мс). */
export const DEFAULT_CROSSFADE_MS = 200;

/** Минимальная длина crossfade, мс (нижняя граница ТЗ). */
export const MIN_CROSSFADE_MS = 150;

/** Максимальная длина crossfade, мс (верхняя граница ТЗ). */
export const MAX_CROSSFADE_MS = 250;

/** Длина crossfade для склейки букв дактиля (ТЗ 5.4: укороченный блендинг). */
export const DACTYL_CROSSFADE_MS = 80;

/** Минимальная длина crossfade для дактиля, мс (ниже общей границы 150). */
export const MIN_DACTYL_CROSSFADE_MS = 0;

/** Режим склейки: обычная фраза или слово по буквам (дактиль). */
export type CrossfadeMode = "phrase" | "dactyl";

/** Длительность перехода в нейтральную позу в начале и конце очереди, мс. */
export const NEUTRAL_FADE_MS = 150;

/**
 * Минимальное описание клипа для планировщика: длительность и частота кадров.
 * `DecodedClip` подходит структурно, но данные кадров планировщику не нужны.
 */
export type QueueClip = {
  /** Длительность клипа в секундах при скорости 1x. */
  duration: number;
  /** Частота кадров клипа (для пересчёта времени в номер кадра). */
  fps: number;
  /** Число кадров (для пересчёта времени в номер кадра). */
  frames: number;
};

/** Отрезок клипа в очереди с абсолютным временем (мс). */
export type Segment = {
  /** Порядковый номер клипа в очереди. */
  index: number;
  /** Время начала перехода в этот клип, мс (начало зоны входа). */
  startMs: number;
  /** Время конца показа клипа, мс (конец зоны выхода). */
  endMs: number;
  /** Длительность показа клипа с учётом скорости, мс. */
  durationMs: number;
  /** Скорость воспроизведения (0.6–1.3x). */
  speed: number;
  /**
   * Длительность crossfade в начале отрезка, мс: сколько миллисекунд аватар
   * переходит из предыдущего клипа (или нейтральной позы) в этот.
   */
  fadeInMs: number;
  /**
   * Длительность crossfade в конце отрезка, мс: сколько миллисекунд уходит на
   * переход к следующему клипу (или в нейтральную позу, если клип последний).
   */
  fadeOutMs: number;
};

/** Готовый план очереди. */
export type QueuePlan = {
  /** Отрезки в порядке воспроизведения. */
  segments: Segment[];
  /** Общая длительность очереди, мс. */
  totalMs: number;
  /** Скорость, применённая ко всем клипам (зажата 0.6–1.3x). */
  speed: number;
  /** Длина crossfade между клипами, мс. */
  crossfadeMs: number;
  /** Пауза в нейтральной позе между фразами, мс. */
  gapMs: number;
  /** Режим склейки (`phrase` или `dactyl`). */
  mode: CrossfadeMode;
};

/** Параметры планирования. */
export type QueuePlanOptions = {
  /** Скорость воспроизведения; зажимается в [0.6, 1.3]. */
  speed?: number;
  /** Длина crossfade, мс; зажимается в [150, 250] (дактиль — в [0, 250]). */
  crossfadeMs?: number;
  /** Пауза в нейтральной позе между фразами, мс. */
  gapMs?: number;
  /**
   * Режим склейки: `phrase` (обычная фраза, переход 150–250 мс) или `dactyl`
   * (слово по буквам — укороченный переход 0–250 мс, ТЗ 5.4). Влияет только на
   * нижнюю границу `crossfadeMs`.
   */
  mode?: CrossfadeMode;
};

/** Зажать значение в диапазон. */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Зажать скорость в допустимый диапазон 0.6–1.3x. */
export function clampSpeed(speed: number): number {
  if (!Number.isFinite(speed)) return 1;
  return clamp(speed, MIN_SPEED, MAX_SPEED);
}

/** Зажать длину crossfade в диапазон 150–250 мс (обычная фраза). */
export function clampCrossfade(ms: number): number {
  if (!Number.isFinite(ms)) return DEFAULT_CROSSFADE_MS;
  return clamp(ms, MIN_CROSSFADE_MS, MAX_CROSSFADE_MS);
}

/**
 * Зажать длину crossfade с учётом режима: для дактиля нижняя граница 0 (переход
 * может быть короче 150 мс — буквы склеиваются почти вплотную), верхняя — 250.
 */
export function clampCrossfadeFor(ms: number, mode: CrossfadeMode = "phrase"): number {
  if (!Number.isFinite(ms)) {
    return mode === "dactyl" ? DACTYL_CROSSFADE_MS : DEFAULT_CROSSFADE_MS;
  }
  const min = mode === "dactyl" ? MIN_DACTYL_CROSSFADE_MS : MIN_CROSSFADE_MS;
  return clamp(ms, min, MAX_CROSSFADE_MS);
}

/** Длительность клипа в секундах при скорости 1x. */
function clipDuration(clip: QueueClip): number {
  if (clip.duration > 0) return clip.duration;
  // Клип без явной длительности: считаем по кадрам и частоте.
  return clip.frames / clip.fps;
}

/**
 * Спланировать очередь клипов: посчитать тайминги отрезков с учётом скорости,
 * crossfade и пауз в нейтральной позе.
 *
 * Зоны блендинга не могут занять больше половины клипа, иначе вход и выход
 * наложились бы друг на друга; для коротких клипов (дактиль на букву) crossfade
 * автоматически ужимается.
 */
export function planQueue(clips: QueueClip[], options: QueuePlanOptions = {}): QueuePlan {
  const mode = options.mode ?? "phrase";
  const speed = clampSpeed(options.speed ?? 1);
  const fallbackCrossfade = mode === "dactyl" ? DACTYL_CROSSFADE_MS : DEFAULT_CROSSFADE_MS;
  const crossfadeMs = clampCrossfadeFor(options.crossfadeMs ?? fallbackCrossfade, mode);
  const gapMs = Math.max(0, options.gapMs ?? 0);

  const segments: Segment[] = [];
  let cursorMs = 0;

  for (let i = 0; i < clips.length; i += 1) {
    const clip = clips[i];
    const durationMs = (clipDuration(clip) / speed) * 1000;

    const isFirst = i === 0;
    const isLast = i === clips.length - 1;

    // Перехода нет только при единственном клипе.
    const single = clips.length === 1;
    const maxFade = durationMs / 2;
    const fade = Math.min(crossfadeMs, maxFade);
    const fadeInMs = !single && !isFirst ? fade : 0;
    const fadeOutMs = !single && !isLast ? fade : 0;

    // Отрезок начинается в момент старта зоны входа (голова совпадает с хвостом
    // предыдущего клипа), поэтому время соседей перекрывается.
    const startMs = cursorMs;
    const endMs = startMs + durationMs;
    segments.push({ index: i, startMs, endMs, durationMs, speed, fadeInMs, fadeOutMs });

    // Следующий клип начинается за `crossfadeMs` до конца текущего — но не
    // раньше середины (иначе перекрытие было бы больше, чем сам клип).
    cursorMs = endMs - fadeOutMs + gapMs;
  }

  const totalMs = segments.length > 0 ? segments[segments.length - 1].endMs : 0;
  return { segments, totalMs, speed, crossfadeMs, gapMs, mode };
}

/**
 * Номер кадра клипа в момент `timeMs` (0..frames-1) при скорости отрезка.
 * Время считается от начала показа клипа (не от начала зоны входа).
 */
export function frameAt(segment: Segment, clip: { frames: number; fps: number }, timeMs: number): number {
  const local = timeMs - segment.startMs;
  if (local <= 0) return 0;
  const frame = Math.floor((local / 1000) * clip.fps * segment.speed);
  return clamp(frame, 0, Math.max(0, clip.frames - 1));
}

/** Найти отрезок, который показывается в момент `timeMs`, или `null`. */
export function segmentAt(plan: QueuePlan, timeMs: number): Segment | null {
  for (const segment of plan.segments) {
    if (timeMs >= segment.startMs && timeMs < segment.endMs) return segment;
  }
  if (timeMs >= plan.totalMs && plan.segments.length > 0) {
    return plan.segments[plan.segments.length - 1];
  }
  return null;
}

/**
 * Прогресс входа в отрезок `index` в момент `timeMs`: 0 — полностью предыдущий
 * кадр (прошлый клип или нейтральная поза), 1 — текущий клип. Вне зоны входа
 * возвращает 1. Зона входа — это первая половина перекрытия с предыдущим
 * клипом, то есть `fadeInMs` от `startMs`.
 */
export function blendAt(plan: QueuePlan, index: number, timeMs: number): number {
  const segment = plan.segments[index];
  if (!segment || segment.fadeInMs <= 0) return 1;
  const fadeEnd = segment.startMs + segment.fadeInMs;
  if (timeMs <= segment.startMs) return 0;
  if (timeMs >= fadeEnd) return 1;
  return (timeMs - segment.startMs) / segment.fadeInMs;
}

/**
 * Прогресс ухода последнего клипа в нейтральную позу: 0 — клип ещё виден,
 * 1 — нейтраль. Для остальных отрезков всегда 0.
 */
export function tailNeutralAt(plan: QueuePlan, index: number, timeMs: number): number {
  const last = plan.segments[plan.segments.length - 1];
  const segment = plan.segments[index];
  if (!segment || segment !== last || segment.fadeOutMs > 0) return 0;
  const tailStart = segment.endMs - NEUTRAL_FADE_MS;
  if (timeMs <= tailStart) return 0;
  if (timeMs >= segment.endMs) return 1;
  return (timeMs - tailStart) / NEUTRAL_FADE_MS;
}

/** Привести раскодированный клип к описанию для планировщика. */
export function toQueueClip(clip: Pick<DecodedClip, "frames" | "fps">): QueueClip {
  return { duration: clip.frames / clip.fps, fps: clip.fps, frames: clip.frames };
}
