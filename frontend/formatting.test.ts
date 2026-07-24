import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { describe, test, expect } from "vitest";

const require = createRequire(import.meta.url);

// Resolve the Prettier CLI from the installed package. Vitest runs with the
// repository root as its working directory, so checking `.` there covers the
// whole repo just like `prettier --check .` would on the command line.
const PRETTIER_BIN = require.resolve("prettier/bin/prettier.cjs");
const REPO_ROOT = process.cwd();

describe("code style", () => {
    test("all files adhere to the Prettier style", () => {
        try {
            execFileSync(process.execPath, [PRETTIER_BIN, "--check", "."], {
                cwd: REPO_ROOT,
                encoding: "utf8",
                stdio: ["ignore", "pipe", "pipe"],
            });
        } catch (error) {
            // `prettier --check` exits non-zero and lists the offending files
            // when any file is mis-formatted.
            const output = `${error.stdout ?? ""}${error.stderr ?? ""}`;
            expect.fail(
                `The CSS/JS code does not adhere to the project style:\n${output}`,
            );
        }
    });
});
