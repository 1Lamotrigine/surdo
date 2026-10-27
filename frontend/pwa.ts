/**
 * PWA-клиент (этап G1, FR-23/FR-24).
 *
 * Здесь живёт **чистая** логика манифеста и service worker'а плюс тонкая
 * обёртка регистрации. Чистые функции можно проверить в vitest (окружение
 * Node), браузерные вызовы подменяются в тестах.
 *
 * Регистрация service worker'а идёт только на защищённых источниках
 * (HTTPS или `localhost`) — браузер больше нигде его не даёт. Манифест и
 * иконки подставляет сервер (Django, `config.pwa`), поэтому здесь нет путей к
 * конкретным файлам сборки.
 */

/** Путь манифеста и service worker'а — оба отдаются с корня сайта. */
export const MANIFEST_PATH = "/manifest.webmanifest";
export const SERVICE_WORKER_PATH = "/sw.js";

/** Событие сервера/страницы: доступен ли PWA-контур. */
export type PwaSupport = {
  serviceWorker: boolean;
  secureContext: boolean;
};

/** Считываемые поля манифеста, которые нужны странице. */
export type ManifestLink = {
  href: string;
  rel: string;
};

/** Абсолютный URL манифеста по текущему источнику (в тестах — заглушка). */
export function manifestUrl(origin: string): string {
  return joinOrigin(origin, MANIFEST_PATH);
}

/** Абсолютный URL service worker'а по текущему источнику. */
export function serviceWorkerUrl(origin: string): string {
  return joinOrigin(origin, SERVICE_WORKER_PATH);
}

function joinOrigin(origin: string, path: string): string {
  const trimmed = origin.replace(/\/+$/, "");
  return `${trimmed}${path}`;
}

/**
 * Набор ссылок `<link rel>` для манифеста и иконок.
 *
 * Возвращаются только те `<link>`, которых не хватает в документе: повторная
 * вставка не нужна, а часть браузеров ругается на дублирующий `rel="manifest"`.
 */
export function requiredLinks(
  existing: readonly ManifestLink[],
  manifestHref: string,
): ManifestLink[] {
  const hasManifest = existing.some(
    (link) => link.rel === "manifest" && link.href === manifestHref,
  );
  return hasManifest ? [] : [{ rel: "manifest", href: manifestHref }];
}

/** Оценка поддержки PWA по объекту `navigator` (в тестах — заглушка). */
export function pwaSupport(
  navigatorLike: {
    serviceWorker?: unknown;
    onLine?: boolean;
  } | null | undefined,
  isSecureContext: boolean,
): PwaSupport {
  return {
    serviceWorker: Boolean(navigatorLike && navigatorLike.serviceWorker),
    secureContext: isSecureContext,
  };
}

/** Можно ли регистрировать service worker в этом окружении. */
export function canRegisterServiceWorker(
  support: PwaSupport,
  navigatorLike: { serviceWorker?: unknown } | null | undefined,
): boolean {
  return support.secureContext && support.serviceWorker && Boolean(navigatorLike?.serviceWorker);
}

export type ServiceWorkerContainerLike = {
  register: (url: string, options?: { scope?: string }) => Promise<ServiceWorkerRegistrationLike>;
  ready?: Promise<ServiceWorkerRegistrationLike>;
  addEventListener?: (type: "controllerchange", listener: () => void) => void;
};

export type ServiceWorkerRegistrationLike = {
  scope?: string;
  update?: () => Promise<void>;
  installing?: { state?: string } | null;
  waiting?: { postMessage?: (message: unknown) => void } | null;
  addEventListener?: (type: string, listener: () => void) => void;
};

export type RegisterOptions = {
  /** Контейнер service worker'а (в тестах — заглушка). */
  container?: ServiceWorkerContainerLike | null;
  /** База для абсолютного URL; в тестах можно передать свой origin. */
  origin?: string;
  /** Вызывается, когда активировался новый контроллер (например, после обновления). */
  onUpdate?: (registration: ServiceWorkerRegistrationLike) => void;
};

/**
 * Зарегистрировать service worker. Возвращает регистрацию или `null`, если
 * окружение не подходит (HTTP вне localhost, отсутствие API, ошибка регистрации).
 *
 * Ошибка регистрации не должна ломать страницу: PWA — дополнительная
 * возможность, а не обязательное условие работы (FR-23).
 */
export async function registerServiceWorker(
  options: RegisterOptions = {},
): Promise<ServiceWorkerRegistrationLike | null> {
  const container =
    options.container ??
    (globalThis.navigator as Navigator & { serviceWorker?: ServiceWorkerContainerLike })
      ?.serviceWorker ??
    null;
  const origin = options.origin ?? globalThis.location?.origin ?? "";
  const secure = typeof globalThis.isSecureContext === "boolean" ? globalThis.isSecureContext : false;

  if (!container || !container.register) return null;
  // Браузер отдаёт service worker только на HTTPS или localhost. Проверяем по
  // схеме источника и по флагу secure context (в некоторых браузерах флаг
  // выставлен и для localhost, поэтому учитываем оба признака).
  if (!secure && !isHttps(origin) && !isLocalhost(origin)) return null;

  try {
    const registration = await container.register(serviceWorkerUrl(origin), { scope: "/" });
    options.onUpdate?.(registration);
    return registration;
  } catch (error) {
    console.warn("[pwa] не удалось зарегистрировать service worker", error);
    return null;
  }
}

/** Проверить, что источник использует HTTPS. */
export function isHttps(origin: string): boolean {
  try {
    return new URL(origin).protocol === "https:";
  } catch {
    return false;
  }
}

/** Локальная разработка идёт по HTTP, но service worker это допускает. */
export function isLocalhost(origin: string): boolean {
  try {
    const host = new URL(origin).hostname;
    return host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "::1";
  } catch {
    return false;
  }
}

/**
 * Подключить service worker на странице: добавить `<link rel="manifest">`,
 * если сервер его не отдал шаблоном, и зарегистрировать SW.
 *
 * Регистрация откладывается до `load`: она не должна конкурировать за сеть с
 * первой отрисовкой и загрузкой клипов.
 */
export function setupPwa(doc: Document = globalThis.document): void {
  if (!doc) return;

  const manifestHref = manifestUrl(globalThis.location?.origin ?? "");
  const links = Array.from(doc.querySelectorAll<HTMLLinkElement>("link[rel]")).map((link) => ({
    rel: link.rel,
    href: link.href,
  }));
  for (const link of requiredLinks(links, manifestHref)) {
    const element = doc.createElement("link");
    element.rel = link.rel;
    element.href = link.href;
    doc.head.appendChild(element);
  }

  if (doc.readyState === "complete") {
    void registerServiceWorker();
  } else {
    globalThis.addEventListener("load", () => void registerServiceWorker(), { once: true });
  }
}
