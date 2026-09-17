/**
 * E2E-7: with RELAY_AI_PROVIDER=disabled (the default stack), no AI control is rendered and starting
 * an investigation is refused by the API. Every other E2E flow runs in this same mode, which is the
 * rest of the acceptance: removing AI removes no workflow. Read-only; runs in any order.
 */
import { expect, test } from "@playwright/test";

import { actAs, API, expectAccessible, issues, MAYA, migrationFor } from "./support/relay";

test("E2E-7: AI disabled shows no AI controls and the API refuses investigations", async ({
  page,
  request,
}) => {
  const migrationId = await migrationFor(request, "Brightwater Provisions");
  const status = await request.get(`${API}/api/v1/ai/status?migration_id=${migrationId}`, {
    headers: { "X-Relay-User": MAYA.email },
  });
  expect(await status.json()).toMatchObject({ provider: "disabled", available: false });

  await actAs(page, MAYA);
  await page.goto(`/migrations/${migrationId}`);
  await expect(page.getByTestId("readiness-banner")).toBeVisible();
  await expect(page.getByTestId("investigate-panel")).toHaveCount(0);
  await expect(page.getByText(/investigate with ai/i)).toHaveCount(0);

  const [issue] = await issues(request, migrationId);
  expect(issue).toBeDefined();
  await page.goto(`/migrations/${migrationId}/issues/${issue!.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(issue!.key);
  await expect(page.getByTestId("investigate-panel")).toHaveCount(0);
  await expect(page.getByTestId("ai-label")).toHaveCount(0);
  await expectAccessible(page);

  const refused = await request.post(`${API}/api/v1/migrations/${migrationId}/investigations`, {
    headers: { "X-Relay-User": MAYA.email },
    data: { question: "Why doesn't AR tie?", issue_id: issue!.id },
  });
  expect(refused.status()).toBe(409);
});
