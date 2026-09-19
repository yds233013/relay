import type { Schemas } from "@/lib/api/client";

/**
 * Readiness in an operator's language.
 *
 * The engine decides go-live with twelve gates, G1 to G12. They are precise and they are not how
 * anyone talks about an implementation. Each gate belongs to exactly one of the six questions
 * below; the gates themselves stay visible underneath for evidence and audit, and this file never
 * changes what any gate decided.
 */
export interface ReadinessCategory {
  readonly id: string;
  readonly title: string;
  /** The question this answers, in the words an implementation team would use. */
  readonly question: string;
  readonly gates: readonly string[];
}

export const READINESS_CATEGORIES: readonly ReadinessCategory[] = [
  {
    id: "data",
    title: "Data completeness",
    question: "Did everything arrive, readable, and is what we are looking at still current?",
    gates: ["G1", "G2", "G4"],
  },
  {
    id: "mapping",
    title: "Account mapping",
    question: "Does every legacy account land somewhere sensible in the new chart of accounts?",
    gates: ["G3"],
  },
  {
    id: "integrity",
    title: "Ledger integrity",
    question: "Does the migrated ledger still agree with the customer's own trial balance?",
    gates: ["G6"],
  },
  {
    id: "reconciliation",
    title: "Subledgers and cash",
    question: "Do receivables, payables and the bank agree with the ledger?",
    gates: ["G7", "G8"],
  },
  {
    id: "exceptions",
    title: "Open exceptions",
    question: "Has everything the checks flagged been resolved, dispositioned or decided?",
    gates: ["G5", "G9", "G10"],
  },
  {
    id: "signoff",
    title: "Approvals and sign-off",
    question: "Are all corrections approved, and has the customer signed off on this exact run?",
    gates: ["G11", "G12"],
  },
];

export type Gate = Schemas["GateOut"];

export interface GroupedCategory extends ReadinessCategory {
  readonly members: Gate[];
  /** `fail` when any member fails, `waived` when a member is waived and none fail, else `pass`. */
  readonly status: string;
  readonly failing: Gate[];
}

export function groupGates(gates: readonly Gate[]): GroupedCategory[] {
  const byId = new Map(gates.map((gate) => [gate.gate_id, gate]));
  const grouped = READINESS_CATEGORIES.map((category) => {
    const members = category.gates
      .map((id) => byId.get(id))
      .filter((gate): gate is Gate => gate !== undefined);
    const failing = members.filter((gate) => gate.status === "fail");
    const waived = members.some((gate) => gate.status === "waived");
    return {
      ...category,
      members,
      failing,
      status: failing.length > 0 ? "fail" : waived ? "waived" : "pass",
    };
  }).filter((category) => category.members.length > 0);

  // A gate this file does not know about must still be shown, not silently dropped.
  const known = new Set(READINESS_CATEGORIES.flatMap((category) => category.gates));
  const orphans = gates.filter((gate) => !known.has(gate.gate_id));
  if (orphans.length > 0) {
    const failing = orphans.filter((gate) => gate.status === "fail");
    grouped.push({
      id: "other",
      title: "Other checks",
      question: "Additional readiness conditions.",
      gates: orphans.map((gate) => gate.gate_id),
      members: orphans,
      failing,
      status: failing.length > 0 ? "fail" : "pass",
    });
  }
  return grouped;
}
