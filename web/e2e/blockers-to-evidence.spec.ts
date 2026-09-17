/**
 * E2E-1 (docs/testing.md): the Overview shows NOT READY with the expected failing gates, and the R3
 * blocker drills down to the missing invoice and the exact source row that posted it.
 *
 * Expected values are the Brightwater Run #1 facts from the golden manifest (run1_gates) and the
 * DS-04 specification; this test belongs to evaluation, not to runtime code.
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
  await expect(banner).toContainText(`${RUN1_FAILING_GATES.length} of 12 gates failing`);
  await expect(banner).toContainText("(current)");
  const gateChips = page.getByTestId("blockers").locator("li > p:first-child [data-status='fail']");
  await expect(gateChips).toHaveText(RUN1_FAILING_GATES.map((gate) => new RegExp(`${gate}$`)));
  await expectNoSeriousAccessibilityViolations(page);

  await page.getByRole("link", { name: "R3:party=C-0233" }).click();
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
