import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { LocalTime } from "@/components/local-time";
import { StatusChip } from "@/components/status-chip";
import { PageHeader, Panel, Section } from "@/components/ui";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

export const dynamic = "force-dynamic";

/** Strength is a gate fact, not a colour: strong pairs block G10, possible ones do not. */
function Strength({ strong }: { strong: boolean }) {
  return strong ? (
    <span className="inline-flex items-center whitespace-nowrap rounded border border-[var(--warning)]/40 bg-[var(--warning-soft)] px-1.5 py-0.5 text-xs font-medium text-[var(--warning)]">
      strong
    </span>
  ) : (
    <span className="inline-flex items-center whitespace-nowrap rounded border border-[var(--border-strong)] bg-[var(--surface-sunken)] px-1.5 py-0.5 text-xs font-medium text-[var(--ink-muted)]">
      possible
    </span>
  );
}

export default async function EntitiesPage(props: PageProps<"/migrations/[migrationId]/entities">) {
  const { migrationId } = await props.params;
  const [candidates, decisions] = await Promise.all([
    apiGet<Schemas["CandidateOut"][]>(`/api/v1/migrations/${migrationId}/entity-candidates`),
    apiGet<Schemas["EntityDecisionOut"][]>(`/api/v1/migrations/${migrationId}/entity-decisions`),
  ]);
  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Duplicate parties"
        description="Possible duplicate customers and vendors from the latest run. Nothing is merged without an approved decision."
      />
      <Section
        title="Candidate pairs"
        description="A strong candidate blocks gate G10 until someone decides it; a possible candidate is shown for review and does not block go-live."
      >
        <Panel className="p-3">
          <DataTable
            caption={`${candidates.length} candidate pairs`}
            rows={candidates}
            rowKey={(c) => c.id}
            empty="No candidate pairs in the latest run."
            columns={[
              {
                header: "Pair",
                cell: (c) => (
                  <Link
                    href={`/migrations/${migrationId}/entities/${c.id}`}
                    className="font-medium whitespace-nowrap"
                  >
                    {humanize(c.party_type)} {c.left_code} and {c.right_code}
                  </Link>
                ),
              },
              {
                header: "Score",
                align: "right",
                cell: (c) => <span className="tabular-nums text-[var(--ink)]">{c.score}</span>,
              },
              { header: "Strength", cell: (c) => <Strength strong={c.strong} /> },
              { header: "Status", cell: (c) => <StatusChip status={c.status} /> },
            ]}
          />
        </Panel>
      </Section>
      <Section
        title="Decisions"
        description="Applied through approved change requests. Revert one on the Overrides page."
      >
        <Panel className="p-3">
          <DataTable
            caption={`${decisions.length} decisions`}
            rows={decisions}
            rowKey={(d) => d.id}
            empty="No entity decisions yet."
            columns={[
              {
                header: "Decision",
                cell: (d) => (
                  <span className="text-[var(--ink)]">
                    <span className="font-medium">{humanize(d.decision)}</span>:{" "}
                    {d.members.join(", ")}
                    {d.survivor ? (
                      <span className="text-[var(--ink-muted)]"> (survivor {d.survivor})</span>
                    ) : null}
                  </span>
                ),
              },
              { header: "Status", cell: (d) => <StatusChip status={d.status} /> },
              {
                header: "Approved by change request",
                cell: (d) => (
                  <Link
                    href={`/migrations/${migrationId}/change-requests/${d.change_request_id}`}
                    className="whitespace-nowrap"
                  >
                    Open change request
                  </Link>
                ),
              },
              { header: "Created", cell: (d) => <LocalTime value={d.created_at} /> },
            ]}
          />
        </Panel>
      </Section>
    </div>
  );
}
