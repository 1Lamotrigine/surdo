/**
 * Показ живой фразы на странице студента (E3): аватар, очередь клипов и
 * субтитры. Модуль тяжёлый (Three.js/VRM), поэтому `room-live.ts` загружает
 * его динамически только при первом событии `utterance`.
 */

import { Avatar, type AvatarStatus } from "./avatar";
import { loadAnimationBundle } from "./animation-clip";
import { AnimationPlayer, animationCrossfadeMs, type AnimationQueueItem } from "./animation-player";
import { decodeClip } from "./clip";
import { ClipPlayer } from "./clip-player";
import {
  DEFAULT_PLAYBACK_POLICY,
  effectivePlaybackSpeed,
  normalizePlaybackPolicy,
  playbackGapMs,
  type NormalizedPlaybackPolicy,
  type PlaybackPolicy,
} from "./lag-policy";
import {
  PhraseQueue,
  clipRefsFromEvent,
  fetchClipBytes,
  loadClipQueue,
  type LoadedClip,
  type UtteranceClipRef,
  type UtteranceEvent,
} from "./room-clips";
import {
  SubtitleView,
  alignTokens,
  wordIndexForToken,
  type UtteranceGlosses,
} from "./subtitles";

export type RoomPhraseOptions = {
  /** URL VRM-модели; без него остаются субтитры. */
  modelUrl?: string;
  /** Скорость показа 0.6–1.3x (по умолчанию 1). */
  speed?: number;
  /** Фраза действительно начала показываться (E4: display_started). */
  onDisplayStarted?: (utterance: UtteranceEvent) => void;
};

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/**
 * Одна сцена на страницу: очередь фраз, загрузка клипов и подсветка слов.
 * Субтитры обновляются сразу, а аватар и клипы догоняют их по мере загрузки.
 */
export class RoomPhrasePlayer {
  private readonly subtitles: SubtitleView;
  private readonly status: HTMLElement | null;
  private readonly avatar: Avatar | null;
  private readonly ready: Promise<void>;
  private readonly queue: PhraseQueue<UtteranceEvent>;
  private readonly baseSpeed: number;
  private readonly onDisplayStarted?: (utterance: UtteranceEvent) => void;
  private playbackPolicy: NormalizedPlaybackPolicy = DEFAULT_PLAYBACK_POLICY;
  private player: ClipPlayer | null = null;
  private animationPlayer: AnimationPlayer | null = null;
  private activeResolve: (() => void) | null = null;
  private disposed = false;

  constructor(root: HTMLElement, options: RoomPhraseOptions = {}) {
    this.baseSpeed = Math.min(1.3, Math.max(0.6, options.speed ?? 1));
    this.onDisplayStarted = options.onDisplayStarted;
    this.status = root.querySelector<HTMLElement>("[data-room-phrase-status]");

    const avatarStage = root.querySelector<HTMLElement>("[data-room-avatar-stage]");
    const subtitleRoot = root.querySelector<HTMLElement>("[data-room-subtitles]");
    if (!subtitleRoot) {
      throw new Error("Не найден контейнер субтитров комнаты");
    }
    this.subtitles = new SubtitleView(subtitleRoot, { size: "large", theme: "dark" });

    if (avatarStage) {
      try {
        this.avatar = new Avatar({
          container: avatarStage,
          onStatus: (state, detail) => this.onAvatarStatus(state, detail),
        });
      } catch {
        this.avatar = null;
      }
      if (this.avatar) {
        this.ready = this.avatar.load(options.modelUrl);
      } else {
        this.ready = Promise.resolve();
        this.setStatus("WebGL недоступен: показываем субтитры.");
      }
    } else {
      this.avatar = null;
      this.ready = Promise.resolve();
      this.setStatus("Область аватара не найдена: показываем субтитры.");
    }

    this.queue = new PhraseQueue((utterance) => this.play(utterance), {
      onError: () => this.setStatus("Не удалось показать фразу."),
    });
  }

  /** Показать распознанный текст сразу, не дожидаясь глосс. */
  showAsrText(text: string): void {
    if (!text.trim()) return;
    const utterance: UtteranceGlosses = { text, tokens: [] };
    this.subtitles.applyStyles({ size: "large", theme: "dark" });
    this.subtitles.render(utterance, alignTokens(utterance));
  }

  /** Поставить фразу в очередь; повторы по `seq` отбрасываются. */
  enqueue(utterance: UtteranceEvent): boolean {
    return this.queue.enqueue(utterance);
  }

