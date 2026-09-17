/** Shared steps for end-to-end tests: act as a seeded person, look things up, wait for runs. */
import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, expect, type Page } from "@playwright/test";

export const API = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
export const MAYA = { name: "Maya Chen", email: "maya.chen@relay.example" };
export const DANIEL = { name: "Daniel Okafor", email: "daniel.okafor@relay.example" };
export const PRIYA = { name: "Priya Raman", email: "priya.raman@brightwater.example" };

export interface Issue {
  id: string;
  key: string;
  rule_or_recon_id: string | null;
  subjects: string[];
  status: string;
}

export async function actAs(page: Page, person: { name: string; email: string }): Promise<void> {
  await page.goto("/select-user");
  await page.getByRole("button", { name: `Act as ${person.name}` }).click();
  await expect(page.getByTestId("current-user")).toContainText(person.email);
}

export async function api<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(`${API}${path}`, { headers: { "X-Relay-User": MAYA.email } });
  expect(response.ok(), path).toBeTruthy();
  return (await response.json()) as T;
}

export async function migrationFor(request: APIRequestContext, company: string): Promise<string> {
  const migrations = await api<{ id: string; company_name: string }[]>(
    request,
    "/api/v1/migrations",
  );
  const found = migrations.find((m) => m.company_name.startsWith(company));
  expect(found, company).toBeDefined();
  return found!.id;
}

export async function issues(
  request: APIRequestContext,
  migrationId: string,
  rule?: string,
): Promise<Issue[]> {
  const query = rule ? `&rule=${encodeURIComponent(rule)}` : "";
  const page = await api<{ items: Issue[] }>(
    request,
    `/api/v1/migrations/${migrationId}/issues?limit=500${query}`,
  );
  return page.items;
}

export async function latestRun(request: APIRequestContext, migrationId: string) {
  const runs = await api<{ id: string; sequence: number; status: string }[]>(
    request,
    `/api/v1/migrations/${migrationId}/pipeline-runs?limit=1`,
  );
  const run = runs[0];
  expect(run, "a pipeline run exists").toBeDefined();
  return run!;
}

/** Wait for the first run of a migration that has none yet. */
export async function anyRun(request: APIRequestContext, migrationId: string) {
  const runs = await api<{ id: string; sequence: number; status: string }[]>(
    request,
    `/api/v1/migrations/${migrationId}/pipeline-runs?limit=1`,
  );
  return runs[0];
}

/** Wait until a run newer than `after` has finished and the latest run succeeded. */
export async function waitForRuns(request: APIRequestContext, migrationId: string, after: number) {
  await expect
    .poll(
      async () => {
        const run = await anyRun(request, migrationId);
        return run && run.sequence > after && run.status === "succeeded" ? "done" : run?.status;
      },
      { timeout: 90_000, intervals: [1_000] },
    )
    .toBe("done");
}

export async function exposure(request: APIRequestContext, migrationId: string): Promise<string> {
  const overview = await api<{ unresolved_exposure: string }>(
    request,
    `/api/v1/migrations/${migrationId}/overview`,
  );
  return overview.unresolved_exposure;
}

export async function expectAccessible(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

export async function approve(page: Page, changeUrl: string, notice: RegExp): Promise<void> {
  await page.goto(changeUrl);
  await page.getByLabel("Comment (required to reject)").fill("Checked against the evidence.");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("status").filter({ hasText: notice })).toBeVisible({
    // Applying a change requests a run, which waits while a previous run holds the pipeline lock.
    timeout: 30_000,
  });
}
