/**
 * Проигрывание клипа на аватаре (C3): очередь кадров, сглаживание и ретаргет.
 *
 * Игрок берёт раскодированный клип (C2), идёт по кадрам с частотой `fps`,
 * сглаживает landmarks фильтром One Euro и применяет позы к VRM. Блендинг
 * между клипами — этап C4, здесь один клип и возврат в нейтральную позу.
 */

import type { VRM } from "@pixiv/three-vrm";

import type { DecodedClip } from "./clip";
import { OneEuroLandmarks } from "./one-euro";
import { retargetParts, splitFrame } from "./retarget";
import { applyRetargetedFrame, resetToNeutral } from "./vrm-rig";

export type ClipPlayerOptions = {
  /** Частота кадров, если играем не в реальном времени (иначе берётся `clip.fps`). */
  fps?: number;
  /** Скорость воспроизведения: 0.6–1.3x (FR-13, FR-16). */
  speed?: number;
  /** Зациклить клип (для тестовой страницы). */
  loop?: boolean;
  /** Сглаживание One Euro вкл/выкл (на записанных клипах может быть уже сглажено). */
  smoothing?: boolean;
  /** Вызывается после последнего кадра (если `loop` выключен). */
  onEnd?: () => void;
};

/**
 * Игрок одного клипа на одной модели. Держит таймер и курсор кадра;
 * `start`/`stop` управляют воспроизведением, `dispose` освобождает таймер.
 */
export class ClipPlayer {
  private readonly vrm: VRM;
  private readonly options: Required<Pick<ClipPlayerOptions, "speed" | "loop" | "smoothing">> &
    ClipPlayerOptions;
  private clip: DecodedClip | null = null;
  private smoothing: Record<string, OneEuroLandmarks> = {};
  private frameIndex = 0;
  private timer: number | null = null;

  constructor(vrm: VRM, options: ClipPlayerOptions = {}) {
    this.vrm = vrm;
    this.options = {
      speed: options.speed ?? 1,
      loop: options.loop ?? false,
      smoothing: options.smoothing ?? true,
      ...options,
    };
  }

  /** Загрузить клип и вернуть модель в нейтральную позу перед стартом. */
  load(clip: DecodedClip): void {
    this.stop();
    this.clip = clip;
    this.frameIndex = 0;
    this.smoothing = {
      pose: new OneEuroLandmarks(),
      hand_l: new OneEuroLandmarks(),
      hand_r: new OneEuroLandmarks(),
      face: new OneEuroLandmarks(),
    };
    resetToNeutral(this.vrm);
  }

  /** Начать воспроизведение с текущего кадра. */
  start(): void {
    if (!this.clip || this.timer !== null) return;
    const fps = this.options.fps ?? this.clip.fps;
    const interval = 1000 / (fps * this.options.speed);
    this.timer = globalThis.setInterval(() => this.tick(), interval) as unknown as number;
  }

  /** Остановить воспроизведение (клип остаётся загруженным). */
  stop(): void {
    if (this.timer !== null) {
      globalThis.clearInterval(this.timer);
      this.timer = null;
    }
  }

  /** Один шаг воспроизведения: показать текущий кадр и перейти к следующему. */
  tick(): void {
    const clip = this.clip;
    if (!clip) return;

    if (this.frameIndex >= clip.frames) {
      if (!this.options.loop) {
        this.stop();
        resetToNeutral(this.vrm);
        this.options.onEnd?.();
        return;
      }
      this.frameIndex = 0;
    }

    this.showFrame(clip, this.frameIndex);
    this.frameIndex += 1;
  }

  /** Отфильтровать landmarks кадра и применить их к модели. */
  private showFrame(clip: DecodedClip, frame: number): void {
    const parts = splitFrame(clip, frame);
    if (this.options.smoothing) {
      for (const name of ["pose", "hand_l", "hand_r", "face"] as const) {
        const points = parts[name];
        if (points) {
          // Фильтр возвращает только {x,y,z}: сохраняем visibility позы,
          // иначе Kalidokit сбросит руки как «за кадром».
          const filtered = this.smoothing[name].filter(points);
          parts[name] = filtered.map((point, index) => ({
            ...point,
            visibility: points[index]?.visibility,
          }));
        }
      }
    }
    applyRetargetedFrame(this.vrm, retargetParts(parts));
  }

  /** Идёт ли воспроизведение. */
  get isPlaying(): boolean {
    return this.timer !== null;
  }

  /** Текущий кадр (для отладки и тестов). */
  get currentFrame(): number {
    return this.frameIndex;
  }

  dispose(): void {
    this.stop();
    this.clip = null;
    this.frameIndex = 0;
  }
}
