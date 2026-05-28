import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.js"],
    include: ["src/lando/static_tests/**/*.test.js"],
  },
  resolve: {
    alias: {
      "@static_src": fileURLToPath(
        new URL("./src/lando/static_src", import.meta.url),
      ),
    },
  },
});
