import { defineConfig } from "@playwright/test";

/**
 * End-to-end tests run against a running, seeded stack (`make up`, then `make demo-seed`).
 * They use the locally installed Chrome, so no browser download is needed.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000",
    channel: "chrome",
    headless: true,
    trace: "retain-on-failure",
  },
});
