/**
 * Уведомления студента (C8): Wake Lock, подсветка экрана и вибрация.
 *
 * FR-25: экран телефона не гаснет, пока открыта комната. FR-26: при новой
 * фразе и при ответе преподавателя в чат экран подсвечивается, а на Android
 * (где есть `navigator.vibrate`) — короткая вибрация.
 *
 * Здесь живёт **чистая** часть: какое событие комнаты даёт какое уведомление и
 * какой узор вибрации ему соответствует. `ScreenWakeLock` и `ScreenNotifier` —
 * тонкие обёртки над браузерными API; их можно подменить в тестах.
 */

/** Вид уведомления: новая фраза или ответ преподавателя в чате. */
export type NotificationKind = "phrase" | "chat";

/** Событие комнаты, на которое смотрит правило уведомлений. */
export type RoomNotificationEvent = {
  /** Тип события WebSocket (`utterance`, `chat_message`, …). */
  type: string;
  /** Для `chat_message`: сообщение написал преподаватель. */
  is_teacher?: boolean;
};

/** Текст уведомления для экранного диктора и строки состояния. */
export const NOTIFICATION_LABELS: Record<NotificationKind, string> = {
  phrase: "Новая фраза",
  chat: "Ответ преподавателя в чате",
};

/** Узор вибрации (мс): фраза — двойной импульс, чат — один короткий. */
export const NOTIFICATION_VIBRATION: Record<NotificationKind, number[]> = {
  phrase: [80, 40, 80],
  chat: [60],
};

/** Сколько держится класс подсветки (чуть дольше CSS-анимации). */
export const NOTIFICATION_FLASH_MS = 900;

/** Какое уведомление показать на событие; `null` — не уведомлять. */
export function notificationKindFor(
  event: RoomNotificationEvent,
  isStudentView: boolean,
): NotificationKind | null {
  // Панель преподавателя не мигает и не вибрирует: уведомления для студента.
  if (!isStudentView) return null;
  if (event.type === "utterance") return "phrase";
  if (event.type === "chat_message" && event.is_teacher === true) return "chat";
  return null;
}

/** Минимальный объект с `vibrate` (в тестах — заглушка). */
export type VibrateTarget = {
  vibrate?: (pattern: number | number[]) => boolean;
};

/**
 * Запустить вибрацию, если браузер её поддерживает. Возвращает `true`, только
 * когда вибрация действительно запрошена; исключения API не ломают страницу.
 */
export function vibrate(
  target: VibrateTarget | null | undefined,
  kind: NotificationKind,
): boolean {
  if (!target || typeof target.vibrate !== "function") return false;
  try {
    return target.vibrate(NOTIFICATION_VIBRATION[kind]) === true;
  } catch {
    return false;
  }
}

/** Событие пробуждения экрана (подмножество Screen Wake Lock API). */
export type WakeLockSentinelLike = {
  release: () => Promise<void>;
  addEventListener?: (type: "release", listener: () => void) => void;
};

/** API Wake Lock (подмножество, нужное странице). */
export type WakeLockLike = {
  request: (type: "screen") => Promise<WakeLockSentinelLike>;
};

/**
 * Взять Wake Lock из браузера. В старых браузерах и в Node его нет — тогда
 * страница просто покажет, что удержание экрана недоступно.
 */
function browserWakeLock(): WakeLockLike | null {
  const navigatorLike = globalThis.navigator as (Navigator & { wakeLock?: WakeLockLike }) | undefined;
  return navigatorLike?.wakeLock ?? null;
}

export type ScreenWakeLockOptions = {
  /** Документ (в тестах — заглушка с `visibilityState` и событиями). */
  document?: Document;
  /** API Wake Lock; `null` явно отключает поддержку. */
  wakeLock?: WakeLockLike | null;
};

/**
 * Удержание экрана включённым (FR-25).
 *
 * Браузер сам снимает Wake Lock, когда вкладка скрыта, поэтому после возврата
 * на страницу запрос повторяется (`visibilitychange`). `enable` можно вызывать
 * повторно: лишних запросов и слушателей не будет.
 */
