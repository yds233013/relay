import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { LocalTime } from "@/components/local-time";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function EntitiesPage(props: PageProps<"/migrations/[migrationId]/entities">) {
  const { migrationId } = await props.params;
  const [candidates, decisions] = await Promise.all([
    apiGet<Schemas["CandidateOut"][]>(`/api/v1/migrations/${migrationId}/entity-candidates`),
    apiGet<Schemas["EntityDecisionOut"][]>(`/api/v1/migrations/${migrationId}/entity-decisions`),
  ]);
  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Entities"
        description="Possible duplicate customers and vendors from the latest run. Nothing is merged without an approved decision."
      />
      <DataTable
        caption={`${candidates.length} candidate pairs`}
        rows={candidates}
        rowKey={(c) => c.id}
        empty="No candidate pairs in the latest run."
        columns={[
          {
            header: "Pair",
            cell: (c) => (
              <Link href={`/migrations/${migrationId}/entities/${c.id}`} className="underline">
                {humanize(c.party_type)} {c.left_code} and {c.right_code}
              </Link>
            ),
          },
          { header: "Score", align: "right", cell: (c) => c.score },
          { header: "Strength", cell: (c) => (c.strong ? "strong" : "possible") },
          { header: "Status", cell: (c) => <StatusChip status={c.status} /> },
        ]}
      />
      <Section title="Decisions">
        <DataTable
          caption={`${decisions.length} decisions`}
          rows={decisions}
          rowKey={(d) => d.id}
          empty="No entity decisions yet."
          columns={[
            {
              header: "Decision",
              cell: (d) =>
                `${humanize(d.decision)}: ${d.members.join(", ")}${d.survivor ? ` (survivor ${d.survivor})` : ""}`,
            },
            { header: "Status", cell: (d) => <StatusChip status={d.status} /> },
            {
              header: "Approved by change request",
              cell: (d) => (
                <Link
                  href={`/migrations/${migrationId}/change-requests/${d.change_request_id}`}
                  className="underline"
                >
                  view
                </Link>
              ),
            },
            { header: "Created", cell: (d) => <LocalTime value={d.created_at} /> },
          ]}
        />
      </Section>
    </div>
  );
}
