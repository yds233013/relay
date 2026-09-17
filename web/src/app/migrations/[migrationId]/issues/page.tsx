import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { FilterForm, SelectFilter } from "@/components/filters";
import { Money } from "@/components/money";
import { SubmitButton, TextArea, TextField } from "@/components/forms";
import { Notice } from "@/components/notice";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { createManualIssue } from "../workflow-actions";

const CATEGORIES = ["completeness", "mapping", "ledger_integrity", "subledger", "cash",
  "master_data", "currency", "dates", "ai_safety", "other"] as const; // prettier-ignore

function Choice({ name, options }: { name: string; options: readonly string[] }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-medium text-gray-700">{humanize(name)}</span>
      <select name={name} className="rounded border border-gray-400 bg-white px-2 py-1">
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
  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Issues"
        description="Findings tracked across runs. Resolved only when a current run no longer reports them."
      />
      <Notice error={param(search.error)} notice={param(search.notice)} />
      <details className="mb-4 rounded border border-gray-200 p-2">
        <summary className="cursor-pointer text-sm font-medium">Raise a manual issue</summary>
        <form action={createManualIssue} className="mt-2 flex max-w-2xl flex-col gap-2">
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
      <DataTable<Schemas["IssueOut"]>
        caption={`${page.items.length} issues on this page`}
        rows={page.items}
        rowKey={(issue) => issue.id}
        nextHref={
          page.next_cursor
            ? buildPath(`${base}/issues`, { ...filters, cursor: page.next_cursor })
            : null
        }
        columns={[
          {
            header: "Key",
            cell: (i) => (
              <Link href={`${base}/issues/${i.id}`} className="text-blue-800 underline">
                {i.key}
              </Link>
            ),
          },
          { header: "Severity", cell: (i) => <StatusChip status={i.severity} /> },
          { header: "Status", cell: (i) => <StatusChip status={i.status} /> },
          { header: "Title", cell: (i) => i.title },
          { header: "Nature", cell: (i) => i.nature.replace("_", " ") },
          {
            header: "Amount at risk",
            align: "right",
            cell: (i) => <Money value={i.amount_at_risk} currency={i.currency} />,
          },
        ]}
      />
    </div>
  );
}
