/**
 * Клипы живой фразы (E3): разбор ссылок из события `utterance`, загрузка
 * файлов и последовательная очередь показа.
 *
 * Сервер уже собрал клипы в порядке показа и приложил `token_index` к каждому.
 * Здесь нет Three.js и DOM: модуль можно проверить в vitest, а тяжёлый плеер
 * (`room-phrase.ts`) использует его уже в браузере.
 */

import { decodeClip, type DecodedClip } from "./clip";
import type { PlaybackPolicy } from "./lag-policy";
import { alignTokens, wordIndexForToken, type UtteranceGlosses } from "./subtitles";

/** Вид клипа: жест, число или буква дактиля. */
export type ClipKind = "sign" | "number" | "fingerspell";

/** Формат файла клипа: landmarks MediaPipe или готовая анимация (H1). */
export type ClipFormat = "landmarks" | "animation";

/** Ссылка на клип в событии `utterance` (порядок уже совпадает с показом). */
export type UtteranceClipRef = {
  token_index: number;
  kind: ClipKind;
  gloss: string;
  url: string;
  format?: ClipFormat;
  /** Имя анимации внутри GLB/VRMA; пусто — первая (H1). */
  animation_name?: string;
  fps?: number;
  frames?: number;
  duration_ms?: number;
  version?: number;
  id?: number;
};

/** Фраза события `utterance`: глоссы E1 + клипы словаря. */
export type UtteranceEvent = {
  id: number;
  seq: number;
  text: string;
  glosses: UtteranceGlosses;
  degraded: boolean;
  /** F8: скорость, паузы и признак сжатия, посчитанные сервером. */
  playback?: PlaybackPolicy;
  ts: string;
  clips?: UtteranceClipRef[];
};

/** Загруженный клип вместе с исходной ссылкой и словом для подсветки. */
export type LoadedClip = {
  ref: UtteranceClipRef;
  clip: DecodedClip;
  wordIndex: number;
};

/** Функция загрузки байтов клипа (подменяется в тестах). */
export type ClipFetcher = (url: string) => Promise<ArrayBuffer | Uint8Array>;
/** Функция декодирования клипа (подменяется в тестах). */
export type ClipDecoder = (input: ArrayBuffer | Uint8Array) => Promise<DecodedClip>;

function isClipRef(value: unknown): value is UtteranceClipRef {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  if (typeof item.url !== "string" || item.url.length === 0) return false;
  if (typeof item.token_index !== "number" || !Number.isInteger(item.token_index)) {
    return false;
  }
  return true;
}

/** Достать валидные ссылки из события, сохранив серверный порядок показа. */
export function clipRefsFromEvent(utterance: UtteranceEvent): UtteranceClipRef[] {
  if (!Array.isArray(utterance.clips)) return [];
  return utterance.clips.filter(isClipRef).map((ref) => ({
    ...ref,
    kind: ref.kind === "number" || ref.kind === "fingerspell" ? ref.kind : "sign",
    gloss: typeof ref.gloss === "string" ? ref.gloss : "",
    format: ref.format === "animation" ? "animation" : "landmarks",
    animation_name:
      typeof ref.animation_name === "string" ? ref.animation_name : "",
  }));
}

/** Браузерная загрузка `.json.gz`; ошибки HTTP превращаем в исключение. */
export async function fetchClipBytes(url: string): Promise<Uint8Array> {
  const response = await fetch(url, { headers: { Accept: "application/gzip" } });
  if (!response.ok) {
    throw new Error(`Клип не загружен: HTTP ${response.status}`);
  }
  return new Uint8Array(await response.arrayBuffer());
}

/**
 * Загрузить и раскодировать клипы параллельно, сохранив порядок ссылок.
 * Битый/недоступный клип пропускается: фраза останется в субтитрах, а
 * остальные клипы очереди продолжат играть.
 */
export async function loadClipQueue(
  utterance: UtteranceEvent,
  options: {
    fetcher?: ClipFetcher;
    decoder?: ClipDecoder;
    onError?: (ref: UtteranceClipRef, error: unknown) => void;
  } = {},
): Promise<LoadedClip[]> {
  const fetcher = options.fetcher ?? fetchClipBytes;
  const decoder = options.decoder ?? decodeClip;
  const refs = clipRefsFromEvent(utterance);
  const words = alignTokens(utterance.glosses);

  const loaded = await Promise.all(
    refs.map(async (ref): Promise<LoadedClip | null> => {
      try {
        const bytes = await fetcher(ref.url);
        const clip = await decoder(bytes);
        return {
          ref,
          clip,
          wordIndex: wordIndexForToken(words, ref.token_index),
        };
      } catch (error) {
        options.onError?.(ref, error);
        return null;
      }
    }),
  );

  return loaded.filter((item): item is LoadedClip => item !== null);
}

/**
 * Очередь фраз: показываем строго по одной, не теряя новые события и
 * отбрасывая повторы по `seq` (например, историю после переподключения).
 */
export class PhraseQueue<T extends { seq: number }> {
  private readonly items: T[] = [];
  private readonly play: (item: T) => Promise<void>;
  private readonly onError?: (error: unknown, item: T) => void;
  private running: Promise<void> | null = null;
  private lastSeq = 0;
  private stopped = false;

  constructor(
    play: (item: T) => Promise<void>,
    options: { onError?: (error: unknown, item: T) => void } = {},
  ) {
    this.play = play;
    this.onError = options.onError;
  }

  /** Сколько фраз ещё ждёт своей очереди. */
  get pending(): number {
    return this.items.length;
  }

  /** Поставить фразу в очередь; `false` — повтор или очередь остановлена. */
  enqueue(item: T): boolean {
    if (this.stopped) return false;
    if (!Number.isFinite(item.seq) || item.seq <= this.lastSeq) return false;
    this.lastSeq = item.seq;
    this.items.push(item);
    this.start();
    return true;
  }

  /** Дождаться, пока очередь доиграет все уже поставленные фразы. */
  waitForIdle(): Promise<void> {
    return this.running ?? Promise.resolve();
  }

  /** Остановить очередь; текущая фраза доигрывает, новые не принимаются. */
  stop(): void {
    this.stopped = true;
    this.items.length = 0;
  }

  private start(): void {
    if (this.running) return;
    this.running = this.drain();
  }

  private async drain(): Promise<void> {
    try {
      while (this.items.length > 0) {
        const item = this.items.shift();
        if (!item) break;
        try {
          await this.play(item);
        } catch (error) {
          this.onError?.(error, item);
        }
      }
    } finally {
      this.running = null;
      // Пока доигрывала предыдущая фраза, могла прийти новая.
      if (this.items.length > 0 && !this.stopped) this.start();
    }
  }
}
