"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Navigation follows the jobs an implementation operator does, not the modules behind them:
 * see where things stand, work the queue, check the data that came in, read what the automatic
 * checks found, govern the corrections, and decide go-live. Nothing is hidden behind a
 * disclosure — every route that existed before is still one click away.
 */
const GROUPS: readonly (readonly [string, readonly (readonly [string, string])[]])[] = [
  [
    "",
    [
      ["", "Overview"],
      ["/work", "Work queue"],
    ],
  ],
  [
    "Migration data",
    [
      ["/setup", "Setup"],
      ["/data", "Imported data"],
      ["/mappings", "Mappings"],
    ],
  ],
  [
    "Checks & reconciliation",
    [
      ["/runs", "Verification runs"],
      ["/validation", "Accounting checks"],
      ["/reconciliation", "Reconciliation"],
      ["/issues", "Issues"],
      ["/entities", "Duplicate parties"],
    ],
  ],
  [
    "Changes & approvals",
    [
      ["/approvals", "Approvals"],
      ["/overrides", "Applied corrections"],
    ],
  ],
  [
    "Go-live",
    [
      ["/readiness", "Readiness"],
      ["/audit", "Audit log"],
      ["/settings", "Policy"],
    ],
  ],
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
