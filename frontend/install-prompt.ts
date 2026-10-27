/**
 * Предложение установки PWA (этап G2, FR-27).
 *
 * После входа в комнату студенту предлагается установить приложение на домашний
 * экран. Предложение **необязательное**: его можно закрыть, и оно больше не
 * появится (отметка в `localStorage`). Сама страница работает и без установки.
 *
 * Два пути установки различаются браузером:
 *  - Android/Chrome и Chromium умеют `beforeinstallprompt` — сохраняем событие
 *    и по нажатию вызываем `event.prompt()`;
 *  - iOS/Safari такого события не даёт — показываем инструкцию «Поделиться →
 *    На экран Домой».
 *
 * Здесь живёт **чистая** часть: какой способ показать, нужно ли показывать
 * вообще и текст подсказки. Браузерные вызовы за тонким классом
 * `InstallPrompt`, который можно подменить в тестах (среда vitest — Node).
 */

/** Способ установки, который показываем студенту. */
export type InstallMethod = "native" | "ios";

/** Способ установки или `null`, если предлагать нечего. */
export type InstallOffer = InstallMethod | null;

/** Ключ отметки «предложение закрыли/установили» в `localStorage`. */
export const INSTALL_PROMPT_KEY = "gluho-nemye:install-prompt:v1";

/** Тексты подсказок под заголовком карточки. */
export const INSTALL_PROMPT_TEXTS: Record<InstallMethod, string> = {
  native: "Установите приложение, чтобы комната открывалась быстрее и жесты брались из кэша.",
  ios: "Нажмите «Поделиться», затем «На экран Домой» — комната откроется как приложение.",
};

/** Заголовок карточки предложения. */
export const INSTALL_PROMPT_TITLE = "Установить приложение?";

/**
 * Система/браузер, важные для выбора способа установки. Значения читаются из
 * `navigator.userAgent` и проверяются чистой функцией, чтобы её можно было
 * прогнать на примерах в тестах.
 */
export type InstallEnvironment = {
  /** Уже запущено как установленное приложение (standalone/PWA). */
  standalone: boolean;
  /** iOS (iPhone/iPad/iPod) — там только ручная инструкция. */
  ios: boolean;
  /** Safari на iOS поддерживает «На экран Домой»; Chrome на iOS — нет. */
  iosSafari: boolean;
  /** Браузер умеет `beforeinstallprompt` (Chromium на Android/десктопе). */
  supportsBeforeInstallPrompt: boolean;
};

/** Определить окружение по `userAgent` и признаку standalone-режима. */
export function installEnvironment(
  userAgent: string,
  options: {
    standalone?: boolean;
    displayModeStandalone?: boolean;
    supportsBeforeInstallPrompt?: boolean;
    /** `navigator.maxTouchPoints` — отличает iPadOS 13+ от настольного macOS. */
    maxTouchPoints?: number;
  } = {},
): InstallEnvironment {
  const ua = userAgent || "";
  const iosDirect = /iphone|ipad|ipod/i.test(ua);
  // iPadOS 13+ представляется как macOS (`MacIntel`), но имеет сенсорный экран.
  const ipadOs = /macintosh/i.test(ua) && (options.maxTouchPoints ?? 0) > 1;
  const iosFamily = iosDirect || ipadOs;
  const iosSafari = iosFamily && /safari/i.test(ua) && !/crios|fxios|edgios/i.test(ua);
  return {
    standalone: options.standalone === true || options.displayModeStandalone === true,
    ios: iosFamily,
    iosSafari,
    supportsBeforeInstallPrompt: options.supportsBeforeInstallPrompt === true,
  };
}

/**
 * Что предложить студенту: `native`, `ios` или ничего.
 *
 * Порядок проверок важен: уже установленное приложение не предлагаем; сохранённое
 * событие `beforeinstallprompt` — самый удобный путь; на iOS Safari — инструкция;
 * остальным (Safari/Firefox на десктопе) ничего не показываем, чтобы не давать
 * заведомо нерабочую подсказку.
 */
export function installOffer(
  environment: InstallEnvironment,
  options: { dismissed?: boolean } = {},
): InstallOffer {
  if (environment.standalone) return null;
  if (options.dismissed === true) return null;
  if (environment.supportsBeforeInstallPrompt) return "native";
  if (environment.iosSafari) return "ios";
  return null;
}

/** Отметка «предложение показано и закрыто» в `localStorage`. */
export type InstallPromptStorage = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem?: (key: string) => void;
};

