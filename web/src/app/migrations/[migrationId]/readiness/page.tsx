import Link from "next/link";

import { EvidenceLink } from "@/components/evidence-link";
import { SubmitButton, TextArea } from "@/components/forms";
import { LocalTime } from "@/components/local-time";
import { Money } from "@/components/money";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
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
      <Section title="Sign-off">
        {signedOff ? (
          <p className="text-sm">
            Signed off on this run. Any change to the inputs invalidates the sign-off.
          </p>
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
          <p className="text-sm text-gray-700" data-testid="signoff-unavailable">
            Sign-off becomes available when G1 to G11 pass or are waived on the current run.
          </p>
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
                {s.status === "invalidated" ? "(the inputs changed after sign-off)" : null}
              </li>
            ))}
          </ul>
        ) : null}
      </Section>
      <ol className="space-y-3">
        {readiness.gates.map((gate) => {
          const waiver = readiness.waivers.find(
            (w) => w.gate_id === gate.gate_id && w.status === "active",
          );
          return (
            <li
              key={gate.gate_id}
              id={gate.gate_id}
              className="rounded border border-gray-200 p-3 text-sm"
              data-gate={gate.gate_id}
            >
              <p className="flex flex-wrap items-center gap-2">
                <StatusChip status={gate.status} label={`${gate.gate_id} ${gate.status}`} />
                <span className="font-medium">{gate.title}</span>
                {gate.waivable ? <span className="text-xs text-gray-700">waivable</span> : null}
              </p>
              <p className="text-gray-700">{gate.summary}</p>
              <p>
                Observed: {gate.observed}. Threshold: {gate.threshold}.
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
                <details className="mt-1">
                  <summary className="cursor-pointer text-blue-800 underline">
                    Evidence ({gate.evidence_links.length})
                  </summary>
                  <ul className="mt-1 list-inside list-disc">
                    {gate.evidence_links.map((link, index) => (
                      <li key={`${gate.gate_id}-${index}`}>
                        <EvidenceLink migrationId={migrationId} link={link} />
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
              {gate.status === "fail" && gate.waivable && gate.scope && readiness.run_is_current ? (
                <details className="mt-2">
                  <summary className="cursor-pointer underline">Propose a waiver</summary>
                  <form action={proposeWaiver} className="mt-2 flex max-w-2xl flex-col gap-2">
                    <input type="hidden" name="migrationId" value={migrationId} />
                    <input type="hidden" name="gateId" value={gate.gate_id} />
                    <p className="text-xs text-gray-700">
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
        <Section title="Waivers">
          <ul className="space-y-1 text-sm" data-testid="waivers">
            {readiness.waivers.map((w) => (
              <li key={w.id}>
                <StatusChip status={w.status} /> {w.gate_id}: {w.reason}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}
