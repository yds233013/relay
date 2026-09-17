/**
 * E2E-8: a lead creates a migration from nothing; a specialist uploads a CSV and proposes its column
 * mapping from the suggestion; the lead approves; the run reports the duplicate customer code.
 */
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { actAs, api, DANIEL, expectAccessible, MAYA, waitForRuns } from "./support/relay";

test("E2E-8: new migration from a CSV to its first issues", async ({ page, request }) => {
  // Letters only: issue key prefixes are 2-6 capital letters.
  const suffix = Array.from(Date.now().toString(26).slice(-4), (c) =>
    String.fromCharCode(65 + Number.parseInt(c, 26)),
  ).join("");
  const csv = path.join(mkdtempSync(path.join(tmpdir(), "relay-e2e-")), "customers.csv");
  writeFileSync(
    csv,
    "Customer Code,Customer Name,City\r\nK-1,Northwind Cafe,Boise\r\nK-2,Harbor Bakery,Tacoma\r\nK-2,Harbor Bakery LLC,Tacoma\r\n",
  );

  await actAs(page, DANIEL);
  await page.goto("/migrations");
  await page.getByRole("link", { name: "New migration" }).click();
  await page.getByLabel("Company name", { exact: true }).fill(`Cascade Coffee Roasters ${suffix}`);
  await page.getByLabel("Migration name").fill("Spreadsheets to new ERP");
  await page.getByLabel(/Issue key prefix/).fill(`C${suffix}`);
  await page.getByLabel("Opening balance date").fill("2025-12-31");
  await page.getByLabel("History start date").fill("2026-01-01");
  await page.getByLabel("Cutover date").fill("2026-03-31");
  await page.getByLabel("Go-live date").fill("2026-04-01");
  await expectAccessible(page);
  await page.getByRole("button", { name: "Create migration" }).click();

  await expect(page.getByRole("heading", { name: "Setup" })).toBeVisible();
  const migrationId = page.url().split("/migrations/")[1]!.split("/")[0]!;
  await page.getByLabel("Name").fill("Office spreadsheets");
  await page.getByLabel("Kind").selectOption("spreadsheet");
  await page.getByRole("button", { name: "Add source system" }).click();
  await expect(page.getByTestId("source-systems")).toContainText("Office spreadsheets");
  await page.getByLabel("Dataset type").selectOption("customers");
  await page
    .locator("form")
    .filter({ hasText: "Add dataset" })
    .getByLabel("Name")
    .fill("customers.csv");
  await page.getByRole("button", { name: "Add dataset" }).click();
  await expect(page.getByTestId("setup-datasets")).toContainText("customers.csv");
  await expectAccessible(page);

  await actAs(page, MAYA);
  await page.goto(`/migrations/${migrationId}/setup`);
  await page.getByTestId("setup-datasets").getByRole("link", { name: "customers.csv" }).click();
  await page.getByLabel("CSV file").setInputFiles(csv);
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByRole("status")).toContainText("as import #1");
  await expect
    .poll(
      async () => {
        await page.reload();
        return page.locator("[data-sequence='1'] [data-status]").getAttribute("data-status");
      },
      { timeout: 30_000, intervals: [1_000] },
    )
    .toBe("parsed");

  await page.getByRole("link", { name: "Review or change the column mapping" }).click();
  await page.getByRole("link", { name: "Start from the suggestion" }).click();
  await page.getByRole("button", { name: "Preview first 50 rows" }).click();
  await expect(page.getByTestId("preview")).toContainText("Harbor Bakery LLC");
  await expect(page.getByText("Missing required fields: none.")).toBeVisible();
  await page.getByLabel("Justification").fill("Suggestion checked against the preview.");
  await page.getByRole("button", { name: "Propose the previewed mapping" }).click();
  await page.waitForURL(/\/change-requests\/[0-9a-f-]+/);
  const changeUrl = page.url();

  await actAs(page, DANIEL);
  await page.goto(changeUrl);
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("status")).toContainText("Approved and applied");
  await waitForRuns(request, migrationId, 0);

  await page.goto(`/migrations/${migrationId}/issues`);
  await expect(page.getByRole("table")).toContainText("NORM.DUPLICATE_NATURAL_KEY");
  const found = await api<{ items: { rule_or_recon_id: string }[] }>(
    request,
    `/api/v1/migrations/${migrationId}/issues`,
  );
  expect(found.items.map((i) => i.rule_or_recon_id)).toEqual(["NORM.DUPLICATE_NATURAL_KEY"]);
});