function resolveStorage(
  storage: InstallPromptStorage | null | undefined,
): InstallPromptStorage | null {
  if (storage !== undefined) return storage;
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/** Предложение уже закрыто/принято в этом браузере. */
export function isInstallDismissed(storage?: InstallPromptStorage | null): boolean {
  const store = resolveStorage(storage);
  if (!store) return false;
  try {
    return store.getItem(INSTALL_PROMPT_KEY) === "dismissed";
  } catch {
    return false;
  }
}

/** Запомнить, что студент закрыл (или принял) предложение. */
export function markInstallDismissed(storage?: InstallPromptStorage | null): void {
  const store = resolveStorage(storage);
  if (!store) return;
  try {
    store.setItem(INSTALL_PROMPT_KEY, "dismissed");
  } catch {
    // Приватный режим или переполнение: просто не запоминаем — не критично.
  }
}

/** Сбросить отметку (нужно кнопке «Показать снова» и тестам). */
export function resetInstallDismissed(storage?: InstallPromptStorage | null): void {
  const store = resolveStorage(storage);
  try {
    store?.removeItem?.(INSTALL_PROMPT_KEY);
  } catch {
    // см. выше
  }
}

/** Событие `beforeinstallprompt` в объёме, который нам нужен. */
export type BeforeInstallPromptEvent = {
  prompt: () => Promise<void> | void;
  userChoice?: Promise<{ outcome: "accepted" | "dismissed" }>;
};

/** Медиазапрос режима отображения (standalone устанавливает система). */
export type MediaQueryLike = {
  matches: boolean;
  addEventListener?: (type: "change", listener: (event: { matches: boolean }) => void) => void;
};

export type InstallPromptOptions = {
  /** Корень карточки (ищем кнопки и статус внутри). */
  root: HTMLElement;
  /** Хранилище отметок; `null` отключает запоминание (в тестах). */
  storage?: InstallPromptStorage | null;
  /** Строка `userAgent`; по умолчанию из `navigator`. */
  userAgent?: string;
  /** Медиазапрос `display-mode: standalone`; по умолчанию создаётся сам. */
  displayModeQuery?: MediaQueryLike | null;
  /** Подписка на `beforeinstallprompt`; по умолчанию — на `window`. */
  subscribeBeforeInstallPrompt?: (
    handler: (event: BeforeInstallPromptEvent) => void,
  ) => void;
  /** Вызывается при закрытии карточки (для тестов и уборки). */
  onDismiss?: () => void;
};

/**
 * Карточка предложения установки: показывает/скрывает разметку, вызывает
 * системный диалог и запоминает отказ.
 *
 * Класс намеренно не зависит от `room-live.ts`: страница передаёт корень
 * карточки и подписки, а логика остаётся здесь.
 */
export class InstallPrompt {
  private readonly root: HTMLElement;
  private readonly storage: InstallPromptStorage | null;
  private readonly userAgent: string;
  private readonly displayModeQuery: MediaQueryLike | null;
  private deferredEvent: BeforeInstallPromptEvent | null = null;
  private method: InstallMethod | null = null;
  private dismissed = false;
  private onDismiss: (() => void) | undefined;

  constructor(options: InstallPromptOptions) {
    this.root = options.root;
    this.storage = options.storage ?? null;
    this.userAgent = options.userAgent ?? globalThis.navigator?.userAgent ?? "";
    this.displayModeQuery =
      options.displayModeQuery !== undefined
        ? options.displayModeQuery
        : defaultDisplayModeQuery();
    this.dismissed = isInstallDismissed(this.storage);

    const subscribe =
      options.subscribeBeforeInstallPrompt ??
      ((handler) => {
        globalThis.addEventListener?.("beforeinstallprompt", (event) => {
          // Не даём браузеру показать свой мини-бар: покажем свою карточку.
          event.preventDefault();
          handler(event as unknown as BeforeInstallPromptEvent);
        });
      });
    subscribe((event) => this.captureEvent(event));

    this.bindButtons(options.onDismiss);
    this.refresh();
  }

  /** Способ, которым предлагается установка (для тестов и диагностики). */
  get offer(): InstallOffer {
    return this.method;
  }

  /** Отложенное системное событие установки, если оно уже пришло. */
  private captureEvent(event: BeforeInstallPromptEvent): void {
    this.deferredEvent = event;
    this.refresh();
  }

  private currentEnvironment(): InstallEnvironment {
    return installEnvironment(this.userAgent, {
      standalone: this.displayModeQuery?.matches === true,
      supportsBeforeInstallPrompt: this.deferredEvent !== null,
      maxTouchPoints: globalThis.navigator?.maxTouchPoints ?? 0,
    });
  }

  /** Пересчитать способ и показать карточку, если есть что предлагать. */
  refresh(): void {
    const offer = installOffer(this.currentEnvironment(), { dismissed: this.dismissed });
    this.method = offer;
    this.root.hidden = offer === null;
    this.root.dataset.method = offer ?? "";
    if (offer === null) return;

    const hint = this.root.querySelector<HTMLElement>("[data-install-hint]");
    if (hint) hint.textContent = INSTALL_PROMPT_TEXTS[offer];

    const acceptButton = this.root.querySelector<HTMLElement>("[data-install-accept]");
    // На iOS системного диалога нет — кнопку «Установить» прячем, оставляя
    // инструкцию, чтобы не обещать несуществующее действие.
    if (acceptButton) acceptButton.hidden = offer !== "native";
  }

  /** Нажатие «Установить»: системный диалог Chromium. */
  async accept(): Promise<"accepted" | "dismissed" | "unavailable"> {
    if (!this.deferredEvent) return "unavailable";
    const event = this.deferredEvent;
    // Событие одноразовое: после вызова его нельзя использовать повторно.
    this.deferredEvent = null;
    try {
      await event.prompt();
      const choice = await event.userChoice;
      if (choice?.outcome === "accepted") {
        this.dismissed = true;
        markInstallDismissed(this.storage);
        this.refresh();
        return "accepted";
      }
    } catch {
      // Браузер мог отклонить вызов — тогда считаем, что установка не началась.
    }
    this.refresh();
    return "dismissed";
  }

  /** Закрыть предложение и больше его не показывать. */
  dismiss(): void {
    this.dismissed = true;
    markInstallDismissed(this.storage);
    this.method = null;
    this.root.hidden = true;
    this.onDismiss?.();
  }

  private bindButtons(onDismiss?: () => void): void {
    this.onDismiss = onDismiss;
    this.root.querySelector("[data-install-accept]")?.addEventListener("click", () => {
      void this.accept();
    });
    this.root.querySelector("[data-install-dismiss]")?.addEventListener("click", () => {
      this.dismiss();
    });
  }
}

/** Медиазапрос `display-mode: standalone` в браузере (или `null`). */
function defaultDisplayModeQuery(): MediaQueryLike | null {
  try {
    return globalThis.matchMedia?.("(display-mode: standalone)") ?? null;
  } catch {
    return null;
  }
}
