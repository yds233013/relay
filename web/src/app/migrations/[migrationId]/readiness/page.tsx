import Link from "next/link";

import { DemoUnavailable } from "@/components/demo-note";
import { EvidenceLink } from "@/components/evidence-link";
import { SubmitButton, TextArea } from "@/components/forms";
import { LocalTime } from "@/components/local-time";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { Callout, Panel } from "@/components/ui";
import { isPublicDemo } from "@/lib/demo";
import { groupGates } from "@/lib/readiness";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize, param } from "@/lib/format";

import { proposeSignoff, proposeWaiver } from "../workflow-actions";

export const dynamic = "force-dynamic";

/**
 * Gate states in the words an operator uses. "Fail" is the engine's word for a condition that is
 * not met; on this screen the question is what has to happen next, so it says so.
 */
const GATE_WORD: Record<string, string> = {
  pass: "passing",
  fail: "needs resolution",
  waived: "waived",
  not_applicable: "not evaluated",
};

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
  const categories = groupGates(readiness.gates);
  return (
    <div className="max-w-[1100px]">
      <PageHeader
        title="Can this customer go live?"
        description={
          readiness.run_id ? (
            <>
              Every check below was evaluated on run #{readiness.run_sequence}
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
              , against the inputs in effect at the time. Unresolved exposure{" "}
              <Money value={readiness.unresolved_exposure} currency={readiness.currency} />.
              Implementation status:{" "}
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
        description="The last step. Sign-off is bound to this exact run: change an input and it lapses."
      >
        {signedOff ? (
          <Callout tone="positive" title="Signed off on this run">
            Any change to the inputs invalidates the sign-off, and the migration returns to not
            ready until it is signed again.
          </Callout>
        ) : prerequisitesMet ? (
          isPublicDemo() ? (
            <DemoUnavailable what="Sign-off is the last step: the lead and the controller both sign against this exact run fingerprint, and it lapses the moment any input changes." />
          ) : (
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
          )
        ) : (
          <div data-testid="signoff-unavailable">
            <Callout>
              Sign-off becomes available once every other check passes or is waived on the current
              run. Until then, the work queue is where that happens.
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
      <Section
        title="What has to be true before go-live"
        description="Six questions, answered by twelve checks. Each check states what it observed and links to the evidence behind it."
      >
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {categories.map((category) => (
            <a
              key={category.id}
              href={`#${category.id}`}
              className={`block rounded-[var(--radius-card)] border bg-[var(--surface-raised)] px-3.5 py-3 no-underline shadow-[var(--shadow-card)] transition-colors hover:bg-[var(--surface-sunken)] ${
                category.status === "fail"
                  ? "border-[var(--critical)]/40"
                  : category.status === "waived"
                    ? "border-[var(--accent)]/40"
                    : "border-[var(--positive)]/40"
              }`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-[var(--ink)]">{category.title}</span>
                <span
                  className={`text-xs font-semibold ${
                    category.status === "fail"
                      ? "text-[var(--critical)]"
                      : category.status === "waived"
                        ? "text-[var(--accent-ink)]"
                        : "text-[var(--positive)]"
                  }`}
                >
                  {category.status === "fail"
                    ? `${category.failing.length} to resolve`
                    : category.status === "waived"
                      ? "waived"
                      : "clear"}
                </span>
              </span>
              <span className="mt-1 block text-xs leading-relaxed text-[var(--ink-muted)]">
                {category.question}
              </span>
            </a>
          ))}
        </div>
      </Section>

      {categories.map((category) => (
        <section key={category.id} id={category.id} className="mb-6 scroll-mt-4">
          <div className="mb-2.5">
            <h2 className="flex flex-wrap items-center gap-2 text-base font-semibold tracking-tight text-[var(--ink)]">
              <span
                aria-hidden="true"
                className={
                  category.status === "fail"
                    ? "text-[var(--critical)]"
                    : category.status === "waived"
                      ? "text-[var(--accent-ink)]"
                      : "text-[var(--positive)]"
                }
              >
                {category.status === "fail" ? "✕" : category.status === "waived" ? "~" : "✓"}
              </span>
              {category.title}
              <span className="font-mono text-[11px] font-normal text-[var(--ink-subtle)]">
                {category.members.map((gate) => gate.gate_id).join(" · ")}
              </span>
            </h2>
            <p className="mt-0.5 text-sm text-[var(--ink-muted)]">{category.question}</p>
          </div>
          <ol className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-card)] border border-[var(--border)] bg-[var(--surface-raised)] shadow-[var(--shadow-card)]">
            {category.members.map((gate) => {
              const waiver = readiness.waivers.find(
                (w) => w.gate_id === gate.gate_id && w.status === "active",
              );
              return (
                <li
                  key={gate.gate_id}
                  id={gate.gate_id}
                  className={`scroll-mt-4 p-4 text-sm ${
                    gate.status === "fail" ? "border-l-[3px] border-l-[var(--critical)]" : ""
                  }`}
                  data-gate={gate.gate_id}
                >
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-[var(--ink)]">{gate.title}</span>
                    <StatusChip
                      status={gate.status}
                      label={GATE_WORD[gate.status] ?? gate.status}
                    />
                    {gate.waivable ? (
                      <span
                        className="rounded-full bg-[var(--surface-sunken)] px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.06em] text-[var(--ink-subtle)]"
                        title="This gate can be waived for a named scope, with lead and controller approval."
                      >
                        waivable
                      </span>
                    ) : null}
                    <span className="ml-auto font-mono text-[11px] text-[var(--ink-subtle)]">
                      {gate.gate_id}
                    </span>
                  </p>
                  <p className="mt-1 leading-relaxed text-[var(--ink-muted)]">{gate.summary}</p>
                  <p className="mt-2 flex flex-wrap gap-x-6 gap-y-1">
                    <span>
                      <span className="text-xs uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
                        Observed{" "}
                      </span>
                      <span
                        className={
                          gate.status === "fail"
                            ? "font-medium text-[var(--critical)]"
                            : "font-medium"
                        }
                      >
                        {gate.observed}
                      </span>
                    </span>
                    <span>
                      <span className="text-xs uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
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
                      <summary className="text-xs uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
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
                  {gate.status === "fail" &&
                  gate.waivable &&
                  gate.scope &&
                  readiness.run_is_current ? (
                    <details className="mt-3 rounded-[var(--radius-control)] border border-[var(--border)] bg-[var(--surface-sunken)] p-3">
                      <summary className="font-medium">Propose a waiver</summary>
                      {isPublicDemo() ? (
                        <DemoUnavailable what="A waiver covers exactly the items failing now, needs a written reason and two approvals, and lapses as soon as a new one appears." />
                      ) : (
                        <form action={proposeWaiver} className="mt-2 flex max-w-2xl flex-col gap-2">
                          <input type="hidden" name="migrationId" value={migrationId} />
                          <input type="hidden" name="gateId" value={gate.gate_id} />
                          <p className="text-xs text-[var(--ink-muted)]">
                            Covers exactly the {Object.keys(gate.scope).length} items failing now.
                          </p>
                          <TextArea
                            name="justification"
                            label="Why this gate can be waived"
                            required
                          />
                          <span>
                            <SubmitButton tone="secondary">Propose waiver</SubmitButton>
                          </span>
                        </form>
                      )}
                    </details>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </section>
      ))}
      {readiness.waivers.length > 0 ? (
        <div className="mt-6">
          <Section
            title="Waivers"
            description="A waiver covers exactly the items failing when it was granted, and lapses if they change."
          >
            <Panel className="divide-y divide-[var(--border)]">
              <ul data-testid="waivers">
                {readiness.waivers.map((w) => (
                  <li key={w.id} className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm">
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