  /**
   * Применить политику догона к текущей и следующим фразам (F8).
   *
   * Событие `playback` приходит после `display_started`, когда фраза уже
   * играет: скорость и паузу меняем на ходу, не начиная очередь заново.
   * Сжатие уже показанного текста невозможно, но следующая фраза будет
   * обработана сервером с учётом нового отставания.
   */
  setPlaybackPolicy(policy: PlaybackPolicy): void {
    const normalized = normalizePlaybackPolicy(policy);
    this.playbackPolicy = normalized;
    const speed = effectivePlaybackSpeed(this.baseSpeed, normalized);
    this.player?.setSpeed(speed);
    this.player?.setGapMs(playbackGapMs(normalized));
    this.animationPlayer?.setSpeed(speed);
  }

  /** Дождаться конца очереди (диагностика и тесты). */
  waitForIdle(): Promise<void> {
    return this.queue.waitForIdle();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.queue.stop();
    this.activeResolve?.();
    this.activeResolve = null;
    this.player?.dispose();
    this.player = null;
    this.animationPlayer?.dispose();
    this.animationPlayer = null;
    this.avatar?.dispose();
  }

  private setStatus(text: string): void {
    if (this.status) this.status.textContent = text;
  }

  private onAvatarStatus(state: AvatarStatus, detail?: string): void {
    if (state === "loading") {
      this.setStatus("Загрузка аватара…");
    } else if (state === "error") {
      this.setStatus(
        detail ? `Аватар недоступен: ${detail}. Показываем субтитры.` : "Аватар недоступен.",
      );
    } else if (this.avatar?.model) {
      this.setStatus("Аватар готов.");
    } else {
      this.setStatus("Аватар не настроен: показываем субтитры.");
    }
  }

  private renderSubtitles(utterance: UtteranceEvent): void {
    const glosses: UtteranceGlosses = {
      ...utterance.glosses,
      text: utterance.glosses?.text || utterance.text,
    };
    this.subtitles.applyStyles({
      size: "large",
      theme: "dark",
      degraded: utterance.degraded,
    });
    this.subtitles.render(glosses, alignTokens(glosses));
  }

  private async play(utterance: UtteranceEvent): Promise<void> {
    if (this.disposed) return;

    this.playbackPolicy = normalizePlaybackPolicy(
      utterance.playback ?? this.playbackPolicy,
    );

    // Текст и слова появляются сразу; клипы и аватар могут догружаться.
    // С этого момента фраза считается показанной: очередь уже доиграла
    // предыдущие фразы, поэтому задержка отражает реальное отставание (E4).
    this.renderSubtitles(utterance);
    this.onDisplayStarted?.(utterance);
    this.setStatus(utterance.degraded ? "Фраза показана только субтитрами." : "Загрузка клипов…");

    // H1: если вся фраза — готовые анимации, играем через AnimationMixer.
    const refs = clipRefsFromEvent(utterance);
    const animationRefs = refs.filter((ref) => ref.format === "animation");
    if (animationRefs.length > 0) {
      if (animationRefs.length !== refs.length) {
        // Смешанная фраза (анимации + дактиль-landmarks) — шаблон H1.
        this.setStatus("Смешанные клипы пока не поддерживаются: играем landmarks.");
      } else {
        await this.ready;
        if (this.disposed) return;
        const vrmForAnimation = this.avatar?.model ?? null;
        if (!vrmForAnimation) {
          await this.playAnimationSubtitlesOnly(utterance, animationRefs);
          return;
        }
        this.setStatus("Показ фразы…");
        await this.playAnimations(vrmForAnimation, utterance, animationRefs);
        this.subtitles.highlight(-1);
        return;
      }
    }

    const loadedPromise = loadClipQueue(utterance, {
      fetcher: fetchClipBytes,
      decoder: decodeClip,
      onError: () => this.setStatus("Часть клипов недоступна — показываем субтитры."),
    });

    await this.ready;
    const loaded = await loadedPromise;
    if (this.disposed) return;

    const vrm = this.avatar?.model ?? null;
    if (!vrm || loaded.length === 0) {
      await this.playSubtitlesOnly(loaded);
      return;
    }

    this.setStatus("Показ фразы…");
    await this.playClips(vrm, loaded);
    this.subtitles.highlight(-1);
  }

