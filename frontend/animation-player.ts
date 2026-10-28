/**
 * Проигрывание анимационных клипов (H1) через `AnimationMixer`.
 *
 * Рядом с `clip-player.ts` (landmarks + Kalidokit) это второй путь показа:
 * готовая анимация уже содержит позы костей, поэтому ретаргет не нужен.
 * Плеер держит очередь клипов, играет их подряд с crossfade и возвращает
 * модель в нейтраль после последнего. Тайминги — по времени `AnimationMixer`,
 * поэтому скорость меняется на ходу без пересборки очереди.
 *
 * Ограничение шаблона: смешанные фразы (часть жестов — анимации, часть —
 * landmaks-дактиль) пока не поддерживаются одним плеером; точка расширения
 * описана в `docs/ANIMATIONS.md`.
 */

import type { VRM } from "@pixiv/three-vrm";
import {
  AnimationMixer,
  LoopOnce,
  type AnimationAction,
  type AnimationClip,
} from "three";

import { DEFAULT_CROSSFADE_MS, MAX_CROSSFADE_MS, MIN_CROSSFADE_MS } from "./clip-queue";

/** Элемент очереди: клип и слово субтитра, которое он показывает. */
export type AnimationQueueItem = {
  clip: AnimationClip;
  /** Индекс слова в субтитрах для подсветки; -1 — не подсвечивать. */
  wordIndex?: number;
};

export type AnimationPlayerOptions = {
  /** Скорость показа 0.6–1.3x. */
  speed?: number;
  /** Зациклить (тестовая страница). */
  loop?: boolean;
  /** Длина перехода между клипами, мс (150–250). */
  crossfadeMs?: number;
  /** Переход к очередному клипу. */
  onClip?: (index: number) => void;
  /** Очередь доиграна. */
  onEnd?: () => void;
};

/**
 * Длина crossfade для анимации: та же граница, что у фразы (150–250 мс),
 * но не больше половины самого короткого клипа, иначе переход «съест» жест.
 */
export function animationCrossfadeMs(
  requested: number | undefined,
  shortestDurationMs: number,
): number {
  const clamped = Math.min(
    MAX_CROSSFADE_MS,
    Math.max(MIN_CROSSFADE_MS, requested ?? DEFAULT_CROSSFADE_MS),
  );
  if (!Number.isFinite(shortestDurationMs) || shortestDurationMs <= 0) return clamped;
  return Math.max(0, Math.min(clamped, shortestDurationMs / 2));
}

/** Плеер очереди анимаций на одной VRM-модели. */
export class AnimationPlayer {
  private readonly vrm: VRM;
  private readonly options: AnimationPlayerOptions;
  private readonly mixer: AnimationMixer;
  private items: AnimationQueueItem[] = [];
  private actions: AnimationAction[] = [];
  private index = 0;
  private speed: number;
  private frame: number | null = null;
  private lastTime = 0;
  private disposed = false;

  constructor(vrm: VRM, options: AnimationPlayerOptions = {}) {
    this.vrm = vrm;
    this.options = options;
    this.speed = Math.min(1.3, Math.max(0.6, options.speed ?? 1));
    this.mixer = new AnimationMixer(vrm.scene);
  }

  /** Загрузить очередь и подготовить действия; модель пока не двигается. */
  loadQueue(items: AnimationQueueItem[]): void {
    this.stop();
    this.items = items;
    this.index = 0;
    this.actions = items.map((item) => {
      const action = this.mixer.clipAction(item.clip);
      action.loop = LoopOnce;
      action.clampWhenFinished = true;
      return action;
    });
  }

  /** Начать показ с первого клипа. */
  start(): void {
    if (this.disposed || this.items.length === 0 || this.frame !== null) return;
    this.index = 0;
    this.lastTime = performance.now();
    this.playCurrent(0);
    this.frame = requestAnimationFrame(this.tick);
  }

  /** Скорость на ходу (F8): меняем timeScale, не пересобирая очередь. */
  setSpeed(speed: number): void {
    this.speed = Math.min(1.3, Math.max(0.6, speed));
    this.mixer.timeScale = this.speed;
  }

  stop(): void {
    if (this.frame !== null) {
      cancelAnimationFrame(this.frame);
      this.frame = null;
    }
    this.mixer.stopAllAction();
    for (const action of this.actions) action.reset();
  }

  dispose(): void {
    this.disposed = true;
    this.stop();
    this.mixer.uncacheRoot(this.vrm.scene);
  }

  private playCurrent(index: number): void {
    const action = this.actions[index];
    if (!action) return;
    const previous = index > 0 ? this.actions[index - 1] : null;
    action.reset().play();
    if (previous) {
      const shortest = Math.min(
        this.items[index - 1].clip.duration,
        this.items[index].clip.duration,
      );
      const fadeSeconds =
        animationCrossfadeMs(this.options.crossfadeMs, shortest * 1000) / 1000;
      if (fadeSeconds > 0) previous.crossFadeTo(action, fadeSeconds, false);
    }
    this.options.onClip?.(index);
  }

  private advance(): void {
    if (this.index + 1 < this.items.length) {
      this.index += 1;
      this.playCurrent(this.index);
      return;
    }
    if (this.options.loop && this.items.length > 0) {
      this.index = 0;
      this.mixer.stopAllAction();
      this.playCurrent(0);
      return;
    }
    this.finish();
  }

  private finish(): void {
    this.stop();
    this.options.onEnd?.();
  }

  private readonly tick = (now: number): void => {
    if (this.disposed) return;
    const delta = Math.min(0.1, Math.max(0, (now - this.lastTime) / 1000));
    this.lastTime = now;
    this.mixer.update(delta * this.speed);

    const current = this.actions[this.index];
    if (current && current.time >= current.getClip().duration) {
      this.advance();
    }
    if (this.frame !== null) {
      this.frame = requestAnimationFrame(this.tick);
    }
  };
}
