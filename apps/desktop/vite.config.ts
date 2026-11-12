import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Tauri expects a fixed dev port; see tauri.conf.json devUrl.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: { port: 1420, strictPort: true, host: "localhost", watch: { ignored: ["**/src-tauri/**"] } },
  build: { target: "es2022", sourcemap: false },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], css: false },
});
