import Link from "next/link";

import { EvidenceLink } from "@/components/evidence-link";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";

export const dynamic = "force-dynamic";

export default async function ReadinessPage(
  props: PageProps<"/migrations/[migrationId]/readiness">,
) {
  const { migrationId } = await props.params;
  const readiness = await apiGet<Schemas["ReadinessOut"]>(
    `/api/v1/migrations/${migrationId}/readiness`,
  );
  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Readiness"
        description={
          readiness.run_id ? (
            <>
              Gates evaluated on the latest successful run{" "}
              <Link
                href={`/migrations/${migrationId}/runs/${readiness.run_id}`}
                className="underline"
              >
                (run details)
              </Link>
              . Unresolved exposure{" "}
              <Money value={readiness.unresolved_exposure} currency={readiness.currency} />.
            </>
          ) : (
            "No successful run yet."
          )
        }
      >
        <StatusChip
          status={readiness.overall}
          label={readiness.overall.replace("_", " ").toUpperCase()}
        />
      </PageHeader>
      <ol className="space-y-3">
        {readiness.gates.map((gate) => (
          <li
            key={gate.gate_id}
            id={gate.gate_id}
            className="rounded border border-gray-200 p-3 text-sm"
          >
            <p className="flex flex-wrap items-center gap-2">
              <StatusChip status={gate.status} label={`${gate.gate_id} ${gate.status}`} />
              <span className="font-medium">{gate.title}</span>
            </p>
            <p className="text-gray-700">{gate.summary}</p>
            <p>
              Observed: {gate.observed}. Threshold: {gate.threshold}.
            </p>
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
          </li>
        ))}
      </ol>
    </div>
  );
}
