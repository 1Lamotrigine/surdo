/*
 * Service worker PWA (этап G1, FR-23/FR-24).
 *
 * Задачи:
 *  - закэшировать «оболочку» (CSS и собранный JS), чтобы приложение открывалось
 *    быстрее и работало при слабой сети;
 *  - закэшировать клипы жестов (cache-first): при повторном заходе клип берётся
 *    из кэша, а не скачивается заново (FR-24);
 *  - сбросить устаревшие клипы при обновлении словаря или сборки клиента.
 *
 * Версия кэша вшита Django'м при отдаче файла: `CACHE_VERSION` меняется вместе
 * с версией словаря (`DictionaryVersion`) и хэшем сборки Vite. При смене версии
 * все прежние кэши (`CACHE_PREFIX*`) удаляются в `activate`.
 *
 * Файл — Django-шаблон (`templates/pwa/sw.js`): подстановки переменных шаблона
 * выполняет Django через `config.pwa.service_worker`. Никакой сборки Vite здесь
 * нет, поэтому в скрипте нет импортов и современного синтаксиса модулей — только
 * классический `self`-based service worker, понятный всем целевым браузерам.
 */

/* global self, caches, clients, fetch, Request, Response */

const CACHE_VERSION = "{{ cache_version|escapejs }}";
const CACHE_PREFIX = "gluho-nemye:";
const SHELL_CACHE = CACHE_PREFIX + "shell:" + CACHE_VERSION;
const RUNTIME_CACHE = CACHE_PREFIX + "runtime:" + CACHE_VERSION;
const CLIP_CACHE = CACHE_PREFIX + "clips:" + CACHE_VERSION;

// Оболочка: CSS и точка входа клиента (собрана Vite). Список готовит Django.
const SHELL_ASSETS = {{ shell_assets|safe }};

// Клипы неизменяемы: новая версия клипа — новый файл (`v<версия>` в имени).
// Поэтому кэш клипов можно держать «навсегда» до смены версии словаря.
const CLIP_PATH = /^\/media\/clips\/\d+\.json\.gz$/;
const STATIC_PATH = /^\/static\//;

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      // Отдельные ошибки не должны валить установку: пробуем по одному файлу.
      await Promise.all(
        SHELL_ASSETS.map((url) =>
          cache.add(new Request(url, { cache: "reload" })).catch(() => undefined),
        ),
      );
      // Не ждём закрытия вкладок: новая версия должна активироваться сразу.
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((name) => name.startsWith(CACHE_PREFIX) && !name.endsWith(CACHE_VERSION))
          .map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

/** Навигационные запросы: сеть, при офлайне — закэшированная оболочка. */
async function handleNavigation(request) {
  try {
    const response = await fetch(request);
    const cache = await caches.open(RUNTIME_CACHE);
    cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await caches.match(request);
    if (cached) {
      return cached;
    }
    const shell = await caches.open(SHELL_CACHE);
    const home = await shell.match("/");
    if (home) {
      return home;
    }
    return new Response(
      "<!doctype html><meta charset=utf-8><title>Нет сети</title>" +
        "<p>Нет сети. Проверьте подключение и обновите страницу.</p>",
      { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } },
    );
  }
}

/** Клипы и статика: cache-first, затем сеть с сохранением ответа. */
async function handleCacheFirst(request, cacheName, { revalidate = false } = {}) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached && !revalidate) {
    return cached;
  }
  try {
    const response = await fetch(request);
    // Складываем только успешные ответы (не 404 и не ошибки сервера).
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    if (cached) {
      return cached;
    }
    return new Response("", { status: 504 });
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(handleNavigation(request));
    return;
  }

  if (CLIP_PATH.test(url.pathname)) {
    // Клипы неизменяемы — берём из кэша прежде всего.
    event.respondWith(handleCacheFirst(request, CLIP_CACHE));
    return;
  }

  if (STATIC_PATH.test(url.pathname)) {
    // У статики имя содержит хэш сборки, поэтому кэш тоже безопасен.
    event.respondWith(handleCacheFirst(request, RUNTIME_CACHE));
  }
});

// Сообщение из страницы: попросить активацию новой версии или очистить кэш.
self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type === "skip-waiting") {
    self.skipWaiting();
  }
  if (data.type === "clear-caches") {
    event.waitUntil(
      caches.keys().then((names) =>
        Promise.all(
          names
            .filter((name) => name.startsWith(CACHE_PREFIX))
            .map((name) => caches.delete(name)),
        ),
      ),
    );
  }
});
