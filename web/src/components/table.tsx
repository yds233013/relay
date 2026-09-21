/**
 * One operational table treatment for the whole product.
 *
 * Relay's tables are the evidence, so they stay dense — denser than a dashboard would be — and
 * earn their legibility from alignment and a sunken header rather than from air. Rows are
 * separated by hairlines, never by stripes: a zebra pattern competes with the row tints below,
 * which are the only colour that carries meaning here.
 *
 * Pages import these constants instead of retyping cell padding, so a table on the reconciliation
 * screen and a table on the audit screen are the same object.
 */

/** The table element itself. Always inside `TABLE_SCROLL`. */
export const TABLE = "w-full border-collapse text-left text-sm";

/**
 * Wide operational tables scroll inside their own container; the page never scrolls sideways.
 *
 * `relative` is load-bearing, not decoration. Overflow only clips an absolutely positioned
 * descendant when the scroller is that descendant's containing block, and these tables carry
 * `sr-only` labels — which Tailwind positions absolutely. Without it a visually hidden span in the
 * last column lands hundreds of pixels past the viewport and the whole page scrolls sideways on a
 * phone, with nothing visible out there to explain why.
 */
export const TABLE_SCROLL = "relative overflow-x-auto";

export const THEAD_ROW = "border-b border-[var(--border)] bg-[var(--surface-sunken)]";

export const TH =
  "px-3 py-2 text-xs font-semibold uppercase tracking-[0.06em] text-[var(--ink-subtle)]";

export const TH_RIGHT = `${TH} text-right`;

export const TR =
  "border-b border-[var(--border)] align-top transition-colors last:border-0 hover:bg-[var(--surface-sunken)]";

export const TD = "px-3 py-2.5";

export const TD_RIGHT = `${TD} text-right tabular-nums`;

/**
 * Row state, where the data already carries one. Tints are deliberately faint — a row that is
 * merely tinted must never look like a row that has been selected by the reader.
 */
export const ROW_TONE = {
  /** Keeps a readiness gate failing. */
  blocking: "bg-[var(--critical-soft)]/60",
  /** Needs a person, but does not block go-live. */
  review: "bg-[var(--warning-soft)]/70",
  /** The row the reader arrived on, or the one a filter is about. */
  selected: "bg-[var(--accent-soft)] shadow-[inset_3px_0_0_var(--accent)]",
} as const;
