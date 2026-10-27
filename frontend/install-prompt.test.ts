/**
 * Тесты предложения установки PWA (G2, FR-27): выбор способа, отметка отказа
 * и поведение карточки. Среда vitest — Node без DOM, поэтому DOM-объекты
 * подменяются минимальными заглушками.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  INSTALL_PROMPT_KEY,
  INSTALL_PROMPT_TEXTS,
  InstallPrompt,
  installEnvironment,
  installOffer,
  isInstallDismissed,
  markInstallDismissed,
  resetInstallDismissed,
  type BeforeInstallPromptEvent,
  type InstallPromptStorage,
} from "./install-prompt";

const IPHONE_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const IPHONE_CHROME_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0 Mobile/15E148 Safari/604.1";
const ANDROID_CHROME_UA =
  "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36";
const DESKTOP_SAFARI_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("installEnvironment", () => {
  it("распознаёт iOS Safari", () => {
    const env = installEnvironment(IPHONE_UA);
    expect(env.ios).toBe(true);
    expect(env.iosSafari).toBe(true);
  });

  it("Chrome на iOS — это iOS, но не Safari", () => {
    const env = installEnvironment(IPHONE_CHROME_UA);
    expect(env.ios).toBe(true);
    expect(env.iosSafari).toBe(false);
  });

  it("Android Chrome узнаётся по поддержке beforeinstallprompt", () => {
    const env = installEnvironment(ANDROID_CHROME_UA, { supportsBeforeInstallPrompt: true });
    expect(env.ios).toBe(false);
    expect(env.supportsBeforeInstallPrompt).toBe(true);
  });

  it("iPadOS 13+ (Macintosh + сенсор) считается iOS", () => {
    const env = installEnvironment(DESKTOP_SAFARI_UA, { maxTouchPoints: 5 });
    expect(env.ios).toBe(true);
    expect(env.iosSafari).toBe(true);
  });

  it("настольный Mac без сенсора — не iOS", () => {
    const env = installEnvironment(DESKTOP_SAFARI_UA, { maxTouchPoints: 0 });
    expect(env.ios).toBe(false);
    expect(env.iosSafari).toBe(false);
  });

  it("standalone-режим фиксируется", () => {
    expect(installEnvironment(IPHONE_UA, { standalone: true }).standalone).toBe(true);
    expect(installEnvironment(IPHONE_UA, { displayModeStandalone: true }).standalone).toBe(true);
  });
});

describe("installOffer", () => {
  it("установленному приложению ничего не предлагаем", () => {
    const env = installEnvironment(ANDROID_CHROME_UA, { supportsBeforeInstallPrompt: true });
    expect(installOffer({ ...env, standalone: true })).toBeNull();
  });

  it("закрытое предложение не показываем снова", () => {
    const env = installEnvironment(ANDROID_CHROME_UA, { supportsBeforeInstallPrompt: true });
    expect(installOffer(env, { dismissed: true })).toBeNull();
  });

  it("Chromium предлагает системный диалог", () => {
    const env = installEnvironment(ANDROID_CHROME_UA, { supportsBeforeInstallPrompt: true });
    expect(installOffer(env)).toBe("native");
  });

  it("iOS Safari даёт инструкцию", () => {
    expect(installOffer(installEnvironment(IPHONE_UA))).toBe("ios");
  });

  it("десктопный Safari без события — без предложения", () => {
    expect(installOffer(installEnvironment(DESKTOP_SAFARI_UA))).toBeNull();
  });
});

/** Простое хранилище в памяти для проверки отметок. */
function memoryStorage(): InstallPromptStorage & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => void data.set(key, value),
    removeItem: (key) => void data.delete(key),
  };
}

describe("отметка отказа", () => {
  it("по умолчанию ничего не отмечено", () => {
    expect(isInstallDismissed(memoryStorage())).toBe(false);
  });

  it("запоминает отказ и умеет сбрасывать", () => {
    const storage = memoryStorage();
    markInstallDismissed(storage);
    expect(isInstallDismissed(storage)).toBe(true);
    expect(storage.data.get(INSTALL_PROMPT_KEY)).toBe("dismissed");

    resetInstallDismissed(storage);
    expect(isInstallDismissed(storage)).toBe(false);
  });

  it("битое хранилище не роняет проверку", () => {
    const broken: InstallPromptStorage = {
      getItem: () => {
        throw new Error("nope");
      },
      setItem: () => {
        throw new Error("nope");
      },
    };
    expect(isInstallDismissed(broken)).toBe(false);
    expect(() => markInstallDismissed(broken)).not.toThrow();
  });
});

/** Минимальный DOM-узел для карточки. */
function fakeCard(): {
  root: HTMLElement;
  hint: { textContent: string };
  accept: { hidden: boolean; click: () => void };
  dismiss: { click: () => void };
} {
  const listeners = new Map<string, () => void>();
  const make = (): { element: { hidden: boolean; click: () => void; addEventListener: (t: string, l: () => void) => void }; listeners: Map<string, () => void> } => {
    const element = {
      hidden: false,
      click: () => listeners.get("click")?.(),
      addEventListener: (type: string, listener: () => void) => void listeners.set(type, listener),
    };
    return { element, listeners };
  };
  const acceptNode = make();
  const dismissNode = make();
  const hint = { textContent: "" };
  const root = {
    hidden: true,
    dataset: {} as DOMStringMap,
    querySelector: (selector: string) => {
      if (selector === "[data-install-hint]") return hint;
      if (selector === "[data-install-accept]") return acceptNode.element;
      if (selector === "[data-install-dismiss]") return dismissNode.element;
      return null;
    },
  } as unknown as HTMLElement;
  return {
    root,
    hint,
    accept: acceptNode.element as { hidden: boolean; click: () => void },
    dismiss: dismissNode.element as { hidden: boolean; click: () => void },
  };
}

