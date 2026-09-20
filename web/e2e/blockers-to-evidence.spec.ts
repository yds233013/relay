/**
 * E2E-1 (docs/testing.md): an operator can go from "this customer is not ready" to the exact line
 * of the exported file that explains why, through the product's own path.
 *
 * The route changed when the overview stopped listing raw gate evidence and started leading with
 * the work queue, so this test now walks that path: overview → work queue → the drill-down → the
 * source row. What it proves is unchanged and slightly stronger: the failing gates are asserted
 * against the readiness page, which is authoritative, and the work queue's headline decision is
 * asserted to carry the money the reconciliation attributes to it.
 *
 * Expected values are the Brightwater Run #1 facts from the golden manifest (run1_gates) and the
 * DS-03/DS-04 specifications; this test belongs to evaluation, not to runtime code.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const RUN1_FAILING_GATES = ["G1", "G3", "G5", "G6", "G7", "G8", "G9", "G10", "G12"];

async function expectNoSeriousAccessibilityViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test("blockers lead to the evidence: R3 to the missing invoice's source row", async ({ page }) => {
  await page.goto("/select-user");
  await page.getByRole("button", { name: "Act as Maya Chen" }).click();
  await expect(page.getByTestId("current-user")).toContainText("maya.chen@relay.example");

  await page
    .getByRole("link", { name: /Brightwater Provisions/ })
    .first()
    .click();
  const banner = page.getByTestId("readiness-banner");
  await expect(banner).toContainText("NOT READY");
  await expect(banner).toContainText(`${RUN1_FAILING_GATES.length} of 12 readiness checks`);
  await expect(banner).toContainText("(current)");
  await expectNoSeriousAccessibilityViolations(page);

  // The work queue is where the blockers became decisions. The mapping defect leads it, carrying
  // the difference R3 attributes to that one legacy account (DS-03).
  await page.getByRole("link", { name: /Open the work queue/ }).click();
  const first = page.locator("[data-work-kind]").first();
  await expect(first).toContainText("1205");
  await expect(first).toContainText("38,400.00");
  await expectNoSeriousAccessibilityViolations(page);

  // Every gate the golden manifest expects to fail is failing, on the page that decides readiness.
  await page
    .getByRole("navigation", { name: "Migration" })
    .getByRole("link", { name: "Readiness" })
    .click();
  const failing = page.locator("[data-gate]").filter({ has: page.locator("[data-status='fail']") });
  await expect(failing).toHaveCount(RUN1_FAILING_GATES.length);
  for (const gate of RUN1_FAILING_GATES) {
    await expect(page.locator(`[data-gate='${gate}'] [data-status='fail']`)).toBeVisible();
  }

  // The subledger difference that is not the mapping's leads to the invoice that is missing.
  await page.goBack();
  await page
    .locator("[data-work-kind='reconciliation']")
    .filter({ hasText: "AR subledger vs GL control accounts" })
    .getByRole("link", { name: "Investigate difference" })
    .click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "R3 drill-down: party=C-0233",
  );
  const invoice = page.locator("[data-document='INV-10877']");
  await expect(invoice).toContainText("Left only");
  await expectNoSeriousAccessibilityViolations(page);

  await invoice.getByRole("link", { name: "jl:JE-AR-10877:1" }).click();
  await expect(page.getByRole("heading", { name: "Record inspector" })).toBeVisible();
  await expect(page.getByTestId("source-location")).toHaveText(/row \d+, line \d+/);
  const sourceRow = page.getByTestId("source-row");
  await expect(sourceRow.getByRole("row", { name: /^Num/ })).toContainText("JE-AR-10877");
  await expect(sourceRow.getByRole("row", { name: /^Doc No/ })).toContainText("INV-10877");
  await expectNoSeriousAccessibilityViolations(page);
});

test("reconciliation results page is accessible", async ({ page }) => {
  await page.goto("/select-user");
  await page.getByRole("button", { name: "Act as Priya Raman" }).click();
  await page
    .getByRole("link", { name: /Brightwater Provisions/ })
    .first()
    .click();
  await page
    .getByRole("navigation", { name: "Migration" })
    .getByRole("link", { name: "Reconciliation" })
    .click();
  await expect(page.getByRole("heading", { name: "Reconciliation" })).toBeVisible();
  await expectNoSeriousAccessibilityViolations(page);
});
