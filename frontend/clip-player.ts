/**
 * Проигрывание клипов на аватаре (C3 + C4): один клип или очередь с блендингом.
 *
 * Игрок берёт раскодированные клипы (C2), сглаживает landmarks фильтром One
 * Euro, ретаргетит их через `retarget.ts` и применяет к VRM (`vrm-rig.ts`).
 * Очередь собирается планировщиком (`clip-queue.ts`): клипы идут подряд с
 * crossfade 150–250 мс, а между фразами аватар стоит в нейтральной позе (FR-12).
 * Скорость воспроизведения ограничена 0.6–1.3x (FR-13, FR-16).
 *
 * Один `tick` продвигает очередь на кадр клипа. При показе Slovo браузер
 * интерполирует повороты между этими кадрами с частотой отрисовки.
 */

import type { VRM } from "@pixiv/three-vrm";

import type { DecodedClip } from "./clip";
import { crossfade, fadeToNeutral, lerpFrames, neutralFrame } from "./clip-blend";
import { planQueue, toQueueClip, type CrossfadeMode, type QueuePlan } from "./clip-queue";
import { OneEuroLandmarks } from "./one-euro";
import { retargetParts, splitFrame, type RetargetedFrame } from "./retarget";
import { prepareSlovoMotion } from "./slovo-motion";
import { retargetSlovo, slovoSpace } from "./slovo-retarget";
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
  /** Режим склейки: `phrase` или `dactyl` (укороченный переход, C5). */
  mode?: CrossfadeMode;
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
  private animationFrame: number | null = null;
  private renderFrom = neutralFrame();
  private renderTo = neutralFrame();
  private rendered = neutralFrame();
  private motion: RetargetedFrame[] | null = null;
  private tailFrames = 0;
  private gapFadeFrames = 0;
  private coordinateSpaces: ReturnType<typeof slovoSpace>[] = [];
  private previous = neutralFrame();
  private last = neutralFrame();

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
    this.coordinateSpaces = clips.map(slovoSpace);
    this.previous = this.last = this.rendered = neutralFrame();
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
            mode: this.options.mode,
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
    if (this.clips.length === 0 || this.isPlaying) return;
    const fps = this.options.fps ?? this.clips[0].fps;
    const speed = this.plan?.speed ?? 1;
    const interval = 1000 / (fps * speed);
    if (this.coordinateSpaces.some(Boolean) && typeof globalThis.requestAnimationFrame === "function") {
      this.startInterpolated(interval);
    } else {
      this.timer = globalThis.setInterval(() => this.tick(), interval) as unknown as number;
    }
  }

  /** Между отметками клипа поза обновляется с частотой отрисовки экрана. */
  private startInterpolated(interval: number): void {
    let boundary: number | undefined;
    // Для одиночного клипа нейтраль смешивается с первым кадром до жеста,
    // чтобы вступление не ослабляло движение в начале записи.
    let frameDuration = this.clips.length === 1 && this.frameIndex === 0 ? 130 : interval;
    this.renderFrom = this.renderTo = this.rendered;
    const step = (): void => {
      this.renderFrom = this.renderTo;
      this.tick();
    };
    const render = (now: number): void => {
      const scheduled = this.animationFrame;
      if (boundary === undefined) {
        boundary = now;
        step();
      } else {
        if (now - boundary > frameDuration + 4 * interval) {
          // После скрытой вкладки продолжить жест без мгновенного догона.
          boundary = now;
          frameDuration = interval;
          step();
        } else {
          while (now - boundary >= frameDuration && this.animationFrame === scheduled) {
            boundary += frameDuration;
            frameDuration = interval;
            step();
          }
        }
      }
      if (this.animationFrame !== scheduled) return;
      const progress = (now - boundary) / frameDuration;
      this.draw(this.renderFrom === this.renderTo
        ? this.renderTo
        : frameDuration === interval
          ? lerpFrames(this.renderFrom, this.renderTo, progress)
          : crossfade(this.renderFrom, this.renderTo, progress));
      this.animationFrame = globalThis.requestAnimationFrame(render);
    };
    this.animationFrame = globalThis.requestAnimationFrame(render);
  }

  private draw(frame: RetargetedFrame): void {
    this.rendered = frame;
    if (frame.bones || frame.leftFingers || frame.rightFingers || frame.face) {
      applyRetargetedFrame(this.vrm, frame);
    } else {
      resetToNeutral(this.vrm);
    }
  }

  private present(frame: RetargetedFrame): void {
    if (this.animationFrame === null) {
      this.draw(frame);
    } else {
      this.renderTo = frame;
    }
  }

  private edgeFadeFrames(): number {
    const clip = this.clips[this.clipIndex];
    return this.animationFrame !== null && this.coordinateSpaces[this.clipIndex]
      ? Math.max(1, Math.round((this.options.fps ?? clip.fps) * (this.plan?.speed ?? 1) * 0.13))
      : 0;
  }

  /** Остановить воспроизведение (очередь остаётся загруженной). */
  stop(): void {
    if (this.animationFrame !== null) {
      globalThis.cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }
    if (this.timer !== null) {
      globalThis.clearInterval(this.timer);
      this.timer = null;
    }
  }

  /**
   * Сменить скорость на ходу (C7): пересобрать план очереди под новую скорость,
   * сохранив текущий клип и кадр. Играющая очередь продолжает идти, а не
   * останавливается на начале.
   */
  setSpeed(speed: number): void {
    if (!Number.isFinite(speed) || speed === this.options.speed) return;
    this.options.speed = speed;
    if (!this.plan || this.clips.length === 0) return;

    const playing = this.isPlaying;
    this.stop();
    this.plan = planQueue(this.clips.map(toQueueClip), {
      speed: this.options.speed,
      crossfadeMs: this.options.crossfadeMs,
      gapMs: this.options.gapMs,
      mode: this.options.mode,
    });
    this.computeIntervals();
    if (playing) this.start();
  }

  /**
   * Сменить паузу между клипами на ходу (F8): на красном уровне отставания
   * сервер присылает ``gapMs = 0``, и пауза пропускается без остановки показа.
   */
  setGapMs(gapMs: number): void {
    if (!Number.isFinite(gapMs)) return;
    const next = Math.max(0, gapMs);
    if (next === this.options.gapMs) return;
    this.options.gapMs = next;
    if (next === 0) this.gapLeft = 0;
    if (!this.plan || this.clips.length === 0) return;

    const playing = this.isPlaying;
    this.stop();
    this.plan = planQueue(this.clips.map(toQueueClip), {
      speed: this.options.speed,
      crossfadeMs: this.options.crossfadeMs,
      gapMs: this.options.gapMs,
      mode: this.options.mode,
    });
    this.computeIntervals();
    if (playing) this.start();
  }

  /** Один шаг воспроизведения: показать текущий кадр и перейти к следующему. */
  tick(): void {
    if (this.clips.length === 0) return;

    // Плавный уход последнего клипа в нейтральную позу (ТЗ 5.4, FR-12).
    if (this.tailLeft > 0) {
      this.tailLeft -= 1;
      const progress = 1 - this.tailLeft / this.tailFrames;
      this.present(fadeToNeutral(this.last, progress));
      if (this.tailLeft === 0) this.finish();
      return;
    }

    // Пауза в нейтральной позе между фразами.
    if (this.gapLeft > 0) {
      this.gapLeft -= 1;
      const elapsed = this.gapFrames - this.gapLeft;
      this.present(this.gapFadeFrames > 0 && elapsed < this.gapFadeFrames
        ? fadeToNeutral(this.last, elapsed / this.gapFadeFrames)
        : neutralFrame());
      if (this.gapLeft === 0) {
        this.last = neutralFrame();
        this.advanceClip();
      }
      return;
    }

    const clip = this.clips[this.clipIndex];
    if (this.frameIndex >= clip.frames) {
      // Клип закончился.
      if (this.clipIndex < this.clips.length - 1) {
        // Пауза в нейтральной позе или сразу следующий клип.
        if (this.gapFrames > 0) {
          this.gapLeft = this.gapFrames;
          this.gapFadeFrames = Math.min(this.gapFrames, this.edgeFadeFrames());
          return;
        }
        this.advanceClip();
      } else if (this.options.loop) {
        this.restart();
      } else {
        this.tailFrames = this.crossfadeFrames || this.edgeFadeFrames();
        if (this.tailFrames > 0) this.tailLeft = this.tailFrames;
        else this.finish();
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
    this.previous = this.last;
    this.resetSmoothing();
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
    this.previous = this.last;
    this.options.onClip?.(0);
  }

  /** Завершить очередь: остановиться и вернуть модель в нейтральную позу. */
  private finish(): void {
    this.stop();
    this.draw(neutralFrame());
    this.options.onEnd?.();
  }

  /** Показать кадр клипа: сгладить, ретаргетить и смешать с соседним кадром. */
  private showFrame(clip: DecodedClip, frame: number): void {
    const current = this.retarget(clip, frame);
    // Сохраняем показанную позу: короткий клип может закончиться ещё в переходе.
    const fade = Math.min(this.crossfadeFrames, clip.frames - 1);
    this.last = frame < fade ? crossfade(this.previous, current, frame / fade) : current;
    this.present(this.last);
  }

  /** Отфильтровать landmarks кадра и ретаргетить их в позы. */
  private retarget(clip: DecodedClip, frame: number): RetargetedFrame {
    const space = this.coordinateSpaces[this.clipIndex];
    if (space && this.options.smoothing) {
      this.motion ??= prepareSlovoMotion(this.vrm, clip, space === "legacy");
      return this.motion[frame];
    }
    const parts = splitFrame(clip, frame);
    // Кисти Slovo уже сглажены при конвертации. Второй фильтр ослабит быстрый жест.
    if (this.options.smoothing && space === null) {
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
    return space ? retargetSlovo(this.vrm, parts, space === "legacy") : retargetParts(parts);
  }

  /** Сбросить фильтры сглаживания (при смене очереди и в цикле). */
  private resetSmoothing(): void {
    this.motion = null;
    this.smoothing = {
      pose: new OneEuroLandmarks(),
      hand_l: new OneEuroLandmarks(),
      hand_r: new OneEuroLandmarks(),
      face: new OneEuroLandmarks(),
    };
  }

  /** Идёт ли воспроизведение. */
  get isPlaying(): boolean {
    return this.timer !== null || this.animationFrame !== null;
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
    this.motion = null;
    this.plan = null;
    this.frameIndex = 0;
    this.clipIndex = 0;
  }
}
