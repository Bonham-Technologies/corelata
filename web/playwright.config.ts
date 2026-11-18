import { defineConfig, devices } from "@playwright/test";

const PORT = 8765;
const CSP_PORT = 8766; // the same stack behind the operator guide's sample policy (CRL-23)

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // one stack, one database
  timeout: 120_000,
  expect: { timeout: 30_000 }, // a run takes several seconds against the fake model
  reporter: process.env["CI"] ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] }, testIgnore: /csp\.spec\.ts/ },
    {
      name: "csp-proxy",
      use: { ...devices["Desktop Chrome"], baseURL: `http://127.0.0.1:${CSP_PORT}` },
      testMatch: /csp\.spec\.ts/,
    },
  ],
  webServer: {
    command:
      `cd ../api && uv run python devstack.py --host 127.0.0.1 --port ${PORT} ` +
      `--web-dir ../web/dist --csp-proxy-port ${CSP_PORT}`,
    url: `http://127.0.0.1:${CSP_PORT}/api/health`, // the proxy answers last
    timeout: 120_000,
    reuseExistingServer: false,
    stdout: "pipe",
    gracefulShutdown: { signal: "SIGTERM", timeout: 15_000 },
  },
});
