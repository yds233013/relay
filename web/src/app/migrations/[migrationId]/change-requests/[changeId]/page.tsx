import Link from "next/link";

import { DemoUnavailable } from "@/components/demo-note";
import { SubmitButton, TextArea } from "@/components/forms";
import { LocalTime } from "@/components/local-time";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { Callout, MetaList, Panel, ProvenanceBadge, type Tone } from "@/components/ui";
import { SignalChips } from "@/components/signal-chips";
import { StatusChip } from "@/components/status-chip";
import { isPublicDemo } from "@/lib/demo";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";
import { TABLE, TD, TH, THEAD_ROW, TR } from "@/components/table";

import {
  reviewChangeRequest,
  submitChangeRequest,
  withdrawChangeRequest,
} from "../../governance-actions";

export const dynamic = "force-dynamic";

type Detail = Schemas["ChangeRequestDetailOut"];
type Json = Record<string, unknown>;

/**
 * What each kind of change actually does, for a reader who does not know Relay's internals. The
 * recurring point: nothing here edits the legacy data. Corrections are overlays and re-derivations,
 * and they only take effect through a run.
 */
const KIND_GLOSS: Record<string, string> = {
  account_mapping_set:
    "Re-points legacy accounts at different accounts in the target chart. The legacy ledger is untouched; what changes is how Relay derives canonical records from it.",
  column_mapping_set:
    "Changes how the columns of one legacy export are read into canonical fields. The file itself is immutable: it is simply re-read under the new mapping.",
  record_override:
    "Corrects one staged record. The source row keeps its original values permanently; the correction is an overlay recorded on top of it.",
  entity_decision:
    "Records a merge or keep-distinct decision about parties the engine flagged as possible duplicates. The legacy parties are never rewritten.",
  disposition:
    "Accepts a real misstatement in the legacy books with a documented reason and follow-up, instead of quietly correcting migration history.",
  policy_change: "Changes a governed setting of this migration.",
  gate_waiver:
    "Waives one readiness gate within a stated scope. The gate keeps evaluating, and the waiver lapses if the evidence behind it moves.",
  readiness_signoff:
    "Signs off go-live readiness against one exact set of inputs, and is invalidated if those inputs change.",
  revert: "Withdraws an overlay applied earlier, through exactly the approvals that created it.",
};

function str(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return typeof value === "string" ? value : JSON.stringify(value);
}

/* ------------------------------------------------------------------ lifecycle */

type StepState = "done" | "current" | "blocked" | "stopped" | "pending";

const STEP_MARK: Record<StepState, { icon: string; label: string; tone: Tone; ink: string }> = {
  done: { icon: "✓", label: "Done", tone: "positive", ink: "text-[var(--positive)]" },
  current: { icon: "→", label: "Now", tone: "accent", ink: "text-[var(--accent-ink)]" },
  blocked: { icon: "!", label: "Blocked", tone: "warning", ink: "text-[var(--warning)]" },
  stopped: { icon: "✕", label: "Stopped", tone: "critical", ink: "text-[var(--critical)]" },
  pending: { icon: "○", label: "Not yet", tone: "neutral", ink: "text-[var(--ink-subtle)]" },
};

interface Step {
  readonly name: string;
  readonly state: StepState;
  readonly detail: React.ReactNode;
}

/**
 * The control, step by step, derived only from what the API reports: the status and timestamps of
 * the change request, the approvals recorded against its requirements, and the runs it requested.
 */
