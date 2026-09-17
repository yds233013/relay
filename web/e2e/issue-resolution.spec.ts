/**
 * E2E-3 (re-import), E2E-4 (merge reveals the duplicate payment, disposition lowers exposure), and
 * the DS-06 and DS-10 decisions, through the UI. Needs a freshly seeded stack (`make demo-reset`)
 * and runs after governed-changes.spec.ts. The API is used only to look up ids and wait for runs.
 */
import path from "node:path";

import { expect, test } from "@playwright/test";

import {
  actAs,
  approve,
  DANIEL,
  expectAccessible,
  exposure,
  issues,
  latestRun,
  MAYA,
  migrationFor,
  PRIYA,
  api,
  waitForRuns,
} from "./support/relay";

const FIXTURES = path.resolve(__dirname, "../../fixtures/demo");

test.describe.configure({ mode: "serial" });

test("E2E-3: an identical upload changes nothing; corrected exports replace the active imports", async ({
  page,
  request,
}) => {
  const migrationId = await migrationFor(request, "Brightwater Provisions");
  const datasets = await api<{ id: string; name: string }[]>(
    request,
    `/api/v1/migrations/${migrationId}/datasets`,
  );
  const before = await latestRun(request, migrationId);
  await actAs(page, MAYA);

  const invoices = datasets.find((d) => d.name === "ledgerpro_invoices.csv")!;
  await page.goto(`/migrations/${migrationId}/data/datasets/${invoices.id}`);
  await page
    .getByLabel("CSV file")
    .setInputFiles(path.join(FIXTURES, "brightwater/ledgerpro/ledgerpro_invoices.csv"));
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByRole("status")).toContainText("already imported as import #1");
  await expectAccessible(page);

  for (const name of [
    "ledgerpro_invoices.csv",
    "ledgerpro_customers.csv",
    "ledgerpro_chart_of_accounts.csv",
  ]) {
    const dataset = datasets.find((d) => d.name === name)!;
    await page.goto(`/migrations/${migrationId}/data/datasets/${dataset.id}`);
    await page
      .getByLabel("CSV file")
      .setInputFiles(path.join(FIXTURES, "brightwater_reexport/ledgerpro", name));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByRole("status")).toContainText("as import #2");
  }
  await expect
    .poll(
      async () => {
        await page.reload();
        return page.locator("[data-sequence='2'] [data-status]").getAttribute("data-status");
      },
      { timeout: 30_000, intervals: [1_000] },
    )
    .toBe("parsed");
  await expect(page.locator("[data-sequence='1'] [data-status]")).toHaveAttribute(
    "data-status",
    "superseded",
  );
  await page.getByRole("button", { name: "Run the pipeline on the current inputs" }).click();
  await expect(page.getByRole("status")).toContainText("Run #");
  await waitForRuns(request, migrationId, before.sequence);

  await page.goto(`/migrations/${migrationId}`);
  await expect(page.getByTestId("blockers").getByRole("link", { name: /^R3b:/ })).toHaveCount(0);
  const orphan = await issues(request, migrationId, "AR.PAYMENT_PARTY_EXISTS");
  expect(orphan.map((i) => i.status)).toEqual(["resolved"]);
});

