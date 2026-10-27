/**
 * Микрофон преподавателя с VAD в браузере (F7).
 *
 * `vad-web` держит модель Silero VAD в Web Worker и отдаёт готовую фразу по
 * паузе. Модуль загружается только после нажатия «Включить микрофон», поэтому
 * тяжёлые зависимости не попадают в первый экран панели. Каждая готовая фраза
 * превращается в WAV и уходит в F6 endpoint; отправка последовательная, чтобы
 * сервер получил фразы в том же порядке, в каком их сказали.
 *
 * Текстовая форма рядом остаётся запасным режимом (FR-7): ошибка микрофона не
 * блокирует ввод текстом.
 */

import {
  encodeWav,
  uploadPhrase,
  type UploadPhraseOptions,
} from "./audio-phrase";

export type SpeechData = {
  audioData: Float32Array;
  sampleRate: number;
  startTime: number;
  endTime: number;
};

export type VadHandlers = {
  onSpeechStart?: () => void;
  onSpeechEnd?: () => void;
  onSpeechAvailable?: (data: SpeechData) => void;
};

export type VadDispose = () => Promise<void>;
export type VadRecorder = (handlers: VadHandlers) => Promise<VadDispose>;

export type MicrophoneSetupOptions = {
  /** URL F6 endpoint для комнаты. */
  phraseUrl: string;
  /** CSRF-токен страницы панели. */
  csrfToken: string;
  /** Подмена VAD в тестах. */
  loadRecorder?: () => Promise<VadRecorder>;
  /** Подмена отправки в тестах. */
  upload?: (options: UploadPhraseOptions) => Promise<void>;
  fetchImpl?: typeof fetch;
};

export type MicrophoneElements = {
  panel: HTMLElement | null;
  toggle: HTMLButtonElement | null;
  status: HTMLElement | null;
  count: HTMLElement | null;
};

type StatusState = "idle" | "loading" | "listening" | "speech" | "uploading" | "error";

const STATUS_IDLE = "Микрофон выключен. Можно ввести фразу текстом.";

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

/**
 * Понятные подсказки вместо технических имён ошибок браузера. Остальные
 * сообщения (например, от VAD или API) показываем как есть.
 */
export function microphoneErrorMessage(error: unknown): string {
  const raw = errorText(error).trim();
  const name =
    error && typeof error === "object" && "name" in error
      ? String((error as { name?: unknown }).name)
      : "";

  if (name === "NotAllowedError" || /permission|denied|запрещ/i.test(raw)) {
    return "Доступ к микрофону запрещён. Разрешите его в настройках браузера.";
  }
  if (name === "NotFoundError" || /no microphone|not found|не найден/i.test(raw)) {
    return "Микрофон не найден. Проверьте подключение.";
  }
  if (name === "NotReadableError" || /could not start|занят/i.test(raw)) {
    return "Микрофон занят другим приложением.";
  }
  if (/secure context|audioworklet|https/i.test(raw)) {
    return "Микрофон работает только по HTTPS или на localhost.";
  }
  return raw || "Не удалось включить микрофон.";
}

async function loadVadRecorder(): Promise<VadRecorder> {
  const { recordAudio } = await import("vad-web");
  return recordAudio;
}

/** Проверить браузер до загрузки тяжёлого VAD-модуля. */
export function microphoneSupportError(): string | null {
  if (typeof navigator === "undefined") {
    return "Браузер не поддерживает запись с микрофона.";
  }
  if (typeof window !== "undefined" && window.isSecureContext === false) {
    return "Микрофон работает только по HTTPS или на localhost.";
  }
  if (typeof AudioWorkletNode === "undefined") {
    return "Браузер не поддерживает AudioWorklet: обновите Chrome, Edge или Safari.";
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return "Браузер не поддерживает запись с микрофона.";
  }
  return null;
}

/**
 * Состояние и действия панели микрофона. Не читает DOM самостоятельно:
 * `setupMicrophone` находит элементы и передаёт их сюда.
 */
