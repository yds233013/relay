import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { FilterForm, SelectFilter } from "@/components/filters";
import { Money } from "@/components/money";
import { SubmitButton, TextArea, TextField } from "@/components/forms";
import { Notice } from "@/components/notice";
import { StatusChip } from "@/components/status-chip";
import { PageHeader, Panel, Section } from "@/components/ui";
import { apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { humanize, param, splitTitle } from "@/lib/format";

import { createManualIssue } from "../workflow-actions";

const CATEGORIES = ["completeness", "mapping", "ledger_integrity", "subledger", "cash",
  "master_data", "currency", "dates", "ai_safety", "other"] as const; // prettier-ignore

const CONTROL =
  "rounded-[var(--radius-control)] border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-sm text-[var(--ink)]";

function Choice({ name, options }: { name: string; options: readonly string[] }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-medium text-[var(--ink-muted)]">{humanize(name)}</span>
      <select name={name} className={CONTROL}>
        {options.map((option) => (
          <option key={option} value={option}>
            {humanize(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

export const dynamic = "force-dynamic";

export default async function IssuesPage(props: PageProps<"/migrations/[migrationId]/issues">) {
  const { migrationId } = await props.params;
  const search = await props.searchParams;
  const filters = {
    status: param(search.status),
    severity: param(search.severity),
    nature: param(search.nature),
    order: param(search.order) === "amount" ? "amount" : "key",
    fingerprint: param(search.fingerprint),
  };
  const cursor = param(search.cursor);
  const page = await apiGet<Schemas["Page_IssueOut_"]>(`/api/v1/migrations/${migrationId}/issues`, {
    ...filters,
    cursor,
    limit: 100,
  });
  const base = `/migrations/${migrationId}`;
  // Stated in words, so a filtered list is never mistaken for the whole population.
  const applied = [
    filters.status ? `status ${humanize(filters.status).toLowerCase()}` : null,
    filters.severity ? `severity ${filters.severity}` : null,
    filters.nature ? `nature ${filters.nature.replace("_", " ")}` : null,
    filters.fingerprint ? "one finding fingerprint" : null,
  ].filter((entry): entry is string => entry !== null);
  return (
    <div className="max-w-[1280px]">
      <PageHeader
        title="Issues"
        description="Findings tracked across runs. Resolved only when a current run no longer reports them."
      />
      <Notice error={param(search.error)} notice={param(search.notice)} />

      {/* The filter bar reads as one control surface, and says plainly what it is showing. */}
      <Panel className="mb-4 p-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
          Filter
        </p>
        <FilterForm>
          <SelectFilter
            name="status"
            label="Status"
            value={filters.status}
            options={[
              ["open", "Open"],
              ["resolved", "Resolved"],
              ["dispositioned", "Dispositioned"],
            ]}
          />
          <SelectFilter
            name="severity"
            label="Severity"
            value={filters.severity}
            options={[
              ["critical", "Critical"],
              ["high", "High"],
              ["medium", "Medium"],
              ["low", "Low"],
            ]}
          />
          <SelectFilter
            name="nature"
            label="Nature"
            value={filters.nature}
            options={[
              ["migration_defect", "Migration defect"],
              ["source_anomaly", "Source anomaly"],
            ]}
          />
          <SelectFilter
            name="order"
            label="Order"
            value={filters.order}
            options={[
              ["key", "Key"],
              ["amount", "Amount at risk"],
            ]}
          />
        </FilterForm>
        <p className="border-t border-[var(--border)] pt-2 text-sm text-[var(--ink-muted)]">
          {applied.length === 0 ? (
            <>
              <span className="font-medium text-[var(--ink)]">No filter applied.</span> Every issue
              of this migration is listed, ordered by{" "}
              {filters.order === "amount" ? "amount at risk" : "issue key"}.
            </>
          ) : (
            <>
              <span className="font-medium text-[var(--ink)]">
                Filtered by {applied.join(", ")}
              </span>
              , ordered by {filters.order === "amount" ? "amount at risk" : "issue key"}.
            </>
          )}
        </p>
      </Panel>

      <Panel className="mb-6 p-3">
        <DataTable<Schemas["IssueOut"]>
          caption={`${page.items.length} issues on this page`}
          rows={page.items}
          rowKey={(issue) => issue.id}
          empty="No issues match this filter."
          nextHref={
            page.next_cursor
              ? buildPath(`${base}/issues`, { ...filters, cursor: page.next_cursor })
              : null
          }
          columns={[
            {
              header: "Key",
              cell: (i) => (
                <Link href={`${base}/issues/${i.id}`} className="font-medium whitespace-nowrap">
                  {i.key}
                </Link>
              ),
            },
            { header: "Severity", cell: (i) => <StatusChip status={i.severity} /> },
            { header: "Status", cell: (i) => <StatusChip status={i.status} /> },
            {
              header: "Finding",
              // The sentence leads; the identifiers it names follow in the technical tier, so a
              // reader scanning sixty-five rows reads sixty-five sentences rather than sixty-five
              // record keys.
              cell: (i) => {
                const { headline, subject } = splitTitle(i.title, i.subjects);
                return (
                  <>
                    <span className="text-[var(--ink)]">{headline}</span>
                    {subject ? (
                      <span className="mt-0.5 block font-mono text-[11px] text-[var(--ink-subtle)]">
                        {subject}
                      </span>
                    ) : null}
                  </>
                );
              },
            },
            {
              header: "Nature",
              cell: (i) => (
                <span className="whitespace-nowrap text-[var(--ink-muted)]">
                  {i.nature.replace("_", " ")}
                </span>
              ),
            },
            {
              header: "Owner",
              cell: (i) =>
                (i.owner_name ?? i.owner_user_id) ? (
                  <span className="whitespace-nowrap text-[var(--ink)]">
                    {i.owner_name ?? i.owner_user_id}
                  </span>
                ) : (
                  <span className="text-[var(--ink-subtle)]">unassigned</span>
                ),
            },
            {
              header: "Amount at risk",
              align: "right",
              cell: (i) => <Money value={i.amount_at_risk} currency={i.currency} />,
            },
          ]}
        />
      </Panel>

      {/* Manual issues are rare and deliberate: folded away, but plainly available. */}
      <Section
        title="Manual issue"
        description="For a problem the rules do not catch. It follows the same workflow, but no run can resolve it."
      >
        <details className="rounded-[var(--radius-card)] border border-[var(--border)] bg-[var(--surface-raised)]">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-[var(--ink)]">
            Raise a manual issue
          </summary>
          <form
            action={createManualIssue}
            className="flex max-w-2xl flex-col gap-3 border-t border-[var(--border)] p-3"
          >
            <input type="hidden" name="migrationId" value={migrationId} />
            <TextField name="title" label="Title" required />
            <span className="flex flex-wrap gap-3">
              <Choice name="severity" options={["critical", "high", "medium", "low"]} />
              <Choice name="category" options={CATEGORIES} />
              <Choice name="nature" options={["migration_defect", "source_anomaly"]} />
            </span>
            <TextArea name="description" label="Description" />
            <span>
              <SubmitButton tone="secondary">Raise issue</SubmitButton>
            </span>
          </form>
        </details>
      </Section>
    </div>
  );
}
