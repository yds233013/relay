import Link from "next/link";

import { BusinessDate } from "@/components/dates";
import { PageHeader } from "@/components/page-header";
import { apiGet, type Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function DataPage(props: PageProps<"/migrations/[migrationId]/data">) {
  const { migrationId } = await props.params;
  const datasets = await apiGet<Schemas["DatasetOut"][]>(
    `/api/v1/migrations/${migrationId}/datasets`,
  );
  const imports = await Promise.all(
    datasets.map((dataset) =>
      apiGet<Schemas["ImportOut"][]>(`/api/v1/datasets/${dataset.id}/imports`),
    ),
  );
  return (
    <div className="max-w-6xl">
      <PageHeader title="Data" description="Datasets, their imports, and what could not be read." />
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">Datasets</caption>
        <thead>
          <tr className="border-b border-gray-300 text-xs uppercase tracking-wide text-gray-700">
            <th scope="col" className="px-2 py-1.5">
              Dataset
            </th>
            <th scope="col" className="px-2 py-1.5">
              Type
            </th>
            <th scope="col" className="px-2 py-1.5">
              As of
            </th>
            <th scope="col" className="px-2 py-1.5">
              Active import
            </th>
            <th scope="col" className="px-2 py-1.5 text-right">
              Rows
            </th>
            <th scope="col" className="px-2 py-1.5 text-right">
              Quarantined
            </th>
            <th scope="col" className="px-2 py-1.5 text-right">
              Imports
            </th>
          </tr>
        </thead>
        <tbody>
          {datasets.map((dataset, index) => {
            const history = imports[index] ?? [];
            const active = history.find((i) => i.id === dataset.active_import_id);
            return (
              <tr key={dataset.id} className="border-b border-gray-100">
                <td className="px-2 py-1.5 font-medium">{dataset.name}</td>
                <td className="px-2 py-1.5">{humanize(dataset.dataset_type)}</td>
                <td className="px-2 py-1.5">
                  <BusinessDate value={dataset.as_of_date} />
                </td>
                <td className="px-2 py-1.5">
                  {active ? (
                    <Link
                      href={`/migrations/${migrationId}/data/imports/${active.id}`}
                      className="text-blue-800 underline"
                    >
                      #{active.sequence} {active.original_filename}
                    </Link>
                  ) : (
                    <span className="text-gray-700">none</span>
                  )}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">{active?.row_count ?? "—"}</td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {active && (active.quarantined_count ?? 0) > 0 ? (
                    <Link
                      href={`/migrations/${migrationId}/data/imports/${active.id}#quarantine`}
                      className="font-medium text-red-900 underline"
                    >
                      {active.quarantined_count}
                    </Link>
                  ) : (
                    (active?.quarantined_count ?? "—")
                  )}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">{history.length}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
