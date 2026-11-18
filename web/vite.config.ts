/// <reference types="vitest/config" />
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/** The engine's report stylesheet: the rendered report's one `<style>` element holds exactly
 * this file's text (engine/corelata/render/html.py). */
const REPORT_CSS = fileURLToPath(
  new URL("../engine/corelata/render/templates/report.css", import.meta.url),
);
const REPORT_STYLE = "virtual:report-style";

/** `virtual:report-style` exports `REPORT_STYLE_HASH`, the CSP source (`sha256-<base64>`) of the
 * report stylesheet, computed from the file at build time: the review frame's policy allows that
 * one stylesheet and no other inline style (CRL-23, R-M14-2). */
function reportStyleHash(): Plugin {
  const resolved = `\0${REPORT_STYLE}`;
  return {
    name: "corelata-report-style-hash",
    resolveId: (id) => (id === REPORT_STYLE ? resolved : undefined),
    load(id) {
      if (id !== resolved) return undefined;
      this.addWatchFile(REPORT_CSS);
      const digest = createHash("sha256").update(readFileSync(REPORT_CSS)).digest("base64");
      return `export const REPORT_STYLE_HASH = ${JSON.stringify(`sha256-${digest}`)};\n`;
    },
  };
}

export default defineConfig({
  plugins: [react(), reportStyleHash()],
  server: {
    // `pnpm dev` talks to a local API (`make dev-stack`); server-sent events pass through as is.
    proxy: { "/api": { target: "http://127.0.0.1:8080", changeOrigin: false } },
  },
  test: {
    globals: true,
    testTimeout: 15_000,
    environment: "./src/test/jsdom-env.ts",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/api/schema.d.ts", // generated from schema/openapi.json; types only
        "src/main.tsx", // mounts the app into the page: exercised by the Playwright journeys
        "src/test/**", // the test harness itself
        "src/**/*.test.{ts,tsx}", // tests are not product code
      ],
      reporter: ["text", "lcov"],
      thresholds: { lines: 95, branches: 95, functions: 95, statements: 95 },
    },
  },
});
