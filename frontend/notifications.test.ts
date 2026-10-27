/**
 * Тесты уведомлений студента (C8).
 *
 * Проверяются правила FR-26 (какие события подсвечивают экран и вибрируют),
 * узоры вибрации и удержание экрана FR-25: запрос Wake Lock, повтор после
 * возврата вкладки, освобождение и терпимость к неподдерживаемому браузеру.
 */

import { describe, expect, it } from "vitest";

import {
  NOTIFICATION_VIBRATION,
  ScreenWakeLock,
  notificationKindFor,
  vibrate,
  type WakeLockLike,
} from "./notifications";

/** Документ-заглушка: хранит слушатели и умеет менять видимость. */
class FakeDocument {
  visibilityState: "visible" | "hidden" = "visible";
  private readonly listeners = new Set<() => void>();

  addEventListener(type: string, listener: () => void): void {
    if (type === "visibilitychange") this.listeners.add(listener);
  }

  removeEventListener(type: string, listener: () => void): void {
    if (type === "visibilitychange") this.listeners.delete(listener);
  }

  setVisibility(state: "visible" | "hidden"): void {
    this.visibilityState = state;
    for (const listener of this.listeners) listener();
  }

  get listenerCount(): number {
    return this.listeners.size;
  }
}

/** Блокировка экрана-заглушка: считает `release` и умеет «сниматься» сама. */
function fakeSentinel() {
  let releaseCount = 0;
  let onRelease: (() => void) | null = null;
  const sentinel = {
    release: async (): Promise<void> => {
      releaseCount += 1;
    },
    addEventListener: (_type: "release", listener: () => void): void => {
      onRelease = listener;
    },
  };
  return {
    sentinel,
    releases: () => releaseCount,
    fireRelease: () => onRelease?.(),
  };
}

function fakeWakeLock(sentinel: ReturnType<typeof fakeSentinel>["sentinel"]) {
  let requests = 0;
  const wakeLock: WakeLockLike = {
    request: async () => {
      requests += 1;
      return sentinel;
    },
  };
  return { wakeLock, requests: () => requests };
}

function visibleDocument(): Document {
  const doc = new FakeDocument();
  return doc as unknown as Document;
}

describe("notificationKindFor", () => {
  it("подсвечивает новую фразу у студента", () => {
    expect(notificationKindFor({ type: "utterance" }, true)).toBe("phrase");
  });

  it("подсвечивает ответ преподавателя в чате", () => {
    expect(notificationKindFor({ type: "chat_message", is_teacher: true }, true)).toBe("chat");
  });

  it("не уведомляет о сообщениях других студентов и служебных событиях", () => {
    expect(notificationKindFor({ type: "chat_message", is_teacher: false }, true)).toBeNull();
    expect(notificationKindFor({ type: "presence" }, true)).toBeNull();
    expect(notificationKindFor({ type: "pong" }, true)).toBeNull();
  });

  it("не уведомляет панель преподавателя", () => {
    expect(notificationKindFor({ type: "utterance" }, false)).toBeNull();
    expect(notificationKindFor({ type: "chat_message", is_teacher: true }, false)).toBeNull();
  });
});

describe("vibrate", () => {
  it("передаёт узор вибрации для фразы и чата", () => {
    const patterns: number[][] = [];
    const target = {
      vibrate: (pattern: number | number[]) => {
        patterns.push(Array.isArray(pattern) ? pattern : [pattern]);
        return true;
      },
    };

    expect(vibrate(target, "phrase")).toBe(true);
    expect(vibrate(target, "chat")).toBe(true);
    expect(patterns).toEqual([NOTIFICATION_VIBRATION.phrase, NOTIFICATION_VIBRATION.chat]);
    expect(NOTIFICATION_VIBRATION.phrase).not.toEqual(NOTIFICATION_VIBRATION.chat);
  });

  it("возвращает false без поддержки и при ошибке API", () => {
    expect(vibrate(null, "chat")).toBe(false);
    expect(vibrate({}, "chat")).toBe(false);
    expect(
      vibrate(
        {
          vibrate: () => {
            throw new Error("not allowed");
          },
        },
        "phrase",
      ),
    ).toBe(false);
    expect(vibrate({ vibrate: () => false }, "phrase")).toBe(false);
  });
});

describe("ScreenWakeLock", () => {
  it("сообщает об отсутствии поддержки и не падает", async () => {
    const lock = new ScreenWakeLock({ document: visibleDocument(), wakeLock: null });

    expect(lock.supported).toBe(false);
    expect(await lock.enable()).toBe(false);
    expect(lock.active).toBe(false);
  });

  it("запрашивает экран и держит его", async () => {
    const fake = fakeSentinel();
    const api = fakeWakeLock(fake.sentinel);
    const lock = new ScreenWakeLock({ document: visibleDocument(), wakeLock: api.wakeLock });

    expect(await lock.enable()).toBe(true);
    expect(api.requests()).toBe(1);
    expect(lock.active).toBe(true);
  });

  it("не запрашивает повторно, пока экран уже удерживается", async () => {
    const fake = fakeSentinel();
    const api = fakeWakeLock(fake.sentinel);
    const lock = new ScreenWakeLock({ document: visibleDocument(), wakeLock: api.wakeLock });

    await lock.enable();
    await lock.enable();

    expect(api.requests()).toBe(1);
    expect(lock.active).toBe(true);
  });

  it("повторно захватывает экран после возврата во вкладку", async () => {
    const fake = fakeSentinel();
    const api = fakeWakeLock(fake.sentinel);
    const document = new FakeDocument();
    const lock = new ScreenWakeLock({
      document: document as unknown as Document,
      wakeLock: api.wakeLock,
    });

    await lock.enable();
    // Браузер сам снимает блокировку при скрытии вкладки.
    fake.fireRelease();
    expect(lock.active).toBe(false);
    document.setVisibility("hidden");
    document.setVisibility("visible");
    // Ждём асинхронный запрос внутри обработчика visibilitychange.
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(api.requests()).toBe(2);
    expect(lock.active).toBe(true);
  });

  it("освобождает экран при disable и снимает слушатель", async () => {
    const fake = fakeSentinel();
    const api = fakeWakeLock(fake.sentinel);
    const document = new FakeDocument();
    const lock = new ScreenWakeLock({
      document: document as unknown as Document,
      wakeLock: api.wakeLock,
    });

    await lock.enable();
    await lock.disable();

    expect(lock.active).toBe(false);
    expect(fake.releases()).toBe(1);
    expect(document.listenerCount).toBe(0);
  });

  it("не запрашивает скрытый документ и ждёт возврата", async () => {
    const fake = fakeSentinel();
    const api = fakeWakeLock(fake.sentinel);
    const document = new FakeDocument();
    document.visibilityState = "hidden";
    const lock = new ScreenWakeLock({
      document: document as unknown as Document,
      wakeLock: api.wakeLock,
    });

    expect(await lock.enable()).toBe(false);
    expect(api.requests()).toBe(0);

    document.setVisibility("visible");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(api.requests()).toBe(1);
    expect(lock.active).toBe(true);
  });

  it("терпит отказ браузера в запросе", async () => {
    const wakeLock: WakeLockLike = {
      request: async () => {
        throw new Error("not allowed");
      },
    };
    const lock = new ScreenWakeLock({ document: visibleDocument(), wakeLock });

    expect(await lock.enable()).toBe(false);
    expect(lock.active).toBe(false);
  });
});