/** Подписка на beforeinstallprompt с ручным «выстрелом» события. */
function promptSubscription() {
  let handler: ((event: BeforeInstallPromptEvent) => void) | null = null;
  return {
    subscribe: (h: (event: BeforeInstallPromptEvent) => void) => {
      handler = h;
    },
    fire: (event: BeforeInstallPromptEvent) => handler?.(event),
  };
}

describe("InstallPrompt", () => {
  it("показывает системный путь и скрывает карточку по умолчанию", () => {
    const card = fakeCard();
    const { subscribe } = promptSubscription();
    const prompt = new InstallPrompt({
      root: card.root,
      storage: memoryStorage(),
      userAgent: ANDROID_CHROME_UA,
      displayModeQuery: { matches: false },
      subscribeBeforeInstallPrompt: subscribe,
    });

    // События ещё не было — показывать нечего.
    expect(prompt.offer).toBeNull();
    expect(card.root.hidden).toBe(true);
  });

  it("после beforeinstallprompt показывает карточку с системной кнопкой", () => {
    const card = fakeCard();
    const { subscribe, fire } = promptSubscription();
    new InstallPrompt({
      root: card.root,
      storage: memoryStorage(),
      userAgent: ANDROID_CHROME_UA,
      displayModeQuery: { matches: false },
      subscribeBeforeInstallPrompt: subscribe,
    });

    fire({ prompt: vi.fn().mockResolvedValue(undefined) });

    expect(card.root.hidden).toBe(false);
    expect(card.root.dataset.method).toBe("native");
    expect(card.hint.textContent).toBe(INSTALL_PROMPT_TEXTS.native);
    expect(card.accept.hidden).toBe(false);
  });

  it("на iOS показывает инструкцию и прячет кнопку установки", () => {
    const card = fakeCard();
    const { subscribe } = promptSubscription();
    const prompt = new InstallPrompt({
      root: card.root,
      storage: memoryStorage(),
      userAgent: IPHONE_UA,
      displayModeQuery: { matches: false },
      subscribeBeforeInstallPrompt: subscribe,
    });

    expect(prompt.offer).toBe("ios");
    expect(card.root.hidden).toBe(false);
    expect(card.hint.textContent).toBe(INSTALL_PROMPT_TEXTS.ios);
    // Системного диалога на iOS нет — кнопку «Установить» не показываем.
    expect(card.accept.hidden).toBe(true);
  });

  it("accept вызывает системный диалог и запоминает принятие", async () => {
    const card = fakeCard();
    const { subscribe, fire } = promptSubscription();
    const storage = memoryStorage();
    const promptFn = vi.fn().mockResolvedValue(undefined);
    const prompt = new InstallPrompt({
      root: card.root,
      storage,
      userAgent: ANDROID_CHROME_UA,
      displayModeQuery: { matches: false },
      subscribeBeforeInstallPrompt: subscribe,
    });
    fire({ prompt: promptFn, userChoice: Promise.resolve({ outcome: "accepted" }) });

    const result = await prompt.accept();

    expect(result).toBe("accepted");
    expect(promptFn).toHaveBeenCalled();
    expect(isInstallDismissed(storage)).toBe(true);
    expect(card.root.hidden).toBe(true);
  });

  it("отклонённый системный диалог не закрывает предложение навсегда", async () => {
    const card = fakeCard();
    const { subscribe, fire } = promptSubscription();
    const storage = memoryStorage();
    const prompt = new InstallPrompt({
      root: card.root,
      storage,
      userAgent: ANDROID_CHROME_UA,
      displayModeQuery: { matches: false },
      subscribeBeforeInstallPrompt: subscribe,
    });
    fire({ prompt: vi.fn(), userChoice: Promise.resolve({ outcome: "dismissed" }) });

    const result = await prompt.accept();

    expect(result).toBe("dismissed");
    expect(isInstallDismissed(storage)).toBe(false);
  });

  it("dismiss скрывает карточку и запоминает отказ", () => {
    const card = fakeCard();
    const { subscribe, fire } = promptSubscription();
    const storage = memoryStorage();
    const onDismiss = vi.fn();
    new InstallPrompt({
      root: card.root,
      storage,
      userAgent: ANDROID_CHROME_UA,
      displayModeQuery: { matches: false },
      subscribeBeforeInstallPrompt: subscribe,
      onDismiss,
    });
    fire({ prompt: vi.fn() });

    card.dismiss.click();

    expect(card.root.hidden).toBe(true);
    expect(isInstallDismissed(storage)).toBe(true);
    expect(onDismiss).toHaveBeenCalled();
  });

  it("уже установленное приложение не предлагает установку", () => {
    const card = fakeCard();
    const { subscribe, fire } = promptSubscription();
    new InstallPrompt({
      root: card.root,
      storage: memoryStorage(),
      userAgent: ANDROID_CHROME_UA,
      displayModeQuery: { matches: true },
      subscribeBeforeInstallPrompt: subscribe,
    });

    fire({ prompt: vi.fn() });

    expect(card.root.hidden).toBe(true);
  });
});