function lifecycle(detail: Detail, migrationId: string): Step[] {
  const change = detail.change_request;
  const status = change.status;
  const halted = status === "rejected" || status === "withdrawn";
  const outstanding = detail.requirements.filter((r) => r.satisfied_by === null);
  const approved =
    change.applied_at !== null ||
    (!halted &&
      change.submitted_at !== null &&
      detail.requirements.length > 0 &&
      outstanding.length === 0);
  const run = detail.runs[detail.runs.length - 1];

  const proposed: StepState = change.submitted_at
    ? "done"
    : halted
      ? "stopped"
      : status === "draft"
        ? "current"
        : "pending";
  const reviewed: StepState = halted
    ? "stopped"
    : approved
      ? "done"
      : status === "stale"
        ? "blocked"
        : status === "submitted"
          ? "current"
          : "pending";
  const applied: StepState = change.applied_at
    ? "done"
    : halted
      ? "stopped"
      : status === "stale"
        ? "blocked"
        : approved
          ? "current"
          : "pending";
  const verified: StepState =
    detail.runs.length > 0
      ? "done"
      : halted
        ? "stopped"
        : change.applied_at
          ? "current"
          : "pending";

  return [
    {
      name: "Proposed with evidence",
      state: proposed,
      detail: (
        <>
          {change.requested_by_name}
          {change.submitted_at ? (
            <>
              {" submitted "}
              <LocalTime value={change.submitted_at} />
            </>
          ) : (
            " has not submitted it for review yet"
          )}
        </>
      ),
    },
    {
      name: "Approved by other people",
      state: reviewed,
      detail: (
        <>
          {change.approvals_given} of {change.approvals_required} required approvals recorded
          {outstanding.length > 0 && !halted
            ? `; waiting on ${outstanding.map((r) => humanize(r.role).toLowerCase()).join(" and ")}`
            : ""}
        </>
      ),
    },
    {
      name: "Applied in one transaction",
      state: applied,
      detail: change.applied_at ? (
        <LocalTime value={change.applied_at} />
      ) : (
        "The overlay and its audit event are written together, or not at all."
      ),
    },
    {
      name: "Re-verified by a fresh run",
      state: verified,
      detail: run ? (
        <Link href={`/migrations/${migrationId}/runs/${run}`}>
          Deterministic checks re-ran on the new inputs
        </Link>
      ) : (
        "A run is requested automatically once the change applies."
      ),
    },
  ];
}

function Lifecycle({ steps }: { steps: readonly Step[] }) {
  return (
    <ol className="mb-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-4" aria-label="Control steps">
      {steps.map((step, index) => {
        const mark = STEP_MARK[step.state];
        return (
          <li key={step.name} aria-current={step.state === "current" ? "step" : undefined}>
            <Panel tone={mark.tone} className="h-full p-3.5">
              <p
                className={`flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] ${mark.ink}`}
              >
                <span aria-hidden="true">{mark.icon}</span>
                {mark.label}
              </p>
              <p className="mt-1.5 text-sm font-semibold text-[var(--ink)]">
                {index + 1}. {step.name}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-[var(--ink-muted)]">{step.detail}</p>
            </Panel>
          </li>
        );
      })}
    </ol>
  );
}

/* ------------------------------------------------------------------ the change itself */