export class MicrophoneController {
  private readonly elements: MicrophoneElements;
  private readonly options: MicrophoneSetupOptions;
  private readonly upload: (options: UploadPhraseOptions) => Promise<void>;
  private recorder: VadDispose | null = null;
  private uploadChain: Promise<void> = Promise.resolve();
  private runToken = 0;
  private starting = false;
  private active = false;
  private speechActive = false;
  private disabled = false;
  private disposed = false;
  private pendingUploads = 0;
  private sentPhrases = 0;
  private lastError = "";

  constructor(elements: MicrophoneElements, options: MicrophoneSetupOptions) {
    this.elements = elements;
    this.options = options;
    this.upload = options.upload ?? uploadPhrase;
    // Разметка закрытой комнаты уже отключает кнопку — не включаем её обратно.
    this.disabled = elements.toggle?.disabled ?? false;
    if (this.disabled) this.lastError = "Комната закрыта: микрофон недоступен.";
    this.render();
  }

  get isActive(): boolean {
    return this.active;
  }

  get isStarting(): boolean {
    return this.starting;
  }

  get pending(): number {
    return this.pendingUploads;
  }

  async start(): Promise<void> {
    if (this.disposed || this.disabled || this.active || this.starting) return;
    // В тестах и при подменённом VAD проверку браузера пропускаем.
    if (!this.options.loadRecorder) {
      const supportError = microphoneSupportError();
      if (supportError) {
        this.lastError = supportError;
        this.render();
        return;
      }
    }
    const token = ++this.runToken;
    this.starting = true;
    this.lastError = "";
    this.render();

    try {
      const loadRecorder = this.options.loadRecorder ?? loadVadRecorder;
      const recorder = await loadRecorder();
      if (token !== this.runToken || this.disposed) return;

      const dispose = await recorder({
        onSpeechStart: () => this.onSpeechStart(),
        onSpeechEnd: () => this.onSpeechEnd(),
        onSpeechAvailable: (data) => this.onSpeechAvailable(data),
      });
      if (token !== this.runToken || this.disposed) {
        await dispose();
        return;
      }
      this.recorder = dispose;
      this.active = true;
      this.speechActive = false;
    } catch (error) {
      if (token === this.runToken && !this.disposed) {
        this.lastError = microphoneErrorMessage(error);
      }
    } finally {
      if (token === this.runToken) {
        this.starting = false;
        this.render();
      }
    }
  }

  async stop(): Promise<void> {
    if (this.disposed && !this.recorder) {
      this.active = false;
      this.starting = false;
      this.render();
      return;
    }
    this.runToken += 1;
    this.starting = false;
    const recorder = this.recorder;
    this.recorder = null;
    this.active = false;
    this.speechActive = false;
    this.render();

    if (!recorder) return;
    try {
      await recorder();
    } catch (error) {
      this.lastError = `Не удалось корректно остановить микрофон: ${errorText(error)}`;
    }
    this.render();
  }

  /** Комнату закрыли: выключить запись и больше не включать. */
  disable(message = "Комната закрыта: микрофон недоступен."): void {
    this.disabled = true;
    this.lastError = message;
    if (this.elements.toggle) this.elements.toggle.disabled = true;
    void this.stop();
    this.render();
  }

  async dispose(): Promise<void> {
    if (this.disposed) return;
    this.disposed = true;
    this.disabled = true;
    await this.stop();
    // Дождаться уже поставленных в очередь отправок перед уходом со страницы;
    // новая запись после dispose не начинается.
    await this.uploadChain.catch(() => undefined);
  }

  private onSpeechStart(): void {
    if (this.disposed) return;
    this.speechActive = true;
    this.lastError = "";
    this.render();
  }

  private onSpeechEnd(): void {
    if (this.disposed) return;
    this.speechActive = false;
    this.render();
  }