test("E2E-4: merging duplicate vendors reveals the double payment; a disposition lowers exposure", async ({
  page,
  request,
}) => {
  const migrationId = await migrationFor(request, "Brightwater Provisions");
  let run = await latestRun(request, migrationId);

  await actAs(page, MAYA);
  await page.goto(`/migrations/${migrationId}/entities`);
  await page.getByRole("link", { name: "Vendor V-1042 and V-1187" }).click();
  await expect(page.getByTestId("parties")).toContainText("Pacific Coast Packaging, L.L.C.");
  await expectAccessible(page);
  await page.getByLabel("the same entity").check();
  await page.getByLabel("Surviving record (same entity only)").selectOption("V-1042");
  await page
    .getByLabel("Justification and evidence")
    .fill("Same tax id, address and vendor invoice reference.");
  await page.getByRole("button", { name: "Propose decision" }).click();
  await page.waitForURL(/\/change-requests\/[0-9a-f-]+/);
  const mergeUrl = page.url();
  await expect(page.getByTestId("requirements")).toContainText("Implementation lead");

  await actAs(page, DANIEL);
  await approve(page, mergeUrl, /Approved and applied/);
  await waitForRuns(request, migrationId, run.sequence);
  run = await latestRun(request, migrationId);

  const [duplicateBill] = await issues(request, migrationId, "AP.DUPLICATE_BILL");
  expect(duplicateBill?.status).toBe("open");
  const exposureBefore = await exposure(request, migrationId);

  await actAs(page, MAYA);
  await page.goto(`/migrations/${migrationId}/issues/${duplicateBill!.id}`);
  await page.getByRole("link", { name: "Propose a disposition" }).click();
  await expect(page.getByLabel(`Include ${duplicateBill!.key}`)).toBeChecked();
  await page.getByLabel("Kind").selectOption("carry_forward_adjustment");
  await page.getByLabel(/^Amount/).fill("14862.50");
  await page.getByLabel("Follow-up", { exact: true }).fill("Request a refund or credit");
  await page.getByLabel("Follow-up owner").selectOption({ label: PRIYA.name });
  await page
    .getByLabel("Justification")
    .fill("Real overpayment in the legacy books; record the vendor receivable in the new ERP.");
  await expectAccessible(page);
  await page.getByRole("button", { name: "Propose disposition" }).click();
  await page.waitForURL(/\/change-requests\/[0-9a-f-]+/);
  const dispositionUrl = page.url();
  await expect(page.getByTestId("requirements")).toContainText("Customer controller");

  await actAs(page, DANIEL);
  await page.goto(dispositionUrl);
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await actAs(page, PRIYA);
  await approve(page, dispositionUrl, /Approved and applied/);
  await waitForRuns(request, migrationId, run.sequence);

  const [after] = await issues(request, migrationId, "AP.DUPLICATE_BILL");
  expect(after?.status).toBe("dispositioned");
  expect(Number.parseFloat(await exposure(request, migrationId))).toBeLessThan(
    Number.parseFloat(exposureBefore),
  );
});

test("DS-06 and DS-10: keep a distinct store apart and disposition six bank fees at once", async ({
  page,
  request,
}) => {
  const migrationId = await migrationFor(request, "Brightwater Provisions");
  const run = await latestRun(request, migrationId);

  await actAs(page, MAYA);
  await page.goto(`/migrations/${migrationId}/entities`);
  await page.getByRole("link", { name: "Customer C-0107 and C-0198" }).click();
  await page.getByLabel("distinct entities").check();
  await page.getByLabel("Justification and evidence").fill("Separate store with its own billing.");
  await page.getByRole("button", { name: "Propose decision" }).click();
  await page.waitForURL(/\/change-requests\/[0-9a-f-]+/);
  const distinctUrl = page.url();

  const bankFees = await issues(request, migrationId, "BANK.UNRECORDED_ACTIVITY");
  expect(bankFees).toHaveLength(6);
  await page.goto(`/migrations/${migrationId}/dispositions/new?issue=${bankFees[0]!.id}`);
  for (const fee of bankFees) {
    await page.getByLabel(`Include ${fee.key}`).check();
  }
  await page.getByLabel("Kind").selectOption("carry_forward_adjustment");
  await page.getByLabel(/^Amount/).fill("270.00");
  await page.getByLabel("Justification").fill("Book six months of bank fees in the opening entry.");
  await page.getByRole("button", { name: "Propose disposition" }).click();
  await page.waitForURL(/\/change-requests\/[0-9a-f-]+/);
  const feesUrl = page.url();

  await actAs(page, DANIEL);
  await approve(page, distinctUrl, /Approved and applied/);
  await actAs(page, PRIYA);
  await approve(page, feesUrl, /Approved and applied/);
  await waitForRuns(request, migrationId, run.sequence);

  const fees = await issues(request, migrationId, "BANK.UNRECORDED_ACTIVITY");
  expect(fees.map((i) => i.status)).toEqual(Array(6).fill("dispositioned"));
  await page.goto(`/migrations/${migrationId}/overrides`);
  await expect(page.getByTestId("dispositions").locator("[data-status='active']")).toHaveCount(7);
  await expect(page.getByTestId("entity-decisions").locator("[data-status='active']")).toHaveCount(
    2,
  );
});
