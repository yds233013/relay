import Link from "next/link";

import { BusinessDate } from "@/components/dates";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { apiGet, type Schemas } from "@/lib/api/client";

export const dynamic = "force-dynamic";

export default async function PortfolioPage() {
  const migrations = await apiGet<Schemas["MigrationSummaryOut"][]>("/api/v1/migrations");
  return (
    <main className="mx-auto max-w-6xl p-4">
      <PageHeader
        title="Portfolio"
        description="Every migration's readiness on its latest run. Stale means inputs changed since."
      />
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">Migrations</caption>
        <thead>
          <tr className="border-b border-gray-300 text-xs uppercase tracking-wide text-gray-700">
            <th scope="col" className="px-2 py-1.5">
              Migration
            </th>
            <th scope="col" className="px-2 py-1.5">
              Readiness
            </th>
            <th scope="col" className="px-2 py-1.5 text-right">
              Failing gates
            </th>
            <th scope="col" className="px-2 py-1.5 text-right">
              Unresolved exposure
            </th>
            <th scope="col" className="px-2 py-1.5">
              Go-live
            </th>
            <th scope="col" className="px-2 py-1.5 text-right">
              Days to go-live
            </th>
          </tr>
        </thead>
        <tbody>
          {migrations.length === 0 ? (
            <tr>
              <td colSpan={6} className="px-2 py-3 text-gray-700">
                No migrations yet.
              </td>
            </tr>
          ) : (
            migrations.map((m) => (
              <tr key={m.id} className="border-b border-gray-100">
                <td className="px-2 py-1.5">
                  <Link
                    href={`/migrations/${m.id}`}
                    className="font-medium text-blue-800 underline"
                  >
                    {m.company_name}
                  </Link>
                  <span className="block text-xs text-gray-700">{m.name}</span>
                </td>
                <td className="px-2 py-1.5">
                  <StatusChip status={m.overall} />
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {m.failing_gate_count === null
                    ? "—"
                    : `${m.failing_gate_count} of ${m.gate_count}`}
                </td>
                <td className="px-2 py-1.5 text-right">
                  <Money value={m.unresolved_exposure} currency={m.functional_currency} />
                </td>
                <td className="px-2 py-1.5">
                  <BusinessDate value={m.go_live_date} />
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">{m.days_to_go_live}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </main>
  );
}
