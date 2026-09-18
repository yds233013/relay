/**
 * One sentence per control, so the reconciliation screen can be read without the specification
 * open. These mirror `docs/validation-and-reconciliation.md` §B; the amounts, labels and statuses
 * all come from the engine — only the explanation lives here.
 */
const GLOSS: Record<string, string> = {
  R1: "The customer's own trial balance against the general ledger detail Relay staged. Anything the ledger lost, gained or dated differently shows up per account and period.",
  R2: "The same balances carried through the account mapping. It answers a different question from R1: not 'is the ledger complete' but 'does it still tie after being mapped onto the new chart of accounts'.",
  R3: "Accounts receivable: the GL control account against the open invoices staged from the subledger, by customer.",
  R3b: "The same receivables at document grain — the customer's aging report against staged open items, invoice by invoice.",
  R3o: "Receivables at the opening balance date: the opening aging against the opening trial balance.",
  R4: "Accounts payable: the GL control account against staged open bills, by vendor.",
  R4b: "Payables at document grain — the aging report against staged open items, bill by bill.",
  R4o: "Payables at the opening balance date.",
  R5: "Cash: the general ledger cash account against the bank statement, with timing differences identified item by item.",
  R6: "Row counts and totals: every line in the source export against every line Relay staged, including rows that could not be parsed.",
};

const PURPOSE: Record<string, string> = {
  completeness: "Nothing was lost between the legacy system and Relay",
  fidelity: "What was carried across still means the same thing",
};

export function reconciliationGloss(reconId: string): string | undefined {
  return GLOSS[reconId];
}

export function PurposeBadge({ purpose }: { purpose: string }) {
  const hint = PURPOSE[purpose];
  return (
    <span
      className="inline-flex items-center rounded border border-[var(--border)] bg-[var(--surface-sunken)] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--ink-muted)]"
      title={hint}
    >
      {purpose}
    </span>
  );
}
