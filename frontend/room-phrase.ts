/**
 * Показ живой фразы на странице студента (E3): аватар, очередь клипов и
 * субтитры. Модуль тяжёлый (Three.js/VRM), поэтому `room-live.ts` загружает
 * его динамически только при первом событии `utterance`.
 */

import { Avatar, type AvatarStatus } from "./avatar";
import { decodeClip } from "./clip";
import { ClipPlayer } from "./clip-player";
import {
  PhraseQueue,
  fetchClipBytes,
  loadClipQueue,
  type LoadedClip,
  type UtteranceEvent,
} from "./room-clips";
import {
  SubtitleView,
  alignTokens,
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
  private readonly speed: number;
  private readonly onDisplayStarted?: (utterance: UtteranceEvent) => void;
  private player: ClipPlayer | null = null;
  private activeResolve: (() => void) | null = null;
  private disposed = false;

  constructor(root: HTMLElement, options: RoomPhraseOptions = {}) {
    this.speed = Math.min(1.3, Math.max(0.6, options.speed ?? 1));
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

    // Текст и слова появляются сразу; клипы и аватар могут догружаться.
    // С этого момента фраза считается показанной: очередь уже доиграла
    // предыдущие фразы, поэтому задержка отражает реальное отставание (E4).
    this.renderSubtitles(utterance);
    this.onDisplayStarted?.(utterance);
    this.setStatus(utterance.degraded ? "Фраза показана только субтитрами." : "Загрузка клипов…");

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
        speed: this.speed,
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

  /** Без VRM или клипов подсвечиваем слова по длительности клипов. */
  private async playSubtitlesOnly(loaded: LoadedClip[]): Promise<void> {
    if (loaded.length === 0) {
      this.setStatus("Клипы не найдены: фраза показана субтитрами.");
      await delay(1500);
      return;
    }
    for (const item of loaded) {
      if (this.disposed) return;
      this.subtitles.highlight(item.wordIndex);
      const seconds = item.clip.frames / Math.max(item.clip.fps, 1);
      await delay(Math.max(200, (seconds * 1000) / this.speed));
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
