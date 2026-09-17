import Link from "next/link";

import { Timestamp } from "@/components/dates";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";

export const dynamic = "force-dynamic";

export default async function RunsPage(props: PageProps<"/migrations/[migrationId]/runs">) {
  const { migrationId } = await props.params;
  const runs = await apiGet<Schemas["RunOut"][]>(`/api/v1/migrations/${migrationId}/pipeline-runs`);
  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Runs"
        description="Each run is a deterministic function of its input fingerprint."
      />
      <DataTable<Schemas["RunOut"]>
        caption={`${runs.length} runs`}
        rows={runs}
        rowKey={(run) => run.id}
        columns={[
          {
            header: "Run",
            cell: (r) => (
              <Link
                href={`/migrations/${migrationId}/runs/${r.id}`}
                className="text-blue-800 underline"
              >
                #{r.sequence}
              </Link>
            ),
          },
          { header: "Status", cell: (r) => <StatusChip status={r.status} /> },
          {
            header: "Current",
            cell: (r) =>
              r.is_current ? (
                <StatusChip status="pass" label="current" />
              ) : (
                <StatusChip status="stale" />
              ),
          },
          {
            header: "Fingerprint",
            cell: (r) => <span className="font-mono text-xs">{r.fingerprint.slice(0, 12)}</span>,
          },
          { header: "Findings", align: "right", cell: (r) => String(r.counts.findings ?? "—") },
          { header: "Requested", cell: (r) => <Timestamp value={r.requested_at} /> },
        ]}
      />
    </div>
  );
}
