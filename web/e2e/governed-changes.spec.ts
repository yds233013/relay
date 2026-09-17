/**
 * E2E-2 (docs/testing.md) and the M5 corrections through the UI: DS-03 account mapping change with
 * segregation of duties, DS-08 and DS-11 entry-date overrides, DS-05 quarantined row repair.
 *
 * Needs a freshly seeded stack (`make demo-reset`): these tests change the demo state. The API is
 * used only to look up identifiers and to prove the API rejects what the UI does not offer; every
 * change is proposed and approved through the web pages.
 */
import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

const API = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
const MAYA = { name: "Maya Chen", email: "maya.chen@relay.example" };
const DANIEL = { name: "Daniel Okafor", email: "daniel.okafor@relay.example" };
const PRIYA = { name: "Priya Raman", email: "priya.raman@brightwater.example" };

interface Issue {
  id: string;
  rule_or_recon_id: string | null;
  subjects: string[];
  status: string;
}

test.describe.configure({ mode: "serial" });

async function actAs(page: Page, person: { name: string; email: string }): Promise<void> {
  await page.goto("/select-user");
  await page.getByRole("button", { name: `Act as ${person.name}` }).click();
  await expect(page.getByTestId("current-user")).toContainText(person.email);
}

async function api<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(`${API}${path}`, {
    headers: { "X-Relay-User": MAYA.email },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as T;
}

async function brightwater(request: APIRequestContext): Promise<string> {
  const migrations = await api<{ id: string; company_name: string }[]>(
    request,
    "/api/v1/migrations",
  );
  const found = migrations.find((m) => m.company_name.startsWith("Brightwater Provisions"));
  expect(found).toBeDefined();
  return found!.id;
}

async function issue(
  request: APIRequestContext,
  migrationId: string,
  rule: string,
  subject: string,
): Promise<Issue> {
  const page = await api<{ items: Issue[] }>(
    request,
    `/api/v1/migrations/${migrationId}/issues?limit=500`,
  );
  const found = page.items.find((i) => i.rule_or_recon_id === rule && i.subjects.includes(subject));
  expect(found, `${rule} on ${subject}`).toBeDefined();
  return found!;
}

async function latestRun(request: APIRequestContext, migrationId: string) {
  const runs = await api<{ id: string; sequence: number; status: string }[]>(
    request,
    `/api/v1/migrations/${migrationId}/pipeline-runs?limit=1`,
  );
  return runs[0]!;
}

/** Wait until every requested run has finished and the latest one succeeded. */
async function waitForRuns(request: APIRequestContext, migrationId: string, after: number) {
  await expect
    .poll(
      async () => {
        const run = await latestRun(request, migrationId);
        return run.sequence > after && run.status === "succeeded" ? "done" : run.status;
      },
      { timeout: 90_000, intervals: [1_000] },
    )
    .toBe("done");
}

async function expectAccessible(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

async function approve(page: Page, changeUrl: string, expectedNotice: RegExp): Promise<void> {
  await page.goto(changeUrl);
  await page.getByLabel("Comment (required to reject)").fill("Checked against the evidence.");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("status").filter({ hasText: expectedNotice })).toBeVisible({
    // Applying a change requests a run, which waits while a previous run holds the pipeline lock.
    timeout: 30_000,
  });
}

test("E2E-2: account mapping change needs lead and controller, never the requester", async ({
  page,
  request,
}) => {
  const migrationId = await brightwater(request);
  const before = await latestRun(request, migrationId);

  await actAs(page, MAYA);
  await page.goto(`/migrations/${migrationId}/mappings`);
  const row = page.locator("[data-legacy='1205']");
  await expect(row).toContainText("subtype conflict");
  await expect(row).toContainText("1210");
  await expectAccessible(page);
  await row.getByLabel("New target for 1205").fill("1210");
  await row.getByLabel("Rationale for 1205").fill("Allowance is a contra-asset");
  await page.getByLabel("Title").fill("Map allowance to allowance for credit losses");
  await page
    .getByLabel("Justification")
    .fill("1205 is a contra-asset and must not be merged into receivables.");
  await page.getByRole("button", { name: "Propose mapping change" }).click();

  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Map allowance to allowance for credit losses",
  );
  await page.waitForURL(/\/change-requests\/[0-9a-f-]+/);
  const changeUrl = page.url();
  const changeId = changeUrl.split("/").pop()!;
  await expect(page.locator("[data-status='submitted']").first()).toBeVisible();
  await expect(page.getByTestId("mapping-diff")).toContainText("1205");
  await expect(page.getByTestId("mapping-diff")).toContainText("subtype ok");
  // Maya has no approve button, and the API rejects her approval regardless.
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expect(page.getByTestId("review-unavailable")).toBeVisible();
  const denied = await request.post(`${API}/api/v1/change-requests/${changeId}/approve`, {
    headers: { "X-Relay-User": MAYA.email },
    data: { comment: "self approval" },
  });
  expect(denied.status()).toBe(403);
  await expectAccessible(page);

  await actAs(page, DANIEL);
  await approve(page, changeUrl, /More approvals are required/);
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);

  await actAs(page, PRIYA);
  await approve(page, changeUrl, /Approved and applied/);
  await expect(page.locator("[data-status='applied']").first()).toBeVisible();
  await expect(page.getByTestId("history")).toContainText("Change request applied");

  await waitForRuns(request, migrationId, before.sequence);
  await page.goto(`/migrations/${migrationId}`);
  const blockers = page.getByTestId("blockers");
  await expect(blockers.getByRole("link", { name: "R3:party=C-0233" })).toBeVisible();
  await expect(blockers.getByRole("link", { name: "R3:party=unassigned" })).toHaveCount(0);
  const mappingIssue = await issue(
    request,
    migrationId,
    "MAP.SUBTYPE_COMPATIBLE",
    "acct:legacy:1205",
  );
  expect(mappingIssue.status).toBe("resolved");
});

