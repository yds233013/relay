"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The workflow, in the order an implementation actually runs: bring the data in, look at what the
 * engine found, work the exceptions, govern the corrections, decide go-live. Grouping is for
 * legibility only — nothing is hidden behind a disclosure.
 */
const GROUPS: readonly (readonly [string, readonly (readonly [string, string])[]])[] = [
  ["", [["", "Overview"]]],
  [
    "Source data",
    [
      ["/setup", "Setup"],
      ["/data", "Data"],
      ["/mappings", "Mappings"],
    ],
  ],
  [
    "Engine results",
    [
      ["/runs", "Runs"],
      ["/validation", "Validation"],
      ["/reconciliation", "Reconciliation"],
    ],
  ],
  [
    "Exceptions",
    [
      ["/issues", "Issues"],
      ["/entities", "Entities"],
    ],
  ],
  [
    "Governance",
    [
      ["/approvals", "Approvals"],
      ["/overrides", "Overrides"],
      ["/audit", "Audit log"],
      ["/settings", "Settings"],
    ],
  ],
  ["Go-live", [["/readiness", "Readiness"]]],
];

export function MigrationNav({ migrationId }: { migrationId: string }) {
  const pathname = usePathname();
  const base = `/migrations/${migrationId}`;
  return (
    <nav aria-label="Migration" className="text-sm">
      {GROUPS.map(([group, items]) => (
        <div key={group || "root"} className="mb-4">
          {group ? (
            <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--ink-subtle)]">
              {group}
            </p>
          ) : null}
          <ul className="space-y-0.5">
            {items.map(([suffix, label]) => {
              const href = `${base}${suffix}`;
              const active = suffix === "" ? pathname === base : pathname.startsWith(href);
              return (
                <li key={label}>
                  <Link
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={`block rounded px-2 py-1 no-underline ${
                      active
                        ? "bg-white font-medium text-[var(--accent-ink)] shadow-[inset_2px_0_0_var(--accent)]"
                        : "text-[var(--ink)] hover:bg-white/70"
                    }`}
                  >
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
