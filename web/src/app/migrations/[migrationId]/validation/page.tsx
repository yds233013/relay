import Link from "next/link";

import { DataTable } from "@/components/data-table";
import { Money } from "@/components/money";
import { PageHeader, Section } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, buildPath, type Schemas } from "@/lib/api/client";
import { param } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ValidationPage(
  props: PageProps<"/migrations/[migrationId]/validation">,
) {
  const { migrationId } = await props.params;
  const search = await props.searchParams;
  const base = `/migrations/${migrationId}`;
  const readiness = await apiGet<Schemas["ReadinessOut"]>(
    `/api/v1/migrations/${migrationId}/readiness`,
  );
  const runId = param(search.run) ?? readiness.run_id;
  if (!runId) {
    return <PageHeader title="Validation" description="No successful run yet." />;
  }
  const rule = param(search.rule);
  const cursor = param(search.cursor);
  const [rules, exceptions] = await Promise.all([
    apiGet<Schemas["RuleRunOut"][]>(`/api/v1/pipeline-runs/${runId}/rules`),
    apiGet<Schemas["Page_ExceptionOut_"]>(`/api/v1/pipeline-runs/${runId}/exceptions`, {
      rule_id: rule,
      cursor,
      limit: 100,
    }),
  ]);
  return (
    <div className="max-w-6xl">
      <PageHeader
        title="Validation"
        description="Rules evaluated on the run, and the findings they produced."
      />
      <Section title="Rules">
        <DataTable<Schemas["RuleRunOut"]>
          caption={`${rules.length} rules`}
          rows={rules}
          rowKey={(r) => r.rule_id}
          columns={[
            { header: "Rule", cell: (r) => <span className="font-mono text-xs">{r.rule_id}</span> },
            { header: "Title", cell: (r) => r.title },
            {
              header: "Status",
              cell: (r) => (
                <>
                  <StatusChip status={r.status} label={r.status.replace("_", " ")} />
                  {r.error ? <p className="text-xs text-red-900">{r.error}</p> : null}
                </>
              ),
            },
            {
              header: "Findings",
              align: "right",
              cell: (r) =>
                r.exception_count > 0 ? (
                  <Link
                    href={buildPath(`${base}/validation`, { run: runId, rule: r.rule_id })}
                    className="text-blue-800 underline"
                  >
                    {r.exception_count}
                  </Link>
                ) : (
                  "0"
                ),
            },
          ]}
        />
      </Section>
      <Section title={rule ? `Findings for ${rule}` : "All findings"}>
        <DataTable<Schemas["ExceptionOut"]>
          caption={`${exceptions.items.length} findings on this page`}
          rows={exceptions.items}
          rowKey={(e) => e.id}
          nextHref={
            exceptions.next_cursor
              ? buildPath(`${base}/validation`, {
                  run: runId,
                  rule,
                  cursor: exceptions.next_cursor,
                })
              : null
          }
          columns={[
            { header: "Severity", cell: (e) => <StatusChip status={e.severity} /> },
            { header: "Rule", cell: (e) => <span className="font-mono text-xs">{e.rule_id}</span> },
            { header: "Message", cell: (e) => e.message },
            {
              header: "Amount at risk",
              align: "right",
              cell: (e) => <Money value={e.amount_at_risk} currency={e.currency} />,
            },
            {
              header: "Issue",
              cell: (e) => (
                <Link
                  href={buildPath(`${base}/issues`, { fingerprint: e.fingerprint })}
                  className="text-blue-800 underline"
                >
                  view
                </Link>
              ),
            },
          ]}
        />
      </Section>
    </div>
  );
}