test("DS-08, DS-11 and DS-05 are corrected through overrides approved in the UI", async ({
  page,
  request,
}) => {
  const migrationId = await brightwater(request);
  const run = await latestRun(request, migrationId);
  const changeUrls: string[] = [];

  await actAs(page, MAYA);
  for (const [entry, value, why] of [
    ["JE-2026-0388", "2026-03-31", "Adjustment belongs to the March close."],
    ["JE-AP-20455", "2026-03-14", "Keying error; bill date and posting period are March 2026."],
  ] as const) {
    const key = `je:${entry}`;
    await page.goto(`/migrations/${migrationId}/records/${run.id}/${encodeURIComponent(key)}`);
    await page.getByLabel("Field").selectOption("entry_date");
    await page.getByLabel("New value").fill(value);
    await page.getByLabel("Justification and evidence").fill(why);
    await page.getByRole("button", { name: "Propose correction" }).click();
    await expect(page.getByTestId("before-after")).toContainText(value);
    await expect(page.getByTestId("requirements")).toContainText("Customer controller");
    await page.waitForURL(/\/change-requests\/[0-9a-f-]+/);
    changeUrls.push(page.url());
  }

  const issues = await api<{ items: Issue[] }>(
    request,
    `/api/v1/migrations/${migrationId}/issues?limit=500`,
  );
  const quarantine = issues.items.find((i) => i.rule_or_recon_id === "NORM.MALFORMED_ROW")!;
  await page.goto(`/migrations/${migrationId}/issues/${quarantine.id}`);
  const replacement = page.getByLabel("Replacement record");
  // The export broke one record at an unquoted line break; the operator joins the two lines.
  const raw = await replacement.inputValue();
  await replacement.fill(raw.replace(/\r?\n/g, " ").trimEnd());
  await page
    .getByLabel("Justification")
    .fill("The memo contained a line break; the repaired record joins the two lines.");
  await page.getByRole("button", { name: "Propose repair" }).click();
  await expect(page.getByTestId("before-after")).toContainText("JE-2026-0412");
  await expectAccessible(page);
  await page.waitForURL(/\/change-requests\/[0-9a-f-]+/);
  changeUrls.push(page.url());

  await actAs(page, DANIEL);
  for (const url of changeUrls) {
    await approve(page, url, /More approvals are required/);
  }
  await actAs(page, PRIYA);
  for (const url of changeUrls) {
    await approve(page, url, /Approved and applied/);
  }

  await waitForRuns(request, migrationId, run.sequence);
  for (const [rule, subject] of [
    ["GL.PERIOD_MATCHES_DATE", "je:JE-2026-0388"],
    ["GL.DATE_IN_WINDOW", "je:JE-AP-20455"],
    ["NORM.MALFORMED_ROW", quarantine.subjects[0]!],
  ] as const) {
    const resolved = await issue(request, migrationId, rule, subject);
    expect(resolved.status, `${rule} ${subject}`).toBe("resolved");
  }
  await page.goto(`/migrations/${migrationId}/overrides`);
  await expect(page.getByTestId("overrides").locator("[data-status='active']")).toHaveCount(3);
});
