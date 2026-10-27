import { copyFileSync, createReadStream, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

const rootDir = fileURLToPath(new URL(".", import.meta.url));
const MEDIAPIPE_WASM_DIR = resolve(rootDir, "node_modules/@mediapipe/tasks-vision/wasm");
const MEDIAPIPE_WASM_FILES = [
  "vision_wasm_internal.js",
  "vision_wasm_internal.wasm",
  "vision_wasm_nosimd_internal.js",
  "vision_wasm_nosimd_internal.wasm",
] as const;
const MEDIAPIPE_DEV_PREFIX = "/static/dist/mediapipe/";

/**
 * MediaPipe грузит WASM отдельными файлами, поэтому они должны лежать рядом с
 * клиентом. В dev-режиме отдаём их из `node_modules` middleware'ом Vite, при
 * сборке копируем в `static/dist/mediapipe` (Django/WhiteNoise раздаёт статику).
 */
function mediapipeWasm(): Plugin {
  return {
    name: "mediapipe-wasm",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const url = request.url ?? "";
        if (!url.startsWith(MEDIAPIPE_DEV_PREFIX)) {
          next();
          return;
        }
        const name = decodeURIComponent(url.slice(MEDIAPIPE_DEV_PREFIX.length).split("?")[0]);
        if (!(MEDIAPIPE_WASM_FILES as readonly string[]).includes(name)) {
          next();
          return;
        }
        response.setHeader(
          "Content-Type",
          name.endsWith(".wasm") ? "application/wasm" : "text/javascript",
        );
        // Модуль страницы Django в dev-режиме грузится с порта Vite.
        response.setHeader("Access-Control-Allow-Origin", "*");
        response.setHeader("Cache-Control", "no-cache");
        createReadStream(resolve(MEDIAPIPE_WASM_DIR, name))
          .on("error", next)
          .pipe(response);
      });
    },
    closeBundle() {
      const targetDir = resolve(rootDir, "static/dist/mediapipe");
      mkdirSync(targetDir, { recursive: true });
      for (const file of MEDIAPIPE_WASM_FILES) {
        copyFileSync(resolve(MEDIAPIPE_WASM_DIR, file), resolve(targetDir, file));
      }
    },
  };
}

// base и outDir согласованы с DJANGO_VITE["default"]["static_url_prefix"] = "dist":
// в dev Vite отдаёт /static/dist/frontend/main.ts, в build — /static/dist/assets/*.
export default defineConfig({
  base: "/static/dist/",
  plugins: [mediapipeWasm()],
  build: {
    outDir: "static/dist",
    emptyOutDir: true,
    manifest: "manifest.json",
    rollupOptions: {
      input: [
        "frontend/main.ts",
        "frontend/rooms.ts",
        "frontend/room-live.ts",
        "frontend/avatar-page.ts",
        "frontend/record-page.ts",
      ],
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
  },
  test: {
    // Тесты декодера — чистые функции над байтами (base64, gzip, Float16),
    // поэтому окружение Node: быстрее jsdom и без лишних зависимостей.
    environment: "node",
    include: ["frontend/**/*.test.ts"],
  },
});
