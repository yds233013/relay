import Link from "next/link";

import { apiGet, type Schemas } from "@/lib/api/client";

const SECTIONS = [
  ["", "Overview"],
  ["/setup", "Setup"],
  ["/data", "Data"],
  ["/mappings", "Mappings"],
  ["/runs", "Runs"],
  ["/validation", "Validation"],
  ["/reconciliation", "Reconciliation"],
  ["/issues", "Issues"],
  ["/entities", "Entities"],
  ["/approvals", "Approvals"],
  ["/overrides", "Overrides"],
  ["/readiness", "Readiness"],
  ["/audit", "Audit log"],
] as const;

export default async function MigrationLayout(props: LayoutProps<"/migrations/[migrationId]">) {
  const { migrationId } = await props.params;
  const migration = await apiGet<Schemas["MigrationOut"]>(`/api/v1/migrations/${migrationId}`);
  return (
    <div className="flex min-h-[calc(100vh-41px)]">
      <nav aria-label="Migration" className="w-48 shrink-0 border-r border-gray-200 bg-gray-50 p-3">
        <p className="mb-3 text-sm">
          <span className="block font-semibold text-gray-900">{migration.company_name}</span>
          <span className="text-xs text-gray-700">{migration.name}</span>
        </p>
        <ul className="space-y-1 text-sm">
          {SECTIONS.map(([suffix, label]) => (
            <li key={label}>
              <Link
                href={`/migrations/${migrationId}${suffix}`}
                className="block rounded px-2 py-1 text-gray-900 hover:bg-gray-200"
              >
                {label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <main className="min-w-0 flex-1 p-4">{props.children}</main>
    </div>
  );
}
