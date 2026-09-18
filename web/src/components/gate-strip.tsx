import Link from "next/link";

import type { Schemas } from "@/lib/api/client";

/**
 * All twelve gates at a glance, in order, so the relationship between "NOT READY" and the
 * individual conditions is visible without reading a list. Never colour alone: each state carries
 * a glyph, and the gate id is always the label.
 */
type GateState = { glyph: string; className: string; word: string };

const NOT_APPLICABLE: GateState = {
  glyph: "–",
  className: "border-[var(--border)] bg-[var(--surface-sunken)] text-[var(--ink-subtle)]",
  word: "not applicable",
};

const STATE: Record<string, GateState> = {
  pass: {
    glyph: "✓",
    className: "border-[var(--positive)]/40 bg-[var(--positive-soft)] text-[var(--positive)]",
    word: "passing",
  },
  fail: {
    glyph: "✕",
    className: "border-[var(--critical)]/50 bg-[var(--critical-soft)] text-[var(--critical)]",
    word: "failing",
  },
  waived: {
    glyph: "~",
    className: "border-[var(--accent)]/40 bg-[var(--accent-soft)] text-[var(--accent-ink)]",
    word: "waived",
  },
  not_applicable: NOT_APPLICABLE,
};

export function GateStrip({ gates, base }: { gates: readonly Schemas["GateOut"][]; base: string }) {
  return (
    <ol className="flex flex-wrap gap-1" aria-label="Readiness gates">
      {gates.map((gate) => {
        const state = STATE[gate.status] ?? NOT_APPLICABLE;
        return (
          <li key={gate.gate_id}>
            <Link
              href={`${base}/readiness#${gate.gate_id}`}
              title={`${gate.gate_id} ${gate.title} — ${state.word}: ${gate.observed}`}
              aria-label={`${gate.gate_id} ${gate.title}, ${state.word}`}
              className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium no-underline ${state.className}`}
            >
              <span aria-hidden="true">{state.glyph}</span>
              {gate.gate_id}
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
