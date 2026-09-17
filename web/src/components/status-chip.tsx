/** Status with an icon and text, never color alone (product-spec.md §8.3). */
const STYLES: Record<string, { icon: string; className: string }> = {
  pass: { icon: "✓", className: "border-green-700 text-green-900 bg-green-50" },
  tied: { icon: "✓", className: "border-green-700 text-green-900 bg-green-50" },
  ready: { icon: "✓", className: "border-green-700 text-green-900 bg-green-50" },
  succeeded: { icon: "✓", className: "border-green-700 text-green-900 bg-green-50" },
  parsed: { icon: "✓", className: "border-green-700 text-green-900 bg-green-50" },
  passed: { icon: "✓", className: "border-green-700 text-green-900 bg-green-50" },
  matched: { icon: "✓", className: "border-green-700 text-green-900 bg-green-50" },
  resolved: { icon: "✓", className: "border-green-700 text-green-900 bg-green-50" },
  complete: { icon: "✓", className: "border-green-700 text-green-900 bg-green-50" },
  tied_with_explained_items: {
    icon: "✓",
    className: "border-green-700 text-green-900 bg-green-50",
  },
  explained: { icon: "✓", className: "border-green-700 text-green-900 bg-green-50" },
  fail: { icon: "✕", className: "border-red-700 text-red-900 bg-red-50" },
  failed: { icon: "✕", className: "border-red-700 text-red-900 bg-red-50" },
  errored: { icon: "✕", className: "border-red-700 text-red-900 bg-red-50" },
  not_ready: { icon: "✕", className: "border-red-700 text-red-900 bg-red-50" },
  discrepancy: { icon: "✕", className: "border-red-700 text-red-900 bg-red-50" },
  critical: { icon: "▲", className: "border-red-700 text-red-900 bg-red-50" },
  high: { icon: "▲", className: "border-orange-700 text-orange-900 bg-orange-50" },
  medium: { icon: "●", className: "border-yellow-700 text-yellow-900 bg-yellow-50" },
  low: { icon: "○", className: "border-gray-500 text-gray-800 bg-gray-50" },
  stale: { icon: "!", className: "border-amber-700 text-amber-900 bg-amber-50" },
  lapsed: { icon: "!", className: "border-amber-700 text-amber-900 bg-amber-50" },
  invalidated: { icon: "!", className: "border-amber-700 text-amber-900 bg-amber-50" },
  signed_off: { icon: "✓", className: "border-green-700 text-green-900 bg-green-50" },
  waived: { icon: "~", className: "border-blue-700 text-blue-900 bg-blue-50" },
  left_only: { icon: "←", className: "border-red-700 text-red-900 bg-red-50" },
  right_only: { icon: "→", className: "border-red-700 text-red-900 bg-red-50" },
  different: { icon: "≠", className: "border-red-700 text-red-900 bg-red-50" },
};

const NEUTRAL = { icon: "•", className: "border-gray-400 text-gray-800 bg-white" };

export function StatusChip({ status, label }: { status: string; label?: string }) {
  const style = STYLES[status] ?? NEUTRAL;
  const text = label ?? status.replaceAll("_", " ");
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-xs font-medium ${style.className}`}
      data-status={status}
    >
      <span aria-hidden="true">{style.icon}</span>
      {text}
    </span>
  );
}
