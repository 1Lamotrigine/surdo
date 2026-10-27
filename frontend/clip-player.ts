/**
 * Проигрывание клипов на аватаре (C3 + C4): один клип или очередь с блендингом.
 *
 * Игрок берёт раскодированные клипы (C2), сглаживает landmarks фильтром One
 * Euro, ретаргетит их через `retarget.ts` и применяет к VRM (`vrm-rig.ts`).
 * Очередь собирается планировщиком (`clip-queue.ts`): клипы идут подряд с
 * crossfade 150–250 мс, а между фразами аватар стоит в нейтральной позе (FR-12).
 * Скорость воспроизведения ограничена 0.6–1.3x (FR-13, FR-16).
 *
 * Время идёт **покадрам**: один `tick` — один кадр текущего клипа (как и в C3).
 * Так воспроизведение детерминировано, тесты не зависят от таймера, а crossfade
 * считается в кадрах из миллисекунд (длина перехода делится на длительность
 * кадра). Плавность добавляет блендинг кадров ретаргета (`clip-blend.ts`).
 */

import type { VRM } from "@pixiv/three-vrm";

import type { DecodedClip } from "./clip";
import { crossfade, fadeToNeutral, neutralFrame } from "./clip-blend";
import { planQueue, toQueueClip, type QueuePlan } from "./clip-queue";
import { OneEuroLandmarks } from "./one-euro";
import { retargetParts, splitFrame, type RetargetedFrame } from "./retarget";
import { applyRetargetedFrame, resetToNeutral } from "./vrm-rig";

export type ClipPlayerOptions = {
  /** Частота кадров, если играем не в реальном времени (иначе берётся `clip.fps`). */
  fps?: number;
  /** Скорость воспроизведения: 0.6–1.3x (FR-13, FR-16). */
  speed?: number;
  /** Зациклить очередь (для тестовой страницы). */
  loop?: boolean;
  /** Сглаживание One Euro вкл/выкл (на записанных клипах может быть уже сглажено). */
  smoothing?: boolean;
  /** Длина crossfade между клипами, мс (150–250, ТЗ 5.4). */
  crossfadeMs?: number;
  /** Пауза в нейтральной позе между фразами, мс. */
  gapMs?: number;
  /** Вызывается после последнего кадра (если `loop` выключен). */
  onEnd?: () => void;
  /** Вызывается при переходе к очередному клипу очереди. */
  onClip?: (index: number) => void;
};

/**
 * Игрок клипов на одной модели: таймер, курсор кадра и номер текущего клипа.
 * `start`/`stop` управляют воспроизведением, `dispose` освобождает таймер.
 */
export class ClipPlayer {
  private readonly vrm: VRM;
  private readonly options: Required<Pick<ClipPlayerOptions, "speed" | "loop" | "smoothing">> &
    ClipPlayerOptions;
  private clips: DecodedClip[] = [];
  /** План очереди (единый источник таймингов: crossfade, пауза, скорость). */
  private plan: QueuePlan | null = null;
  /** Длина crossfade в кадрах (0 — блендинга нет: один клип). */
  private crossfadeFrames = 0;
  /** Длина паузы между клипами в кадрах. */
  private gapFrames = 0;
  private smoothing: Record<string, OneEuroLandmarks> = {};
  /** Курсор кадра текущего клипа (число уже показанных кадров клипа). */
  private frameIndex = 0;
  /** Номер клипа очереди, который показывается сейчас. */
  private clipIndex = 0;
  /** Пауза между клипами в кадрах (счётчик, уменьшается на тик). */
  private gapLeft = 0;
  /** Остаток кадров плавного ухода последнего клипа в нейтральную позу. */
  private tailLeft = 0;
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

  /** Загрузить один клип и вернуть модель в нейтральную позу перед стартом. */
  load(clip: DecodedClip): void {
    this.loadQueue([clip]);
  }

  /**
   * Загрузить очередь клипов: спланировать тайминги (crossfade, пауза,
   * скорость), сбросить курсоры и вернуть модель в нейтральную позу.
   */
  loadQueue(clips: DecodedClip[]): void {
    this.stop();
    this.clips = clips;
    this.frameIndex = 0;
    this.clipIndex = 0;
    this.gapLeft = 0;
    this.tailLeft = 0;
    this.resetSmoothing();
    this.plan =
      clips.length > 0
        ? planQueue(clips.map(toQueueClip), {
            speed: this.options.speed,
            crossfadeMs: this.options.crossfadeMs,
            gapMs: this.options.gapMs,
          })
        : null;
    this.computeIntervals();
    resetToNeutral(this.vrm);
  }

  /**
   * Пересчитать crossfade и паузу в кадрах по плану очереди. Планировщик уже
   * зажал скорость (0.6–1.3x) и длину перехода (150–250 мс); здесь только
   * перевод миллисекунд в кадры при текущей скорости.
   */
  private computeIntervals(): void {
    if (!this.plan || this.clips.length === 0) {
      this.crossfadeFrames = 0;
      this.gapFrames = 0;
      return;
    }
    const fps = this.options.fps ?? this.clips[0].fps;
    const framesPerMs = (fps * this.plan.speed) / 1000;
    // Первый отрезок с зоной входа — второй клип; для единственного клипа 0.
    const fadeMs = this.plan.segments.length > 1 ? this.plan.segments[1].fadeInMs : 0;
    this.crossfadeFrames = Math.max(0, Math.round(fadeMs * framesPerMs));
    this.gapFrames = Math.max(0, Math.round(this.plan.gapMs * framesPerMs));
  }

