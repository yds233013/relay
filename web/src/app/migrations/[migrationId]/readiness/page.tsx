import Link from "next/link";

import { EvidenceLink } from "@/components/evidence-link";
import { SubmitButton, TextArea } from "@/components/forms";
import { LocalTime } from "@/components/local-time";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { Callout, Panel } from "@/components/ui";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { proposeSignoff, proposeWaiver } from "../workflow-actions";

export const dynamic = "force-dynamic";

export default async function ReadinessPage(
  props: PageProps<"/migrations/[migrationId]/readiness">,
) {
  const { migrationId } = await props.params;
  const query = await props.searchParams;
  const readiness = await apiGet<Schemas["ReadinessOut"]>(
    `/api/v1/migrations/${migrationId}/readiness`,
  );
  const prerequisitesMet =
    readiness.run_is_current &&
    readiness.gates.length > 0 &&
    readiness.gates.every((g) => g.gate_id === "G12" || g.status !== "fail");
  const signedOff = readiness.signoffs.some((s) => s.status === "active");
  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Readiness"
        description={
          readiness.run_id ? (
            <>
              Gates evaluated on run #{readiness.run_sequence}
              {readiness.evaluated_at ? (
                <>
                  {" "}
                  at <LocalTime value={readiness.evaluated_at} />
                </>
              ) : null}{" "}
              <Link
                href={`/migrations/${migrationId}/runs/${readiness.run_id}`}
                className="underline"
              >
                (run details)
              </Link>
              . Unresolved exposure{" "}
              <Money value={readiness.unresolved_exposure} currency={readiness.currency} />.
              Migration status:{" "}
              <span data-testid="migration-status">{humanize(readiness.migration_status)}</span>.
            </>
          ) : (
            "No successful run yet."
          )
        }
      >
        <span data-testid="readiness-overall">
          <StatusChip
            status={readiness.overall}
            label={readiness.overall.replace("_", " ").toUpperCase()}
          />
        </span>
      </PageHeader>
      <Notice error={param(query.error)} notice={param(query.notice)} />
      <Section
        title="Sign-off"
        description="The last gate. Sign-off is bound to this exact run: change an input and it lapses."
      >
        {signedOff ? (
          <Callout tone="positive" title="Signed off on this run">
            Any change to the inputs invalidates the sign-off, and the migration returns to not
            ready until it is signed again.
          </Callout>
        ) : prerequisitesMet ? (
          <form action={proposeSignoff} className="flex max-w-2xl flex-col gap-2">
            <input type="hidden" name="migrationId" value={migrationId} />
            <p className="text-sm">
              G1 to G11 pass or are waived on the current run. The implementation lead and the
              customer controller must both approve the sign-off.
            </p>
            <TextArea name="justification" label="Sign-off statement" required />
            <span>
              <SubmitButton>Request sign-off</SubmitButton>
            </span>
          </form>
        ) : (
          <div data-testid="signoff-unavailable">
            <Callout>
              Sign-off becomes available when G1 to G11 pass or are waived on the current run.
            </Callout>
          </div>
        )}
        {readiness.signoffs.length > 0 ? (
          <ul className="mt-2 space-y-1 text-sm" data-testid="signoffs">
            {readiness.signoffs.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2">
                <StatusChip status={s.status} /> <LocalTime value={s.created_at} />
                <Link
                  href={`/migrations/${migrationId}/change-requests/${s.change_request_id}`}
                  className="underline"
                >
                  approval
                </Link>
                {s.status === "invalidated" ? (
                  <span className="text-[var(--warning)]">(the inputs changed after sign-off)</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </Section>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--ink-muted)]">
        Gates
      </h2>
      <ol className="space-y-3">
        {readiness.gates.map((gate) => {
          const waiver = readiness.waivers.find(
            (w) => w.gate_id === gate.gate_id && w.status === "active",
          );
          return (
            <li
              key={gate.gate_id}
              id={gate.gate_id}
              className={`scroll-mt-4 rounded-md border bg-[var(--surface-raised)] p-3 text-sm ${
                gate.status === "fail"
                  ? "border-[var(--border)] border-l-4 border-l-[var(--critical)]"
                  : "border-[var(--border)]"
              }`}
              data-gate={gate.gate_id}
            >
              <p className="flex flex-wrap items-center gap-2">
                <StatusChip status={gate.status} label={`${gate.gate_id} ${gate.status}`} />
                <span className="font-medium text-[var(--ink)]">{gate.title}</span>
                {gate.waivable ? (
                  <span
                    className="rounded border border-[var(--border)] px-1 text-[10px] uppercase tracking-wide text-[var(--ink-subtle)]"
                    title="This gate can be waived for a named scope, with lead and controller approval."
                  >
                    waivable
                  </span>
                ) : null}
              </p>
              <p className="mt-0.5 text-[var(--ink-muted)]">{gate.summary}</p>
              <p className="mt-1.5 flex flex-wrap gap-x-6 gap-y-1">
                <span>
                  <span className="text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                    Observed{" "}
                  </span>
                  <span
                    className={
                      gate.status === "fail" ? "font-medium text-[var(--critical)]" : "font-medium"
                    }
                  >
                    {gate.observed}
                  </span>
                </span>
                <span>
                  <span className="text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                    Threshold{" "}
                  </span>
                  <span className="text-[var(--ink-muted)]">{gate.threshold}</span>
                </span>
              </p>
              {gate.status === "waived" && waiver ? (
                <p className="mt-1">
                  Waived, not passing: {waiver.reason}{" "}
                  <Link
                    href={`/migrations/${migrationId}/change-requests/${waiver.change_request_id}`}
                    className="underline"
                  >
                    approval
                  </Link>
                  . The waiver lapses if any waived amount changes.
                </p>
              ) : null}
              {gate.evidence_links.length > 0 ? (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs uppercase tracking-wide text-[var(--ink-subtle)]">
                    Evidence ({gate.evidence_links.length})
                  </summary>
                  <ul className="mt-1 space-y-0.5 border-l-2 border-[var(--border)] pl-3">
                    {gate.evidence_links.map((link, index) => (
                      <li key={`${gate.gate_id}-${index}`}>
                        <EvidenceLink migrationId={migrationId} link={link} />
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
              {gate.status === "fail" && gate.waivable && gate.scope && readiness.run_is_current ? (
                <details className="mt-2 rounded border border-[var(--border)] bg-[var(--surface-sunken)] p-2">
                  <summary className="cursor-pointer font-medium">Propose a waiver</summary>
                  <form action={proposeWaiver} className="mt-2 flex max-w-2xl flex-col gap-2">
                    <input type="hidden" name="migrationId" value={migrationId} />
                    <input type="hidden" name="gateId" value={gate.gate_id} />
                    <p className="text-xs text-[var(--ink-muted)]">
                      Covers exactly the {Object.keys(gate.scope).length} items failing now.
                    </p>
                    <TextArea name="justification" label="Why this gate can be waived" required />
                    <span>
                      <SubmitButton tone="secondary">Propose waiver</SubmitButton>
                    </span>
                  </form>
                </details>
              ) : null}
            </li>
          );
        })}
      </ol>
      {readiness.waivers.length > 0 ? (
        <div className="mt-6">
          <Section
            title="Waivers"
            description="A waiver covers exactly the items failing when it was granted, and lapses if they change."
          >
            <Panel className="divide-y divide-[var(--border)]">
              <ul data-testid="waivers">
                {readiness.waivers.map((w) => (
                  <li key={w.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                    <StatusChip status={w.status} />
                    <span className="font-medium">{w.gate_id}</span>
                    <span className="text-[var(--ink-muted)]">{w.reason}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          </Section>
        </div>
      ) : null}
    </div>
  );
}