function AccountMappingChanges({ detail }: { detail: Detail }) {
  const impact = (detail.impact ?? {}) as Json;
  const changes = (impact.changes ?? []) as Json[];
  return (
    <div className="relative overflow-x-auto" tabIndex={0}>
      <table className={`${TABLE} mb-1`} data-testid="mapping-diff">
        <caption className="mb-2 text-left text-sm text-[var(--ink)]">
          {str(impact.changed_count)} legacy accounts change
          {impact.changes_truncated ? " (first 500 shown)" : ""}.
        </caption>
        <thead>
          <tr className={THEAD_ROW}>
            <th scope="col" className={TH}>
              Legacy account
            </th>
            <th scope="col" className={TH}>
              Before
            </th>
            <th scope="col" className={TH}>
              After
            </th>
            <th scope="col" className={TH}>
              Compatibility of new target
            </th>
            <th scope="col" className={TH}>
              Rationale
            </th>
          </tr>
        </thead>
        <tbody>
          {changes.map((change) => (
            <tr key={str(change.legacy)} className={TR}>
              <td className={TD}>
                <span className="font-mono">{str(change.legacy)}</span> {str(change.legacy_name)}
                <span className="block text-xs text-[var(--ink-muted)]">
                  {str(change.legacy_subtype)}
                </span>
              </td>
              <td className={TD}>
                <del className="font-mono">{str(change.before)}</del> {str(change.before_name)}
              </td>
              <td className={TD}>
                <ins className="font-mono no-underline">{str(change.after)}</ins>{" "}
                {str(change.after_name)}
                <span className="block text-xs text-[var(--ink-muted)]">
                  {str(change.after_subtype)}
                </span>
              </td>
              <td className={TD}>
                <SignalChips signals={change.signals} />
              </td>
              <td className={TD}>{str(change.rationale)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BeforeAfter({ rows }: { rows: [string, unknown, unknown][] }) {
  return (
    <table className={TABLE} data-testid="before-after">
      <caption className="sr-only">Before and after</caption>
      <thead>
        <tr className={THEAD_ROW}>
          <th scope="col" className={TH}>
            Field
          </th>
          <th scope="col" className={TH}>
            Before
          </th>
          <th scope="col" className={TH}>
            After
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, before, after]) => (
          <tr key={label} className={TR}>
            <th scope="row" className="px-2 py-1.5 font-normal text-[var(--ink-muted)]">
              {label}
            </th>
            <td className="px-2 py-1.5 font-mono text-xs whitespace-pre-wrap">{str(before)}</td>
            <td className="px-2 py-1.5 font-mono text-xs whitespace-pre-wrap">{str(after)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Diff({ detail, migrationId }: { detail: Detail; migrationId: string }) {
  const before = (detail.before ?? {}) as Json;
  const after = (detail.after ?? {}) as Json;
  const impact = (detail.impact ?? {}) as Json;
  const kind = detail.change_request.kind;
  if (detail.before === null) {
    return (
      <p className="text-sm text-[var(--ink-muted)]">
        Before and after are computed when submitted.
      </p>
    );
  }
  if (kind === "account_mapping_set") {
    return (
      <>
        <p className="mb-2 text-sm">
          Replaces{" "}
          {before.approved_version
            ? `approved version ${str(before.approved_version)}`
            : "the account mapping file"}{" "}
          ({str(before.entries)} accounts) with version {str(after.version)} ({str(after.entries)}{" "}
          accounts).
        </p>
        <AccountMappingChanges detail={detail} />
      </>
    );
  }
  if (kind === "record_override") {
    const runId = typeof impact.run_id === "string" ? impact.run_id : null;
    const key = str(before.natural_key);
    return (
      <>
        <p className="mb-2 text-sm">
          Record{" "}
          {runId && !key.startsWith("quarantine:") ? (
            <Link
              href={`/migrations/${migrationId}/records/${runId}/${encodeURIComponent(key)}`}
              className="font-mono underline"
            >
              {key}
            </Link>
          ) : (
            <span className="font-mono">{key}</span>
          )}
          {impact.amount ? (
            <>
              {" "}
              · entry size <Money value={str(impact.amount)} currency={str(impact.currency)} />
            </>
          ) : null}
          {impact.restores_row ? " · restores a source line, including its amounts" : null}
        </p>
        {"raw_text" in before ? (
          <BeforeAfter rows={[["Source text", before.raw_text, after.replacement_text]]} />
        ) : (
          <BeforeAfter rows={[[str(before.field), before.value, after.value]]} />
        )}
      </>
    );
  }
  if (kind === "column_mapping_set") {
    const fields = (impact.changed_fields ?? []) as string[];
    const beforeFields = (before.fields ?? {}) as Json;
    const afterFields = (after.fields ?? {}) as Json;
    return (
      <>
        <p className="mb-2 text-sm">
          {str(impact.dataset_name)}: approved version {str(before.approved_version)} →{" "}
          {str(after.approved_version)}; {fields.length} fields change.
        </p>
        <BeforeAfter rows={fields.map((f) => [f, beforeFields[f], afterFields[f]])} />
      </>
    );
  }
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
  return <BeforeAfter rows={keys.map((k) => [humanize(k), before[k], after[k]])} />;
}

/* ------------------------------------------------------------------ why review is closed */

/**
 * The API decides who may review; this only says, in plain words, why the viewer may not. Every
 * case is a deliberate control, not a failure: segregation of duties above all.
 */
function reviewControl(detail: Detail): { title: string; body: string } {
  const reason = detail.viewer.reason;
  const status = detail.change_request.status;
  if (detail.viewer.is_requester && reason.startsWith("requesters cannot review")) {
    return {
      title: "Segregation of duties: you proposed this change",
      body: "The person who proposes a correction to financial data never approves it. Each required role below has to be satisfied by somebody else. This is enforced by the server, so it holds however the page is reached.",
    };
  }
  if (reason.startsWith("this reviewer has already decided")) {
    return {
      title: "You have already recorded your decision",
      body: "One decision per reviewer, kept as written. Any remaining requirement has to be satisfied by another person.",
    };
  }
  if (reason.startsWith("the reviewer's role satisfies no outstanding requirement")) {
    return {
      title: "No outstanding requirement matches your role",
      body: "Approvals are recorded against named roles, not against people in general. Every requirement your role covers is already satisfied.",
    };
  }
  if (reason.startsWith("your role does not review change requests")) {
    return {
      title: "Your access here is read-only",
      body: "The full evidence is visible to everyone; approving is limited to the roles listed below.",
    };
  }
  return {
    title: `Review is closed: this change request is ${humanize(status).toLowerCase()}`,
    body: "Decisions are final once recorded. A different outcome needs a new change request, which goes through the same approvals.",
  };
}

/* ------------------------------------------------------------------ page */

export default async function ChangeRequestPage(
  props: PageProps<"/migrations/[migrationId]/change-requests/[changeId]">,
) {
  const { migrationId, changeId } = await props.params;
  const query = await props.searchParams;
  const detail = await apiGet<Detail>(`/api/v1/change-requests/${changeId}`);
  const change = detail.change_request;
  const open = ["draft", "submitted", "stale"].includes(change.status);
  const steps = lifecycle(detail, migrationId);
  const control = reviewControl(detail);
  const gloss = KIND_GLOSS[change.kind];
  return (
    <div className="max-w-[1280px]">
      <PageHeader
        title={`${change.key}: ${change.title}`}
        breadcrumbs={[
          { label: "Approvals", href: `/migrations/${migrationId}/approvals` },
          { label: change.key },
        ]}
        description={`${humanize(change.kind)} proposed by ${change.requested_by_name}.`}
      >
        <StatusChip status={change.status} />
      </PageHeader>
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <div className="mb-5">
        <Callout title="Financial data is never changed silently">
          Relay detects and investigates problems on its own, but it does not correct them on its
          own. A correction is proposed with evidence, approved by someone other than the person who
          proposed it, applied in a single transaction with its audit event, and then re-checked by
          a fresh deterministic run. The steps below say where this one stands.
        </Callout>
      </div>
      <Lifecycle steps={steps} />
      {change.status === "stale" ? (
        <div className="mb-5">
          <Callout tone="warning" title="What this change was based on has moved">
            This change was prepared against one specific version of the thing it edits. That
            version has since been replaced by another approved change, so applying this one now
            would silently undo the newer work. Relay will not apply it as it stands: propose it
            again from the current state.
          </Callout>
        </div>
      ) : null}

      {/* Who asked, and for what. Everything else on the page is evidence for this. */}
      <Panel emphasis className="mb-6 p-4">
        <MetaList
          columns={4}
          items={[
            { label: "Requested by", value: change.requested_by_name },
            {
              label: "Origin",
              value:
                change.origin === "ai_finding"
                  ? "Drafted from an AI finding, owned by the requester"
                  : "Proposed by an operator",
            },
            {
              label: "Submitted",
              value: change.submitted_at ? (
                <LocalTime value={change.submitted_at} />
              ) : (
                <span className="text-[var(--ink-subtle)]">not submitted</span>
              ),
            },
            {
              label: "Applied",
              value: change.applied_at ? (
                <LocalTime value={change.applied_at} />
              ) : (
                <span className="text-[var(--ink-subtle)]">not applied</span>
              ),
            },
          ]}
        />
      </Panel>

      <Section
        title="Justification"
        description="The reason of record. It is written into the audit trail when the change is submitted, and cannot be edited afterwards."
      >
        <Panel className="p-4">
          <p className="text-sm whitespace-pre-wrap">{change.justification || "—"}</p>
        </Panel>
      </Section>
      <Section
        title="What would change"
        description={gloss}
        actions={<ProvenanceBadge kind="derived" />}
      >
        <Panel className="p-4">
          <Diff detail={detail} migrationId={migrationId} />
        </Panel>
      </Section>
      <Section
        title="Approvals"
        description="Each role below has to be satisfied by a different person, and never by the requester. Segregation of duties is enforced by the API, not by hiding buttons."
      >
        <ul className="mb-3 space-y-1 text-sm" data-testid="requirements">
          {detail.requirements.map((requirement) => (
            <li key={requirement.index} className="flex flex-wrap items-center gap-2">
              <StatusChip
                status={requirement.satisfied_by ? "pass" : "pending"}
                label={requirement.satisfied_by ? "approved" : "waiting"}
              />
              {humanize(requirement.role)}
              {requirement.satisfied_by ? ` — ${requirement.satisfied_by}` : ""}
              {requirement.satisfied_by ? null : (
                <span className="text-xs text-[var(--ink-subtle)]">
                  outstanding: nobody in this role has approved
                </span>
              )}
            </li>
          ))}
        </ul>
        {detail.approvals.length > 0 ? (
          <ul className="mb-3 space-y-1 text-sm" data-testid="approvals">
            {detail.approvals.map((approval) => (
              <li key={approval.reviewer_user_id} className="flex flex-wrap items-baseline gap-2">
                <StatusChip
                  status={approval.decision === "approve" ? "pass" : "fail"}
                  label={approval.decision === "approve" ? "approved" : "rejected"}
                />
                <span className="font-medium">{approval.reviewer_name}</span>
                <span className="text-[var(--ink-muted)]">({humanize(approval.role)})</span>
                <span className="text-xs text-[var(--ink-subtle)]">
                  <LocalTime value={approval.decided_at} />
                </span>
                {approval.comment ? (
                  <span className="text-[var(--ink-muted)]">— {approval.comment}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
        {detail.viewer.can_review ? (
          <Panel className="p-4">
            <p className="mb-2 max-w-xl text-sm text-[var(--ink-muted)]">
              Approving records your name against one requirement. When it is the last one
              outstanding, the change is applied in a single transaction and a fresh run is
              requested straight away. Rejecting ends the change request and needs a comment.
            </p>
            {isPublicDemo() ? (
              <DemoUnavailable what="Approving or rejecting is the control this whole system exists for, and it is never the requester who does it." />
            ) : (
              <form action={reviewChangeRequest} className="flex max-w-xl flex-col gap-2">
                <input type="hidden" name="migrationId" value={migrationId} />
                <input type="hidden" name="changeId" value={change.id} />
                <TextArea name="comment" label="Comment (required to reject)" rows={2} />
                <span className="flex gap-2">
                  <SubmitButton name="decision" value="approve">
                    Approve
                  </SubmitButton>
                  <SubmitButton name="decision" value="reject" tone="danger">
                    Reject
                  </SubmitButton>
                </span>
              </form>
            )}
          </Panel>
        ) : (
          <div
            className="max-w-3xl rounded-[var(--radius-control)] border border-[var(--border)] bg-[var(--surface-sunken)] px-3 py-2 text-sm"
            data-testid="review-unavailable"
          >
            <p className="font-medium text-[var(--ink)]">{control.title}</p>
            <p className="mt-1 text-[var(--ink-muted)]">{control.body}</p>
            <p className="mt-1 text-xs text-[var(--ink-subtle)]">
              Reported by the API as: {detail.viewer.reason}.
            </p>
          </div>
        )}
        {detail.viewer.is_requester && change.status === "draft" ? (
          <div className="mt-3 max-w-2xl rounded-[var(--radius-control)] border border-[var(--accent)]/30 bg-[var(--accent-soft)] p-3">
            <p className="text-sm font-medium text-[var(--ink)]">Submit this for approval</p>
            <p className="mt-1 text-sm text-[var(--ink-muted)]">
              A draft changes nothing. Write why this correction is right — it becomes the reason of
              record in the audit trail — and send it to the people who must approve it.
              {change.origin === "ai_finding"
                ? " This draft came from an investigation, so the reasoning is yours to confirm before anyone reviews it."
                : ""}
            </p>
            {isPublicDemo() ? (
              <DemoUnavailable what="Submitting writes the justification into the audit trail, where it cannot be edited afterwards." />
            ) : (
              <form action={submitChangeRequest} className="mt-2 flex flex-col gap-2">
                <input type="hidden" name="migrationId" value={migrationId} />
                <input type="hidden" name="changeId" value={change.id} />
                <TextArea name="justification" label="Justification" required rows={3} />
                <span>
                  <SubmitButton>Submit for approval</SubmitButton>
                </span>
              </form>
            )}
          </div>
        ) : null}
        {detail.viewer.is_requester && open ? (
          isPublicDemo() ? (
            <DemoUnavailable what="Withdrawing is the requester's to do, and is itself recorded in the history." />
          ) : (
            <form action={withdrawChangeRequest} className="mt-3 flex items-end gap-2">
              <input type="hidden" name="migrationId" value={migrationId} />
              <input type="hidden" name="changeId" value={change.id} />
              <SubmitButton tone="secondary">Withdraw</SubmitButton>
              <span className="text-xs text-[var(--ink-subtle)]">
                Withdrawing is yours to do as the requester, and is itself recorded in the history.
              </span>
            </form>
          )
        ) : null}
      </Section>
      {detail.runs.length > 0 ? (
        <Section
          title="Verification after applying"
          description="Applying a change does not decide anything by itself. A fresh pipeline run re-ran every deterministic validation and reconciliation over the new inputs, and those results are what the readiness gates read."
        >
          <ul className="space-y-1 text-sm">
            {detail.runs.map((runId, index) => (
              <li key={runId}>
                <Link href={`/migrations/${migrationId}/runs/${runId}`}>
                  Run requested by this change{detail.runs.length > 1 ? ` (${index + 1})` : ""}
                </Link>{" "}
                <span className="font-mono text-xs text-[var(--ink-subtle)]">
                  {runId.slice(0, 8)}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      <Section
        title="History"
        description="Every step above as it was written to the hash-chained audit log."
      >
        <Panel>
          <ol className="divide-y divide-[var(--border)] text-sm" data-testid="history">
            {detail.history.map((event) => (
              <li key={event.id} className="flex flex-col gap-1 px-4 py-2.5 sm:flex-row sm:gap-4">
                <span className="shrink-0 text-xs tabular-nums text-[var(--ink-subtle)] sm:w-44">
                  <LocalTime value={event.occurred_at} />
                </span>
                <span className="min-w-0">
                  <span className="font-medium text-[var(--ink)]">{humanize(event.action)}</span>
                  {event.reason ? (
                    <span className="mt-0.5 block leading-relaxed text-[var(--ink-muted)]">
                      {event.reason}
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ol>
        </Panel>
      </Section>
    </div>
  );
}