export class ScreenWakeLock {
  private readonly document: Document;
  private readonly wakeLock: WakeLockLike | null;
  private sentinel: WakeLockSentinelLike | null = null;
  private wanted = false;
  private asking = false;
  private listening = false;

  constructor(options: ScreenWakeLockOptions = {}) {
    this.document = options.document ?? globalThis.document;
    this.wakeLock = options.wakeLock !== undefined ? options.wakeLock : browserWakeLock();
  }

  /** Поддерживает ли браузер Screen Wake Lock. */
  get supported(): boolean {
    return this.wakeLock !== null;
  }

  /** Держится ли экран прямо сейчас. */
  get active(): boolean {
    return this.sentinel !== null;
  }

  /** Запросить удержание экрана. `false` — браузер не дал или скрыт документ. */
  async enable(): Promise<boolean> {
    this.wanted = true;
    if (!this.listening) {
      this.document.addEventListener("visibilitychange", this.handleVisibility);
      this.listening = true;
    }
    return this.acquire();
  }

  /** Отпустить экран (комната закрыта, страница уходит). */
  async disable(): Promise<void> {
    this.wanted = false;
    if (this.listening) {
      this.document.removeEventListener("visibilitychange", this.handleVisibility);
      this.listening = false;
    }
    const sentinel = this.sentinel;
    this.sentinel = null;
    if (sentinel) {
      try {
        await sentinel.release();
      } catch {
        // Браузер уже мог снять блокировку сам.
      }
    }
  }

  private handleVisibility = (): void => {
    if (this.wanted && this.document.visibilityState === "visible") {
      void this.acquire();
    }
  };

  private async acquire(): Promise<boolean> {
    if (!this.wakeLock || this.sentinel || this.asking) return this.sentinel !== null;
    if (this.document.visibilityState === "hidden") return false;

    this.asking = true;
    try {
      const sentinel = await this.wakeLock.request("screen");
      // Пока браузер отвечал, экран могли отпустить — тогда сразу освобождаем.
      if (!this.wanted) {
        await sentinel.release();
        return false;
      }
      this.sentinel = sentinel;
      sentinel.addEventListener?.("release", () => {
        if (this.sentinel === sentinel) this.sentinel = null;
      });
      return true;
    } catch {
      return false;
    } finally {
      this.asking = false;
    }
  }
}

/**
 * Подсветка экрана и вибрация (FR-26). Класс на `body` включает CSS-анимацию
 * (`body.notification-flash::after`), текст уходит в `aria-live`-строку.
 */
export class ScreenNotifier {
  private readonly body: HTMLElement | null;
  private readonly status: HTMLElement | null;
  private readonly vibrateTarget: VibrateTarget | null;
  private timer: number | null = null;

  constructor(root: HTMLElement, vibrateTarget: VibrateTarget | null = globalThis.navigator) {
    this.body = globalThis.document?.body ?? null;
    this.status = root.querySelector<HTMLElement>("[data-notification-status]");
    this.vibrateTarget = vibrateTarget;
  }

  /** Показать уведомление: подсветка, текст и (если есть) вибрация. */
  notify(kind: NotificationKind): void {
    if (this.status) this.status.textContent = NOTIFICATION_LABELS[kind];
    if (this.body) {
      // Перезапуск CSS-анимации на повторном событии.
      this.body.classList.remove("notification-flash");
      this.body.dataset.notification = kind;
      void this.body.offsetWidth;
      this.body.classList.add("notification-flash");
    }
    vibrate(this.vibrateTarget, kind);

    if (this.timer !== null) window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => this.clear(), NOTIFICATION_FLASH_MS);
  }

  /** Снять подсветку и текст (комната закрыта, страница уходит). */
  clear(): void {
    if (this.timer !== null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.body) {
      this.body.classList.remove("notification-flash");
      delete this.body.dataset.notification;
    }
    if (this.status) this.status.textContent = "";
  }

  dispose(): void {
    this.clear();
  }
}
