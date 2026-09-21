"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Navigation follows the jobs an implementation operator does, not the modules behind them:
 * see where things stand, work the queue, check the data that came in, read what the automatic
 * checks found, govern the corrections, and decide go-live. Nothing is hidden behind a
 * disclosure — every route that existed before is still one click away.
 *
 * The active destination is a filled pill rather than a rail: a thin bar on the left edge is a
 * developer-tool idiom, and at fourteen destinations in five groups the eye needs a shape to land
 * on. No icons — there is no icon set in this app, and Unicode glyphs beside real words would be
 * decoration rather than help.
 *
 * Below `lg` the same markup reflows into one scrollable row of pills per group, above the
 * workspace instead of beside it. It stays one list of links in one `nav`, so nothing about it
 * depends on JavaScript and nothing is hidden behind a control a keyboard has to find — and five
 * short rows keep the first screenful of a phone for the work rather than for the menu.
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
        <div key={group || "root"} className="mb-1.5 last:mb-0 lg:mb-4">
          {group ? (
            <p className="mb-0.5 px-2.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--ink-subtle)] lg:mb-1.5">
              {group}
            </p>
          ) : null}
          <ul className="flex snap-x gap-1 overflow-x-auto pb-0.5 lg:block lg:space-y-0.5 lg:overflow-visible lg:pb-0">
            {items.map(([suffix, label]) => {
              const href = `${base}${suffix}`;
              const active = suffix === "" ? pathname === base : pathname.startsWith(href);
              return (
                <li key={label}>
                  <Link
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={`block whitespace-nowrap rounded-[var(--radius-control)] px-2.5 py-1.5 text-[13px] no-underline transition-colors ${
                      active
                        ? "bg-[var(--accent-soft)] font-semibold text-[var(--accent-ink)]"
                        : "text-[var(--ink-muted)] hover:bg-[var(--surface-sunken)] hover:text-[var(--ink)]"
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
