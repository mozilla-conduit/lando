/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

// The frontend is built into `static_dist` and served by Django as a plain
// static asset (see `stack.html`). There is no dev server; rebuild with
// `make build-js` after changing the frontend sources.
export default defineConfig({
    plugins: [vue()],
    build: {
        outDir: fileURLToPath(new URL("./src/lando/static_dist", import.meta.url)),
        emptyOutDir: true,
        rollupOptions: {
            input: fileURLToPath(new URL("./frontend/src/main.ts", import.meta.url)),
            output: {
                // Stable, unhashed names so the Django template can reference them
                // directly, consistent with the other vendored static assets.
                entryFileNames: "uplift.js",
                chunkFileNames: "uplift-[name].js",
                assetFileNames: "uplift.[ext]",
            },
        },
    },
    resolve: {
        // `@` is the frontend source root, so modules can be imported as
        // `@/components/...` instead of via relative paths. `@static_src` points at
        // the legacy static assets directory, letting tests import the
        // hand-written JS that predates this Vite build.
        alias: {
            "@": fileURLToPath(new URL("./frontend/src", import.meta.url)),
            "@static_src": fileURLToPath(
                new URL("./src/lando/static_src", import.meta.url),
            ),
        },
    },
    test: {
        globals: true,
        environment: "jsdom",
        setupFiles: ["./vitest.setup.js"],
        include: ["frontend/**/*.test.ts", "src/lando/static_tests/**/*.test.{js,ts}"],
    },
});
