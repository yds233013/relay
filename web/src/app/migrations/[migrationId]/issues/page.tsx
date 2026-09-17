import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { FilterForm, SelectFilter } from "@/components/filters";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";

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
