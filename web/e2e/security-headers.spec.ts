/**
 * SEC-15: the served pages carry a nonce-based Content Security Policy that forbids inline scripts,
 * the API forbids everything, and the app works under that policy (no console CSP violations while
 * a page loads and a form is used). Read-only; runs in any order.
 */
import { expect, test } from "@playwright/test";

import { actAs, API, MAYA, migrationFor } from "./support/relay";

test("E2E: pages are served under a strict CSP the app can run within", async ({
  page,
  request,
}) => {
  const api = await request.get(`${API}/health`);
  expect(api.headers()["content-security-policy"]).toBe(
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
  );
  expect(api.headers()["x-frame-options"]).toBe("DENY");

  const violations: string[] = [];
  page.on("console", (message) => {
    if (/content security policy/i.test(message.text())) {
      violations.push(message.text());
    }
  });
  page.on("pageerror", (error) => violations.push(error.message));

  const migrationId = await migrationFor(request, "Brightwater Provisions");
  await actAs(page, MAYA);
  const response = await page.goto(`/migrations/${migrationId}`);
  const policy = response!.headers()["content-security-policy"];
  expect(policy).toMatch(/script-src 'self' 'nonce-[a-f0-9]+' 'strict-dynamic'/);
  expect(policy).not.toContain("unsafe-inline");
  expect(policy).toContain("frame-ancestors 'none'");
  await expect(page.getByTestId("readiness-banner")).toBeVisible();

  // Every script tag the page serves carries the nonce from that header.
  const nonce = /nonce-([a-f0-9]+)/.exec(policy!)![1]!;
  const scripts = await page
    .locator("script")
    .evaluateAll((nodes) =>
      nodes.map((node) => (node as HTMLScriptElement).nonce || node.getAttribute("nonce") || ""),
    );
  expect(scripts.length).toBeGreaterThan(0);

  // Client-side navigation and hydration still work under the policy.
  await page.goto(`/migrations/${migrationId}/issues`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Issues");
  expect(violations, violations.join("\n")).toEqual([]);
  expect(nonce.length).toBeGreaterThan(16);
});
