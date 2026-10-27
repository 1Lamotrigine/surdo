/**
 * Тесты PWA-клиента (G1): адреса манифеста/SW, добавление `<link>`,
 * оценка поддержки и регистрация service worker.
 *
 * Чистые функции проверяются напрямую; браузерные вызовы подменяются
 * заглушками, потому что среда vitest — Node без DOM.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MANIFEST_PATH,
  SERVICE_WORKER_PATH,
  canRegisterServiceWorker,
  isLocalhost,
  manifestUrl,
  pwaSupport,
  registerServiceWorker,
  requiredLinks,
  serviceWorkerUrl,
  type ServiceWorkerContainerLike,
  type ServiceWorkerRegistrationLike,
} from "./pwa";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("URL манифеста и service worker'а", () => {
  it("собирает абсолютный URL из источника без хвостового слэша", () => {
    expect(manifestUrl("https://example.com")).toBe(`https://example.com${MANIFEST_PATH}`);
    expect(serviceWorkerUrl("https://example.com/")).toBe(
      `https://example.com${SERVICE_WORKER_PATH}`,
    );
  });

  it("сохраняет порт dev-сервера", () => {
    expect(manifestUrl("http://localhost:5173")).toBe(`http://localhost:5173${MANIFEST_PATH}`);
  });
});

describe("requiredLinks", () => {
  it("добавляет ссылку на манифест, если её нет", () => {
    expect(requiredLinks([], "/manifest.webmanifest")).toEqual([
      { rel: "manifest", href: "/manifest.webmanifest" },
    ]);
  });

  it("не дублирует уже подключённый манифест", () => {
    const existing = [{ rel: "manifest", href: "/manifest.webmanifest" }];
    expect(requiredLinks(existing, "/manifest.webmanifest")).toEqual([]);
  });

  it("игнорирует чужие ссылки rel", () => {
    const existing = [{ rel: "icon", href: "/favicon.ico" }];
    expect(requiredLinks(existing, "/manifest.webmanifest")).toHaveLength(1);
  });
});

describe("поддержка PWA", () => {
  it("считает service worker доступным, когда он есть в navigator", () => {
    const support = pwaSupport({ serviceWorker: {} }, true);
    expect(support.serviceWorker).toBe(true);
    expect(support.secureContext).toBe(true);
  });

  it("без navigator поддержки нет", () => {
    expect(pwaSupport(null, true).serviceWorker).toBe(false);
    expect(pwaSupport(undefined, false).serviceWorker).toBe(false);
  });

  it("регистрация требует secure context и API", () => {
    const withApi = pwaSupport({ serviceWorker: {} }, true);
    expect(canRegisterServiceWorker(withApi, { serviceWorker: {} })).toBe(true);
    expect(canRegisterServiceWorker({ ...withApi, secureContext: false }, { serviceWorker: {} })).toBe(
      false,
    );
    expect(canRegisterServiceWorker(withApi, {})).toBe(false);
  });
});

describe("isLocalhost", () => {
  it("распознаёт локальные хосты (HTTP допустим для SW)", () => {
    expect(isLocalhost("http://localhost:8000")).toBe(true);
    expect(isLocalhost("http://127.0.0.1")).toBe(true);
  });

  it("внешний домен по HTTP не локальный", () => {
    expect(isLocalhost("http://example.com")).toBe(false);
  });

  it("битый origin — не локальный", () => {
    expect(isLocalhost("not a url")).toBe(false);
  });
});

describe("registerServiceWorker", () => {
  const registration: ServiceWorkerRegistrationLike = { scope: "/" };

  it("регистрирует sw.js с областью видимости корня", async () => {
    const register = vi.fn().mockResolvedValue(registration);
    const container: ServiceWorkerContainerLike = { register };

    const result = await registerServiceWorker({
      container,
      origin: "https://example.com",
    });

    expect(result).toBe(registration);
    expect(register).toHaveBeenCalledWith("https://example.com/sw.js", { scope: "/" });
  });

  it("разрешает регистрацию на localhost по HTTP", async () => {
    const register = vi.fn().mockResolvedValue(registration);
    vi.stubGlobal("isSecureContext", false);

    const result = await registerServiceWorker({
      container: { register },
      origin: "http://localhost:8000",
    });

    expect(result).toBe(registration);
    expect(register).toHaveBeenCalled();
  });

  it("на внешнем HTTP-адресе не регистрирует", async () => {
    const register = vi.fn().mockResolvedValue(registration);
    vi.stubGlobal("isSecureContext", false);

    const result = await registerServiceWorker({
      container: { register },
      origin: "http://example.com",
    });

    expect(result).toBeNull();
    expect(register).not.toHaveBeenCalled();
  });

  it("ошибку регистрации не пробрасывает наружу", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const register = vi.fn().mockRejectedValue(new Error("boom"));

    const result = await registerServiceWorker({
      container: { register },
      origin: "https://example.com",
    });

    expect(result).toBeNull();
    expect(warn).toHaveBeenCalled();
  });

  it("без контейнера возвращает null", async () => {
    const result = await registerServiceWorker({ container: null, origin: "https://example.com" });
    expect(result).toBeNull();
  });
});
