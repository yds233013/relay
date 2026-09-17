import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { FilterForm, SelectFilter } from "@/components/filters";
import { LocalTime } from "@/components/local-time";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

export const dynamic = "force-dynamic";

const STATUSES = [
  ["submitted", "Waiting for approval"],
  ["applied", "Applied"],
  ["stale", "Stale"],
  ["rejected", "Rejected"],
  ["withdrawn", "Withdrawn"],
  ["draft", "Draft"],
  ["", "All"],
] as const;

export default async function ApprovalsPage(
  props: PageProps<"/migrations/[migrationId]/approvals">,
) {
  const { migrationId } = await props.params;
  const query = await props.searchParams;
  const status = param(query.status) ?? "submitted";
  const changes = await apiGet<Schemas["ChangeRequestOut"][]>(
    `/api/v1/migrations/${migrationId}/change-requests`,
    { status: status || undefined },
  );
  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Approvals"
        description="Change requests: nothing changes a run's inputs until the required people approve."
      />
      <FilterForm>
        <SelectFilter name="status" label="Status" value={status} options={STATUSES} />
      </FilterForm>
      <DataTable
        caption={`${changes.length} change requests`}
        rows={changes}
        rowKey={(c) => c.id}
        empty="No change requests match."
        columns={[
          {
            header: "Change request",
            cell: (c) => (
              <Link
                href={`/migrations/${migrationId}/change-requests/${c.id}`}
                className="underline"
              >
                {c.key}: {c.title}
              </Link>
            ),
          },
          { header: "Kind", cell: (c) => humanize(c.kind) },
          { header: "Status", cell: (c) => <StatusChip status={c.status} /> },
          { header: "Requested by", cell: (c) => c.requested_by_name },
          {
            header: "Approvals",
            align: "right",
            cell: (c) => `${c.approvals_given} of ${c.approvals_required}`,
          },
          {
            header: "Submitted",
            cell: (c) => (c.submitted_at ? <LocalTime value={c.submitted_at} /> : "—"),
          },
        ]}
      />
    </div>
  );
}