  /** Начать воспроизведение с текущего места. */
  start(): void {
    if (this.clips.length === 0 || this.timer !== null) return;
    const fps = this.options.fps ?? this.clips[0].fps;
    const speed = this.plan?.speed ?? 1;
    const interval = 1000 / (fps * speed);
    this.timer = globalThis.setInterval(() => this.tick(), interval) as unknown as number;
  }

  /** Остановить воспроизведение (очередь остаётся загруженной). */
  stop(): void {
    if (this.timer !== null) {
      globalThis.clearInterval(this.timer);
      this.timer = null;
    }
  }

  /** Один шаг воспроизведения: показать текущий кадр и перейти к следующему. */
  tick(): void {
    if (this.clips.length === 0) return;

    // Плавный уход последнего клипа в нейтральную позу (ТЗ 5.4, FR-12).
    if (this.tailLeft > 0) {
      this.tailLeft -= 1;
      const progress = 1 - this.tailLeft / this.crossfadeFrames;
      const last = this.retarget(this.clips[this.clipIndex], this.clips[this.clipIndex].frames - 1);
      applyRetargetedFrame(this.vrm, fadeToNeutral(last, progress));
      if (this.tailLeft === 0) this.finish();
      return;
    }

    // Пауза в нейтральной позе между фразами.
    if (this.gapLeft > 0) {
      this.gapLeft -= 1;
      applyRetargetedFrame(this.vrm, neutralFrame());
      if (this.gapLeft === 0) this.advanceClip();
      return;
    }

    const clip = this.clips[this.clipIndex];
    if (this.frameIndex >= clip.frames) {
      // Клип закончился.
      if (this.clipIndex < this.clips.length - 1) {
        // Пауза в нейтральной позе или сразу следующий клип.
        if (this.gapFrames > 0) {
          this.gapLeft = this.gapFrames;
          return;
        }
        this.advanceClip();
      } else if (this.options.loop) {
        this.restart();
      } else if (this.crossfadeFrames > 0) {
        // Последний клип очереди: плавный уход в нейтральную позу.
        this.tailLeft = this.crossfadeFrames;
        return;
      } else {
        this.finish();
        return;
      }
    }

    const activeClip = this.clips[this.clipIndex];
    const frame = Math.min(this.frameIndex, activeClip.frames - 1);
    this.showFrame(activeClip, frame);
    this.frameIndex += 1;
  }

  /** Перейти к следующему клипу очереди (сбросить курсор и открыть crossfade). */
  private advanceClip(): void {
    this.clipIndex += 1;
    this.frameIndex = 0;
    this.options.onClip?.(this.clipIndex);
  }

  /** Вернуться к началу очереди (режим цикла). */
  private restart(): void {
    this.clipIndex = 0;
    this.frameIndex = 0;
    this.gapLeft = 0;
    this.tailLeft = 0;
    this.resetSmoothing();
    this.options.onClip?.(0);
  }

  /** Завершить очередь: остановиться и вернуть модель в нейтральную позу. */
  private finish(): void {
    this.stop();
    resetToNeutral(this.vrm);
    this.options.onEnd?.();
  }

  /** Показать кадр клипа: сгладить, ретаргетить и смешать с соседним кадром. */
  private showFrame(clip: DecodedClip, frame: number): void {
    const current = this.retarget(clip, frame);

    // Зона входа: смешиваем с последним кадром предыдущего клипа (или с
    // нейтральной позой для первого клипа очереди — ТЗ 5.4).
    if (this.crossfadeFrames > 0 && frame < this.crossfadeFrames) {
      const previous = this.previousFrame();
      const progress = frame / this.crossfadeFrames;
      applyRetargetedFrame(this.vrm, crossfade(previous, current, progress));
      return;
    }
    applyRetargetedFrame(this.vrm, current);
  }

  /** Последний кадр предыдущего клипа (или нейтраль, если его нет). */
  private previousFrame(): RetargetedFrame {
    if (this.clipIndex === 0) return neutralFrame();
    const previous = this.clips[this.clipIndex - 1];
    return this.retarget(previous, previous.frames - 1);
  }

  /** Отфильтровать landmarks кадра и ретаргетить их в позы. */
  private retarget(clip: DecodedClip, frame: number): RetargetedFrame {
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
    return retargetParts(parts);
  }

  /** Сбросить фильтры сглаживания (при смене очереди и в цикле). */
  private resetSmoothing(): void {
    this.smoothing = {
      pose: new OneEuroLandmarks(),
      hand_l: new OneEuroLandmarks(),
      hand_r: new OneEuroLandmarks(),
      face: new OneEuroLandmarks(),
    };
  }

  /** Идёт ли воспроизведение. */
  get isPlaying(): boolean {
    return this.timer !== null;
  }

  /** Текущий кадр внутри текущего клипа (для отладки и тестов). */
  get currentFrame(): number {
    return this.frameIndex;
  }

  /** Номер текущего клипа очереди (для отладки и тестов). */
  get currentClip(): number {
    return this.clipIndex;
  }

  /** Число клипов в очереди. */
  get clipCount(): number {
    return this.clips.length;
  }

  /** Длина crossfade в кадрах (для отладки и тестов). */
  get crossfadeFrameCount(): number {
    return this.crossfadeFrames;
  }

  /** План очереди (для отладки и тестов). */
  get queue(): QueuePlan | null {
    return this.plan;
  }

  dispose(): void {
    this.stop();
    this.clips = [];
    this.plan = null;
    this.frameIndex = 0;
    this.clipIndex = 0;
  }
}
