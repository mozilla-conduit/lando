/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

// The frontend is built into `static_src/dist` and served by Django as a plain
// static asset. There is no dev server; rebuild with `make build-js` after
// changing the frontend sources.
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: fileURLToPath(
      new URL("./src/lando/static_src/dist", import.meta.url),
    ),
    emptyOutDir: true,
    rollupOptions: {
      input: fileURLToPath(new URL("./frontend/src/main.ts", import.meta.url)),
    },
  },
  resolve: {
    alias: {
      "@static_src": fileURLToPath(
        new URL("./src/lando/static_src", import.meta.url),
      ),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.js"],
    include: [
      "frontend/**/*.test.ts",
      "src/lando/static_tests/**/*.test.{js,ts}",
    ],
  },
});
