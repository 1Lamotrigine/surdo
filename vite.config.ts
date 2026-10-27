import { defineConfig } from "vite";

// base и outDir согласованы с DJANGO_VITE["default"]["static_url_prefix"] = "dist":
// в dev Vite отдаёт /static/dist/frontend/main.ts, в build — /static/dist/assets/*.
export default defineConfig({
  base: "/static/dist/",
  build: {
    outDir: "static/dist",
    emptyOutDir: true,
    manifest: "manifest.json",
    rollupOptions: {
      input: ["frontend/main.ts", "frontend/rooms.ts", "frontend/room-socket.ts"],
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
  },
});