  private async playClips(
    vrm: NonNullable<Avatar["model"]>,
    loaded: LoadedClip[],
  ): Promise<void> {
    const clips = loaded.map((item) => item.clip);
    const policy = this.playbackPolicy;
    await new Promise<void>((resolve) => {
      let settled = false;
      const done = (): void => {
        if (settled) return;
        settled = true;
        this.activeResolve = null;
        this.player?.dispose();
        this.player = null;
        resolve();
      };
      this.activeResolve = done;

      const player = new ClipPlayer(vrm, {
        speed: effectivePlaybackSpeed(this.baseSpeed, policy),
        gapMs: playbackGapMs(policy),
        mode: "phrase",
        onClip: (index) => {
          this.subtitles.highlight(loaded[index]?.wordIndex ?? -1);
        },
        onEnd: done,
      });
      this.player = player;
      player.loadQueue(clips);
      this.subtitles.highlight(loaded[0]?.wordIndex ?? -1);
      player.start();
    });
  }

  /** Показать фразу из готовых анимаций (H1) через `AnimationMixer`. */
  private async playAnimations(
    vrm: NonNullable<Avatar["model"]>,
    utterance: UtteranceEvent,
    refs: UtteranceClipRef[],
  ): Promise<void> {
    const words = alignTokens(utterance.glosses);
    const items: (AnimationQueueItem | null)[] = await Promise.all(
      refs.map(async (ref) => {
        try {
          const bundle = await loadAnimationBundle(ref.url);
          const clip = bundle.clips[0];
          if (!clip) return null;
          return {
            clip,
            wordIndex: wordIndexForToken(words, ref.token_index),
          };
        } catch {
          this.setStatus("Часть анимаций недоступна — показываем субтитры.");
          return null;
        }
      }),
    );
    const queue = items.filter((item): item is AnimationQueueItem => item !== null);
    if (queue.length === 0) {
      await this.playAnimationSubtitlesOnly(utterance, refs);
      return;
    }

    const speed = effectivePlaybackSpeed(this.baseSpeed, this.playbackPolicy);
    const shortestMs = Math.min(...queue.map((item) => item.clip.duration * 1000));
    await new Promise<void>((resolve) => {
      let settled = false;
      const done = (): void => {
        if (settled) return;
        settled = true;
        this.activeResolve = null;
        this.animationPlayer?.dispose();
        this.animationPlayer = null;
        resolve();
      };
      this.activeResolve = done;

      const player = new AnimationPlayer(vrm, {
        speed,
        crossfadeMs: animationCrossfadeMs(200, shortestMs),
        onClip: (index) => this.subtitles.highlight(queue[index]?.wordIndex ?? -1),
        onEnd: done,
      });
      this.animationPlayer = player;
      player.loadQueue(queue);
      this.subtitles.highlight(queue[0]?.wordIndex ?? -1);
      player.start();
    });
  }

  /** Без VRM подсвечиваем слова по длительности анимаций. */
  private async playAnimationSubtitlesOnly(
    utterance: UtteranceEvent,
    refs: UtteranceClipRef[],
  ): Promise<void> {
    const words = alignTokens(utterance.glosses);
    const speed = effectivePlaybackSpeed(this.baseSpeed, this.playbackPolicy);
    for (const ref of refs) {
      if (this.disposed) return;
      this.subtitles.highlight(wordIndexForToken(words, ref.token_index));
      const duration = ref.duration_ms && ref.duration_ms > 0 ? ref.duration_ms : 1000;
      await delay(Math.max(200, duration / speed));
    }
    this.subtitles.highlight(-1);
  }

  /** Без VRM или клипов подсвечиваем слова по длительности клипов. */
  private async playSubtitlesOnly(loaded: LoadedClip[]): Promise<void> {
    if (loaded.length === 0) {
      this.setStatus("Клипы не найдены: фраза показана субтитрами.");
      await delay(1500);
      return;
    }
    const speed = effectivePlaybackSpeed(this.baseSpeed, this.playbackPolicy);
    for (const item of loaded) {
      if (this.disposed) return;
      this.subtitles.highlight(item.wordIndex);
      const seconds = item.clip.frames / Math.max(item.clip.fps, 1);
      await delay(Math.max(200, (seconds * 1000) / speed));
    }
    this.subtitles.highlight(-1);
  }
}

/** Создать сцену по разметке страницы студента. */
export function createRoomPhrasePlayer(
  root: HTMLElement,
  options: Pick<RoomPhraseOptions, "onDisplayStarted"> = {},
): RoomPhrasePlayer {
  const modelUrl = root.dataset.avatarModelUrl || undefined;
  const speed = Number(root.dataset.avatarSpeed ?? "1");
  return new RoomPhrasePlayer(root, {
    modelUrl,
    speed: Number.isFinite(speed) ? speed : 1,
    onDisplayStarted: options.onDisplayStarted,
  });
}
