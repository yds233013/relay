/**
 * Status with a glyph and text, never colour alone (product-spec.md §8.3).
 *
 * Chips are tinted fills rather than outlines: an outlined pill at this size reads as a form
 * control, and these are not clickable. Four semantic families carry every state in the product,
 * and the critical one is rationed — it means "this blocks go-live or a control did not tie",
 * not "this needs looking at". Lesser states take attention or neutral so that red keeps meaning
 * something when it appears.
 */
type Family = "critical" | "attention" | "positive" | "neutral" | "informational";

const FAMILY: Record<Family, string> = {
  critical: "bg-[var(--critical-soft)] text-[var(--critical)]",
  attention: "bg-[var(--warning-soft)] text-[var(--warning)]",
  positive: "bg-[var(--positive-soft)] text-[var(--positive)]",
  informational: "bg-[var(--accent-soft)] text-[var(--accent-ink)]",
  neutral:
    "bg-[var(--surface-sunken)] text-[var(--ink-muted)] ring-1 ring-inset ring-[var(--border)]",
};

const STYLES: Record<string, { icon: string; family: Family }> = {
  // Passed, tied, done.
  pass: { icon: "✓", family: "positive" },
  tied: { icon: "✓", family: "positive" },
  ready: { icon: "✓", family: "positive" },
  succeeded: { icon: "✓", family: "positive" },
  parsed: { icon: "✓", family: "positive" },
  passed: { icon: "✓", family: "positive" },
  matched: { icon: "✓", family: "positive" },
  resolved: { icon: "✓", family: "positive" },
  complete: { icon: "✓", family: "positive" },
  applied: { icon: "✓", family: "positive" },
  tied_with_explained_items: { icon: "✓", family: "positive" },
  explained: { icon: "✓", family: "positive" },
  signed_off: { icon: "✓", family: "positive" },

  // A control did not tie, or go-live is blocked.
  fail: { icon: "✕", family: "critical" },
  failed: { icon: "✕", family: "critical" },
  errored: { icon: "✕", family: "critical" },
  not_ready: { icon: "✕", family: "critical" },
  discrepancy: { icon: "✕", family: "critical" },
  critical: { icon: "▲", family: "critical" },
  left_only: { icon: "←", family: "critical" },
  right_only: { icon: "→", family: "critical" },
  different: { icon: "≠", family: "critical" },

  // Needs a person, but does not by itself stop a cutover.
  high: { icon: "▲", family: "attention" },
  medium: { icon: "●", family: "attention" },
  stale: { icon: "!", family: "attention" },
  lapsed: { icon: "!", family: "attention" },
  invalidated: { icon: "!", family: "attention" },
  rejected: { icon: "✕", family: "attention" },

  // Deliberate states an operator chose, rather than results.
  waived: { icon: "~", family: "informational" },
  submitted: { icon: "→", family: "informational" },
  running: { icon: "◴", family: "informational" },
  queued: { icon: "◴", family: "informational" },

  // Informational only.
  low: { icon: "○", family: "neutral" },
  superseded: { icon: "→", family: "neutral" },
  draft: { icon: "○", family: "neutral" },
  withdrawn: { icon: "○", family: "neutral" },
};

const NEUTRAL = { icon: "•", family: "neutral" as Family };

export function StatusChip({ status, label }: { status: string; label?: string }) {
  const style = STYLES[status] ?? NEUTRAL;
  const text = label ?? status.replaceAll("_", " ");
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${FAMILY[style.family]}`}
      data-status={status}
    >
      <span aria-hidden="true">{style.icon}</span>
      {text}
    </span>
  );
}
