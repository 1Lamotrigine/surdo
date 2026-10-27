import { defineConfig } from "vitest/config";

// base и outDir согласованы с DJANGO_VITE["default"]["static_url_prefix"] = "dist":
// в dev Vite отдаёт /static/dist/frontend/main.ts, в build — /static/dist/assets/*.
export default defineConfig({
  base: "/static/dist/",
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
