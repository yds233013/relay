import Link from "next/link";

import { StatusChip } from "@/components/status-chip";

/**
 * Which run produced what is on this page. Evidence is only meaningful against the run that
 * produced it, and a reader who arrived by a deep link has no other way to tell.
 */
export function RunContext({
  base,
  runId,
  sequence,
  isCurrent,
}: {
  base: string;
  runId: string;
  sequence?: number | null;
  isCurrent: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="text-[var(--ink-muted)]">
        Evaluated on{" "}
        <Link href={`${base}/runs/${runId}`}>Run{sequence ? ` #${sequence}` : ""}</Link>
      </span>
      <StatusChip
        status={isCurrent ? "pass" : "stale"}
        label={isCurrent ? "current" : "stale: inputs changed since"}
      />
    </span>
  );
}