  private onSpeechAvailable(data: SpeechData): void {
    if (this.disposed || this.disabled || data.audioData.length === 0) return;
    this.speechActive = false;

    let wav: Uint8Array;
    try {
      wav = encodeWav(data.audioData, data.sampleRate);
    } catch (error) {
      this.lastError = `Не удалось упаковать фразу: ${errorText(error)}`;
      this.render();
      return;
    }

    this.pendingUploads += 1;
    this.render();
    const task = this.uploadChain.then(async () => {
      if (this.disposed) return;
      await this.upload({
        url: this.options.phraseUrl,
        csrfToken: this.options.csrfToken,
        audio: wav,
        filename: `phrase-${Date.now()}.wav`,
        fetchImpl: this.options.fetchImpl,
      });
    });
    this.uploadChain = task
      .then(() => {
        this.sentPhrases += 1;
        this.lastError = "";
      })
      .catch((error: unknown) => {
        this.lastError = `Не удалось отправить фразу: ${errorText(error)}`;
      })
      .finally(() => {
        this.pendingUploads = Math.max(0, this.pendingUploads - 1);
        this.render();
      });
  }

  private statusView(): { state: StatusState; text: string } {
    if (this.starting) {
      return { state: "loading", text: "Запрашиваем доступ к микрофону…" };
    }
    if (this.lastError) {
      return {
        state: "error",
        text: this.active
          ? `Микрофон работает. ${this.lastError}`
          : this.lastError,
      };
    }
    if (this.pendingUploads > 0) {
      return {
        state: "uploading",
        text: this.active
          ? `Отправляем фраз: ${this.pendingUploads}. Можно продолжать говорить.`
          : `Микрофон выключен. Отправляем оставшиеся фразы: ${this.pendingUploads}.`,
      };
    }
    if (this.speechActive) {
      return { state: "speech", text: "Слышу речь…" };
    }
    if (this.active) {
      return { state: "listening", text: "Слушаю. Скажите фразу и сделайте паузу." };
    }
    if (this.disabled) {
      return { state: "idle", text: "Микрофон недоступен." };
    }
    if (this.sentPhrases > 0) {
      return {
        state: "idle",
        text: `Микрофон выключен. Отправлено фраз: ${this.sentPhrases}.`,
      };
    }
    return { state: "idle", text: STATUS_IDLE };
  }

  private render(): void {
    const { panel, toggle, status, count } = this.elements;
    const view = this.statusView();

    if (panel) panel.dataset.state = view.state;
    if (status) {
      status.dataset.state = view.state;
      status.textContent = view.text;
    }
    if (toggle) {
      toggle.disabled = this.disabled || this.starting;
      toggle.textContent = this.starting
        ? "Включаем…"
        : this.active
          ? "Остановить микрофон"
          : "Включить микрофон";
      toggle.setAttribute("aria-pressed", String(this.active));
    }
    if (count) {
      const pending = this.pendingUploads > 0 ? ` · в очереди: ${this.pendingUploads}` : "";
      count.textContent =
        this.sentPhrases > 0 || this.pendingUploads > 0
          ? `Отправлено фраз: ${this.sentPhrases}${pending}`
          : "";
      count.hidden = count.textContent.length === 0;
    }
  }
}

/** Найти разметку микрофона в панели преподавателя и включить обработчики. */
export function setupMicrophone(
  root: HTMLElement,
  options: MicrophoneSetupOptions,
): MicrophoneController {
  const toggle = root.querySelector<HTMLButtonElement>("[data-mic-toggle]");
  const controller = new MicrophoneController(
    {
      panel: root,
      toggle,
      status: root.querySelector<HTMLElement>("[data-mic-status]"),
      count: root.querySelector<HTMLElement>("[data-mic-count]"),
    },
    options,
  );

  toggle?.addEventListener("click", () => {
    if (controller.isActive || controller.isStarting) {
      void controller.stop();
    } else {
      void controller.start();
    }
  });
  return controller;
}
