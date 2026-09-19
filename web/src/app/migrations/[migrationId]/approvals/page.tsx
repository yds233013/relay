import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { FilterForm, SelectFilter } from "@/components/filters";
import { LocalTime } from "@/components/local-time";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Callout, Panel } from "@/components/ui";
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

/** What the queue is showing, said once in plain words rather than left to the select box. */
const VIEW_GLOSS: Record<string, string> = {
  submitted: "Submitted and waiting for the approvals listed on each row.",
  applied: "Approved and applied. Each one was followed by a fresh run that re-checked the data.",
  stale: "What these were based on has changed since. They cannot be applied as they stand.",
  rejected: "Reviewed and turned down. The reason is recorded on the change request.",
  withdrawn: "Pulled back by the person who proposed them, before any decision.",
  draft: "Prepared but not yet submitted for review.",
  "": "Every change request ever raised on this migration, in any state.",
};

/** One line on what each kind of change actually touches. */
const KIND_GLOSS: Record<string, string> = {
  account_mapping_set: "legacy accounts re-pointed at the target chart",
  column_mapping_set: "how one export is read into canonical fields",
  record_override: "one staged record corrected by an overlay",
  entity_decision: "duplicate parties merged or kept distinct",
  disposition: "a legacy misstatement accepted with a follow-up",
  policy_change: "a governed setting of this migration",
  gate_waiver: "one readiness gate waived within a stated scope",
  readiness_signoff: "go-live signed off against one exact set of inputs",
  revert: "an applied overlay withdrawn again",
};

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
  const label = STATUSES.find(([value]) => value === status)?.[1] ?? "All";
  const waiting = changes.filter((c) => c.status === "submitted").length;
  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Approvals"
        description="Every change to a migration's inputs is proposed here first. Nothing takes effect until the required people, none of them the requester, have approved it."
      />
      <div className="mb-4">
        <Callout>
          A change request carries its own evidence: what it would change, why, and who asked for
          it. Approving the last outstanding requirement applies it in one transaction and triggers
          a fresh deterministic run over the new inputs.
        </Callout>
      </div>

      {/* The queue is filtered by default, so the filter says so in words, not only in a control. */}
      <Panel className="mb-4 p-3">
        <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h2 className="text-sm font-semibold text-[var(--ink)]">
            Showing: {label.toLowerCase()}
          </h2>
          <span className="rounded border border-[var(--border-strong)] bg-white px-1.5 py-0.5 text-xs font-medium tabular-nums text-[var(--ink)]">
            {changes.length} change requests
          </span>
          {status !== "" ? (
            <Link href={`/migrations/${migrationId}/approvals?status=`} className="text-sm">
              show every status
            </Link>
          ) : null}
        </div>
        <p className="mb-3 max-w-3xl text-sm text-[var(--ink-muted)]">
          {VIEW_GLOSS[status] ?? VIEW_GLOSS[""]}
          {status !== "submitted" && waiting > 0
            ? ` ${waiting} of these are still waiting for approval.`
            : ""}
        </p>
        <FilterForm>
          <SelectFilter name="status" label="Status" value={status} options={STATUSES} />
        </FilterForm>
      </Panel>

      <DataTable
        caption={`${changes.length} change requests`}
        rows={changes}
        rowKey={(c) => c.id}
        empty="No change requests match."
        columns={[
          {
            header: "Change request",
            cell: (c) => (
              <>
                <Link
                  href={`/migrations/${migrationId}/change-requests/${c.id}`}
                  className="underline"
                >
                  {c.key}: {c.title}
                </Link>
                <span className="block text-xs text-[var(--ink-muted)]">
                  {humanize(c.kind)}
                  {KIND_GLOSS[c.kind] ? ` · ${KIND_GLOSS[c.kind]}` : ""}
                </span>
              </>
            ),
          },
          { header: "Kind", cell: (c) => humanize(c.kind) },
          { header: "Status", cell: (c) => <StatusChip status={c.status} /> },
          {
            header: "Requested by",
            cell: (c) => (
              <>
                {c.requested_by_name}
                <span className="block text-xs text-[var(--ink-subtle)]">
                  {c.origin === "ai_finding" ? "from an AI finding" : "operator"}
                </span>
              </>
            ),
          },
          {
            header: "Approvals",
            align: "right",
            cell: (c) => (
              <>
                <span className="tabular-nums">
                  {c.approvals_given} of {c.approvals_required}
                </span>
                <span className="block text-xs text-[var(--ink-subtle)]">
                  {c.approvals_given >= c.approvals_required
                    ? "complete"
                    : `${c.approvals_required - c.approvals_given} outstanding`}
                </span>
              </>
            ),
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
