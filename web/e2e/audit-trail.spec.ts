/**
 * E2E-6: the audit log carries before/after and the approvers for a governed change, and the hash
 * chain verifies. It anchors on the most recent applied account mapping change — the one E2E-2
 * makes when the whole suite runs, the seed's own otherwise — so it does not depend on test order.
 * Read-only.
 */
import { expect, test } from "@playwright/test";

import { actAs, api, expectAccessible, migrationFor, SAM } from "./support/relay";

interface Change {
  id: string;
  key: string;
  kind: string;
  status: string;
  requested_by_name: string;
}

test("E2E-6: the audit log shows the change, its approvers and a verified chain", async ({
  page,
  request,
}) => {
  const migrationId = await migrationFor(request, "Brightwater Provisions");
  const applied = await api<Change[]>(
    request,
    `/api/v1/migrations/${migrationId}/change-requests?kind=account_mapping_set&status=applied&limit=50`,
  );
  const change = applied.at(-1);
  expect(change, "an applied account mapping change exists").toBeDefined();

  // Sam can only read: the evidence stands on its own, without the power to change anything.
  await actAs(page, SAM);
  await page.goto(`/migrations/${migrationId}/change-requests/${change!.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(change!.key);
  const requirements = page.getByTestId("requirements");
  await expect(requirements).toContainText("Implementation lead");
  await expect(requirements).toContainText("Customer controller");
  // Two different people approved, and neither is the requester.
  const approvers = (await requirements.innerText())
    .split("\n")
    .filter((line) => line.includes("—"))
    .map((line) => line.split("—")[1]!.trim());
  expect(approvers.length).toBe(2);
  expect(new Set(approvers).size).toBe(2);
  expect(approvers).not.toContain(change!.requested_by_name);
  await expect(page.getByTestId("history")).toContainText("Change request applied");

  await page.goto(`/migrations/${migrationId}/audit?entity_type=change_request`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Audit log");
  await expect(page.getByText("chain verified")).toBeVisible();
  await expectAccessible(page);

  const events = await api<{ items: { action: string; before: unknown; after: unknown }[] }>(
    request,
    `/api/v1/migrations/${migrationId}/audit-events?entity_id=${change!.id}&limit=100`,
  );
  const actions = events.items.map((e) => e.action);
  expect(actions).toEqual(
    expect.arrayContaining([
      "change_request.drafted",
      "change_request.submitted",
      "change_request.approval_recorded",
      "change_request.approved",
      "change_request.applied",
    ]),
  );
  expect(actions.filter((a) => a === "change_request.approval_recorded").length).toBe(2);
  const submitted = events.items.find((e) => e.action === "change_request.submitted")!;
  expect(submitted.before).toMatchObject({ status: "draft" });
  expect(submitted.after).toMatchObject({ status: "submitted" });

  // The page renders the same before/after, and the chain verifies over every event.
  await page.goto(`/migrations/${migrationId}/audit?action=change_request.submitted`);
  await page.getByText("before / after").first().click();
  await expect(page.locator("pre").first()).toContainText('"status": "submitted"');

  const chain = await api<{
    valid: boolean;
    events_checked: number;
    first_broken_seq: number | null;
  }>(request, `/api/v1/migrations/${migrationId}/audit-events/verify`);
  expect(chain.valid).toBe(true);
  expect(chain.first_broken_seq).toBeNull();
  expect(chain.events_checked).toBeGreaterThan(events.items.length);
});
