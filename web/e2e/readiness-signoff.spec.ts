/**
 * E2E-5: fast-forward to just before sign-off → sign-off → READY → a policy change → the sign-off is
 * invalidated and readiness is no longer ready. Runs last: it changes the demo state the most.
 * The fast-forward command is supplied by `make test-e2e` (it runs inside the Compose stack).
 */
import { execSync } from "node:child_process";

import { expect, test } from "@playwright/test";

import {
  actAs,
  api,
  approve,
  DANIEL,
  expectAccessible,
  latestRun,
  MAYA,
  migrationFor,
  PRIYA,
  waitForRuns,
} from "./support/relay";

interface Readiness {
  overall: string;
  migration_status: string;
  gates: { gate_id: string; status: string }[];
  signoffs: { status: string }[];
}

test("E2E-5: sign-off makes the migration ready and a policy change invalidates it", async ({
  page,
  request,
}) => {
  test.setTimeout(600_000);
  const command = process.env.E2E_FAST_FORWARD;
  test.skip(!command, "E2E_FAST_FORWARD is set by `make test-e2e`");
  execSync(command!, { stdio: "inherit", timeout: 540_000 });

  const migrationId = await migrationFor(request, "Brightwater Provisions");
  const readiness = () => api<Readiness>(request, `/api/v1/migrations/${migrationId}/readiness`);
  await expect
    .poll(
      async () =>
        (await readiness()).gates.filter((g) => g.status === "fail").map((g) => g.gate_id),
      {
        timeout: 60_000,
        intervals: [1_000],
      },
    )
    .toEqual(["G12"]);

  await actAs(page, MAYA);
  await page.goto(`/migrations/${migrationId}/readiness`);
  await expect(page.getByTestId("readiness-overall")).toContainText("NOT READY");
  await expectAccessible(page);
  await page.getByLabel("Sign-off statement").fill("All gates pass; dispositions are documented.");
  await page.getByRole("button", { name: "Request sign-off" }).click();
  await page.waitForURL(/\/change-requests\/[0-9a-f-]+/);
  const signoffUrl = page.url();

  await actAs(page, DANIEL);
  await approve(page, signoffUrl, /More approvals are required/);
  await actAs(page, PRIYA);
  await approve(page, signoffUrl, /Approved and applied/);

  await expect
    .poll(async () => (await readiness()).overall, { timeout: 60_000, intervals: [1_000] })
    .toBe("ready");
  await page.goto(`/migrations/${migrationId}/readiness`);
  await expect(page.getByTestId("readiness-overall")).toContainText("READY");
  await expect(page.getByTestId("migration-status")).toHaveText("Signed off");
  const before = await latestRun(request, migrationId);

  await actAs(page, MAYA);
  await page.goto(`/migrations/${migrationId}/settings`);
  await page.getByLabel("Setting").selectOption("max_unresolved_exposure");
  await page.getByLabel("New value").fill("500.00");
  await page.getByLabel("Justification").fill("The controller lowered the exposure threshold.");
  await expectAccessible(page);
  await page.getByRole("button", { name: "Propose policy change" }).click();
  await page.waitForURL(/\/change-requests\/[0-9a-f-]+/);
  const policyUrl = page.url();
  await actAs(page, DANIEL);
  await approve(page, policyUrl, /More approvals are required/);
  await actAs(page, PRIYA);
  await approve(page, policyUrl, /Approved and applied/);
  await waitForRuns(request, migrationId, before.sequence);

  await expect
    .poll(async () => (await readiness()).signoffs.map((s) => s.status), {
      timeout: 60_000,
      intervals: [1_000],
    })
    .toEqual(["invalidated"]);
  const after = await readiness();
  expect(after.overall).toBe("not_ready");
  expect(after.migration_status).toBe("in_progress");
  await page.goto(`/migrations/${migrationId}/readiness`);
  await expect(page.getByTestId("readiness-overall")).toContainText("NOT READY");
  await expect(page.getByTestId("signoffs")).toContainText("invalidated");
});
