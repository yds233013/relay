import Link from "next/link";

import type { Schemas } from "@/lib/api/client";

/** One piece of gate evidence, linked to the issue or reconciliation line it names. */
export function EvidenceLink({
  migrationId,
  link,
}: {
  migrationId: string;
  link: Schemas["EvidenceLinkOut"];
}) {
  if (link.kind === "issue" && link.issue_id) {
    return (
      <Link
        href={`/migrations/${migrationId}/issues/${link.issue_id}`}
        className="text-blue-800 underline"
      >
        {link.label}
      </Link>
    );
  }
  if (link.kind === "reconciliation_line" && link.line_id) {
    return (
      <Link
        href={`/migrations/${migrationId}/reconciliation/lines/${link.line_id}`}
        className="font-mono text-xs text-blue-800 underline"
      >
        {link.label}
      </Link>
    );
  }
  if (link.kind === "entity_candidate") {
    return (
      <span className="font-mono text-xs">
        {link.label} <span className="text-gray-700">(duplicate candidate)</span>
      </span>
    );
  }
  return <span className="font-mono text-xs">{link.label}</span>;
}
