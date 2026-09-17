# 0001 — Money representation

Status: **Accepted (M0).** Implemented in `backend/src/relay/core/money.py`, `currency.py`, `db_types.py`.

Requirements: FC-01 – FC-05 in [security-and-correctness.md](../security-and-correctness.md).

## Context

The planning documents fix the broad rules (Decimal, `NUMERIC(20,4)`, strings in JSON, `ROUND_HALF_UP` only for FX, debit-positive sign convention). Building the primitives exposed ambiguities the documents did not settle. Each was resolved toward the safest behavior for financial correctness.

## Decisions

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | What inputs construct an amount? | `Decimal` (finite), `int`, or a **strict** decimal string (`-?(0\|[1-9]\d*)(\.\d+)?`). `float` and `bool` are rejected. | Floats are lossy. `bool` is an `int` subclass and `Money(True, ...)` is always a bug. Strict strings forbid exponents, `+`, separators, whitespace and leading zeros, so the API has exactly one textual form. |
| 2 | What happens when a value exceeds the storage envelope (more than 4 decimal places, or \|value\| ≥ 10¹⁶)? | **Raise** `AmountOutOfRangeError`. | PostgreSQL silently rounds `NUMERIC(20,4)` input (`1.23456` → `1.2346`). Rounding to fit would alter source data (FC-02). An integration test proves the database behavior and that `AmountType` prevents it. |
| 3 | Amount has more decimals than the currency's minor units but fits the envelope (e.g. `12.345 USD`)? | **Preserve** it; `Money.has_sub_minor_precision` is `True`. | Legacy exports contain such values. Rejecting them loses evidence; rounding them changes source data. Rules in later milestones flag them. |
| 4 | How do equal amounts serialize? | Canonical scale = max(currency minor units, smallest exact scale). `12.5`, `12.50`, `12.5000` USD all serialize as `"12.50"`. Negative zero becomes zero. | Deterministic serialization is required for hashing and fingerprints. |
| 5 | Arithmetic precision | Operations run in a private decimal context (precision 60) that **traps** `Inexact`, `Rounded`, `Overflow` etc., independent of the ambient thread context. | A lossy operation raises instead of rounding. Code that changes the global decimal context cannot affect Money. |
| 6 | Which operators exist? | `+`, `-`, unary `-`, `abs`, ordering, equality. **No** `*` or `/`. `sum()` is rejected; `sum_money(values, currency)` requires a currency. | Multiplication and division are where rounding hides. The only multiplication is `convert()` (FX), which rounds explicitly. An empty sum must still have a currency (FC-04). |
| 7 | Mixed currencies | `+`, `-`, `<`, `<=`, `>`, `>=` raise `CurrencyMismatchError`. `==` returns `False`. Operators are typed as accepting `Money` only, so mypy rejects `money + 1.5`. | Raising from `==` would break sets and dicts. Returning `False` is correct: 1 USD is not 1 EUR. |
| 8 | Truthiness | `bool(money)` raises `TypeError`. | `if amount:` is ambiguous (zero? present?). Use `is_zero()`. |
| 9 | FX rounding | `convert(source, rate, target)` multiplies exactly, then rounds `ROUND_HALF_UP` (half away from zero, symmetric for negatives) to the **target** minor units. It returns the exact product and the rounding difference. Same-currency conversion is rejected. Rates: positive, ≤ 10 decimal places, < 10¹⁰ (`NUMERIC(20,10)`). | Reporting the rounding difference means rounding can always be explained in reconciliations. A same-currency "conversion" can only hide a mapping error. |
| 10 | Tolerance | `within_tolerance(diff, tol)` compares `|diff| <= tol` exactly. Negative tolerance is rejected. | FC-03. `0.0101` is outside a `0.01` tolerance even though it rounds to `0.01`. |
| 11 | Debit/credit columns | `signed_ledger_amount(debit, credit)`: both missing → error; a missing side is zero; negative values in either column → error; both non-zero → error. Result is debit − credit. | FC-05. The sign is carried by the column, so a negative debit is ambiguous. |
| 12 | Parsing source text | `parse_amount_text(text, AmountFormat)` requires a declared decimal separator, optional thousands separator (grouping validated in threes), whether parentheses mean negative, and allowed currency symbols. Empty text is an error, not zero. | No locale guessing. `1.234,56` under a US format is rejected, not misread. Whether an empty cell means zero or missing is a mapping decision (M2). |
| 13 | Currencies | Active ISO 4217 codes only, upper-case, from a static table. Fund codes, precious metals and test codes (`XAU`, `XDR`, `XTS`, `XXX`, …) are rejected. | These are not valid transaction currencies for accounting records. |

## Consequences

- Money never rounds implicitly anywhere in Python or at the database boundary.
- Callers must handle `AmountOutOfRangeError` for data that does not fit; later milestones turn this into a normalization exception rather than dropping or rounding the value.
- Display formatting (for example, rounding `12.345` for a UI) is a presentation concern. It is not implemented in M0 and must never feed back into stored values.
