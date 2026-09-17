"""Compare a Relay engine result with the golden manifest (evaluation only).

Selectors in the manifest that do not name a natural key (a payment identified by its check number,
a quarantined record identified by its content, a bank line identified by date and amount) are
resolved here from the raw fixture files with the independent evaluation reader, never with engine
code.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal
from typing import Any, Protocol

from relay.engine.entities import Candidate
from relay.engine.exceptions import RuleException, Severity
from relay.engine.policy import Policy
from relay.engine.reconciliation import ReconLine, ReconResult
from relay_evaluation.brightwater.fixtures import Table, read_table
from relay_evaluation.brightwater.manifest import ExpectedIssue, Manifest
from relay_evaluation.brightwater.verify import VerificationReport

PAYMENTS = "ledgerpro/ledgerpro_payments.csv"
CUSTOMERS = "ledgerpro/ledgerpro_customers.csv"
VENDORS = "ledgerpro/ledgerpro_vendors.csv"
_DIRECTION = {"Receipt": "received", "Bill Payment": "disbursed"}

Predicate = Callable[[RuleException], bool]


class ResultLike(Protocol):
    """What the comparison reads: an in-memory engine result or one rebuilt from the database."""

    @property
    def exceptions(self) -> Sequence[RuleException]: ...

    @property
    def reconciliations(self) -> Sequence[ReconResult]: ...

    @property
    def candidates(self) -> Sequence[Candidate]: ...


class _Resolver:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.tables: dict[str, Table] = {
            path: read_table(path, content)
            for path, content in files.items()
            if path.endswith(".csv")
        }

    def _payment_keys(self, column: str, value: str) -> set[str]:
        return {
            f"pay:{_DIRECTION[row['Type']]}:{row['Payment No']}"
            for row in self.tables[PAYMENTS].rows
            if row[column].strip() == value
        }

    def party_codes_named(self, name: str) -> set[str]:
        codes = {
            row["Customer ID"]
            for row in self.tables[CUSTOMERS].rows
            if row["Customer Name"].strip() == name
        }
        codes |= {
            row["Vendor ID"]
            for row in self.tables[VENDORS].rows
            if row["Vendor Name"].strip() == name
        }
        return codes

    def subject(self, selector: object) -> Predicate:
        if isinstance(selector, str):
            return lambda e: selector in e.subjects
        if not isinstance(selector, dict):
            raise TypeError(f"unsupported selector {selector!r}")
        if "payments_file_reference" in selector:
            keys = self._payment_keys("Check/Ref No", selector["payments_file_reference"])
            return lambda e: len(keys) == 1 and bool(keys & set(e.subjects))
        if "payments_file_applied_to" in selector:
            keys = self._payment_keys("Applied To", selector["payments_file_applied_to"])
            return lambda e: len(keys) == 1 and bool(keys & set(e.subjects))
        if "quarantined_in" in selector:
            prefix = f"quarantine:{selector['quarantined_in']}:"
            needle = selector["contains"]
            return lambda e: (
                any(s.startswith(prefix) for s in e.subjects)
                and needle in str(e.details.get("raw_text", ""))
            )
        if "bank_posted" in selector:
            posted, amount = selector["bank_posted"], Decimal(selector["amount"])
            return lambda e: (
                any(s.startswith("bank:") and f":{posted}:" in s for s in e.subjects)
                and Decimal(str(e.details.get("amount"))) == amount
            )
        raise TypeError(f"unsupported selector {selector!r}")


def _issue_matches(resolver: _Resolver, expected: ExpectedIssue) -> Predicate:
    predicates = [resolver.subject(s) for s in expected.subjects]
    count = len(expected.subjects)
    return lambda e: (
        e.rule_id == expected.rule and len(e.subjects) == count and all(p(e) for p in predicates)
    )


def _describe(e: RuleException) -> str:
    return f"{e.rule_id} {list(e.subjects)} {e.severity.value} at_risk={e.amount_at_risk}"


def compare_issues(
    report: VerificationReport,
    resolver: _Resolver,
    expected: Iterable[tuple[str, ExpectedIssue]],
    actual: list[RuleException],
    label: str,
) -> None:
    remaining = [e for e in actual if not e.rule_id.startswith("RECON.")]
    for owner, issue in expected:
        matches = [e for e in remaining if _issue_matches(resolver, issue)(e)]
        name = f"{label} {owner} {issue.rule} {list(issue.subjects)}"
        if len(matches) != 1:
            report.record(name, False, f"expected exactly one matching issue, found {len(matches)}")
            continue
        found = matches[0]
        remaining.remove(found)
        problems = []
        if found.severity != Severity(issue.severity):
            problems.append(f"severity {found.severity.value} != {issue.severity}")
        if issue.amount_at_risk is not None and found.amount_at_risk != Decimal(
            issue.amount_at_risk
        ):
            problems.append(f"amount_at_risk {found.amount_at_risk} != {issue.amount_at_risk}")
        report.record(name, not problems, "; ".join(problems))
    report.record(
        f"{label} no unexpected issues",
        not remaining,
        "; ".join(_describe(e) for e in remaining[:20]),
    )


def _grain(resolver: _Resolver, grain: dict[str, str]) -> tuple[tuple[str, str], ...]:
    resolved = dict(grain)
    if "party_name" in resolved:
        codes = resolver.party_codes_named(resolved.pop("party_name"))
        resolved["party"] = next(iter(codes)) if len(codes) == 1 else f"ambiguous:{sorted(codes)}"
    return tuple(sorted(resolved.items()))


def _line_value(line: ReconLine, name: str) -> object:
    if name == "difference":
        return line.difference
    return line.extra.get(name)


def compare_reconciliations(
    report: VerificationReport, resolver: _Resolver, result: ResultLike, manifest: Manifest
) -> None:
    actual: dict[tuple[str, tuple[tuple[str, str], ...]], ReconLine] = {}
    by_id = {r.recon_id: r for r in result.reconciliations}
    for recon in result.reconciliations:
        for discrepancy in recon.discrepancies():
            actual[(recon.recon_id, tuple(sorted(discrepancy.grain)))] = discrepancy
    expected_keys = set()
    for spec in manifest.reconciliation_lines:
        line_key = (spec.recon, _grain(resolver, spec.grain))
        expected_keys.add(line_key)
        found = actual.get(line_key)
        if found is None:
            report.record(
                f"engine reconciliation {line_key}", False, "expected discrepancy not found"
            )
            continue
        problems = []
        for name, value in spec.values.items():
            expected_value = value if isinstance(value, int) else Decimal(str(value))
            if _line_value(found, name) != expected_value:
                problems.append(f"{name}: expected {value}, actual {_line_value(found, name)}")
        report.record(f"engine reconciliation {line_key}", not problems, "; ".join(problems))
    if manifest.reconciliation_exact:
        unexpected = sorted(set(actual) - expected_keys)
        report.record(
            "engine reconciliation exact set", not unexpected, f"unexpected: {unexpected[:10]}"
        )
    recon_issues = sum(1 for e in result.exceptions if e.rule_id.startswith("RECON."))
    report.record(
        "engine reconciliation issues match discrepancy lines",
        recon_issues == len(actual),
        f"{recon_issues} vs {len(actual)}",
    )

    totals = manifest.reconciliation_totals
    if "R3_total_difference" in totals:
        total = sum((line.difference for line in by_id["R3"].lines), Decimal(0))
        report.record(
            "engine R3 total difference",
            total == Decimal(totals["R3_total_difference"]),
            str(total),
        )
    for recon_id in ("R3o", "R4o"):
        total_key = f"{recon_id}_difference"
        if total_key in totals:
            value = sum((line.difference for line in by_id[recon_id].lines), Decimal(0))
            report.record(f"engine {total_key}", value == Decimal(totals[total_key]), str(value))

    r5 = by_id["R5"]
    if len(r5.lines) != 1:
        report.record("engine R5 single bank account line", False, str(len(r5.lines)))
        return
    line = r5.lines[0]
    expected = manifest.r5
    for name, value in (
        ("gl_balance", line.left),
        ("bank_balance", line.right),
        ("difference", line.difference),
        ("unexplained", line.unexplained),
    ):
        report.record(f"engine R5 {name}", value == Decimal(expected[name]), str(value))
    for name, classification in (
        ("outstanding_checks", "outstanding_check"),
        ("deposits_in_transit", "deposit_in_transit"),
        ("bank_only_activity", "bank_only_activity"),
    ):
        items = [i for i in line.items if i.classification == classification]
        total = sum((i.amount for i in items), Decimal(0))
        ok = len(items) == expected[name]["count"] and total == Decimal(expected[name]["total"])
        report.record(f"engine R5 {name}", ok, f"count {len(items)} total {total}")


def compare_candidates(
    report: VerificationReport, result: ResultLike, manifest: Manifest, policy: Policy
) -> None:
    actual = {(c.party_type.value, tuple(sorted(c.members))): c for c in result.candidates}
    expected_keys = set()
    for defect in manifest.defects:
        for candidate in defect.expected_candidates:
            key = (candidate["party_type"], tuple(sorted(candidate["members"])))
            expected_keys.add(key)
            found = actual.get(key)
            if found is None:
                report.record(f"engine candidate {key}", False, "not found")
                continue
            strength = "strong" if found.score >= policy.entity_strong_threshold else "below_strong"
            report.record(
                f"engine candidate {key}", strength == candidate["strength"], f"score {found.score}"
            )
    unexpected = sorted(set(actual) - expected_keys)
    report.record("engine candidates exact set", not unexpected, str(unexpected))


def compare_traps(
    report: VerificationReport,
    resolver: _Resolver,
    result: ResultLike,
    manifest: Manifest,
    policy: Policy,
    *,
    allowed: Iterable[tuple[str, ExpectedIssue]] = (),
) -> None:
    allowed_predicates = [_issue_matches(resolver, issue) for _, issue in allowed]
    for trap in manifest.traps:
        for rule_id in trap.silent_rules:
            noisy = [
                e
                for e in result.exceptions
                if e.rule_id == rule_id and not any(p(e) for p in allowed_predicates)
            ]
            report.record(
                f"engine trap {trap.id} silent {rule_id}",
                not noisy,
                "; ".join(_describe(e) for e in noisy[:5]),
            )
        names: list[str] = trap.extra.get("no_strong_candidate", [])
        if names:
            codes = set().union(*(resolver.party_codes_named(n) for n in names))
            strong = [
                c
                for c in result.candidates
                if set(c.members) <= codes and c.score >= policy.entity_strong_threshold
            ]
            report.record(
                f"engine trap {trap.id} no strong candidate",
                len(codes) == len(names) and not strong,
                str(strong),
            )
            if trap.extra.get("no_high_duplicate_issue"):
                high = [
                    e
                    for e in result.exceptions
                    if e.rule_id == "PARTY.UNRESOLVED_DUPLICATE_CANDIDATE"
                    and e.severity is Severity.HIGH
                    and {s.rsplit(":", 1)[1] for s in e.subjects} <= codes
                ]
                report.record(f"engine trap {trap.id} no high duplicate issue", not high, str(high))


def compare_run1(
    result: ResultLike, files: dict[str, bytes], manifest: Manifest, policy: Policy | None = None
) -> VerificationReport:
    """Run #1: exact issues, reconciliation discrepancies, candidates and trap silence."""
    policy = policy or Policy()
    report = VerificationReport()
    resolver = _Resolver(files)
    expected = [(d.id, issue) for d in manifest.defects for issue in d.expected_issues]
    compare_issues(report, resolver, expected, list(result.exceptions), "engine run1")
    compare_reconciliations(report, resolver, result, manifest)
    compare_candidates(report, result, manifest, policy)
    compare_traps(report, resolver, result, manifest, policy)
    return report


def expected_after_resolution(manifest: Manifest) -> list[tuple[str, ExpectedIssue]]:
    return [(d.id, issue) for d in manifest.defects for issue in d.expected_issues_after_resolution]


def check_issues_present(
    report: VerificationReport,
    result: ResultLike,
    files: dict[str, bytes],
    expected: Iterable[tuple[str, ExpectedIssue]],
    label: str,
) -> None:
    """Each expected issue is present exactly once with its severity and amount (no exact set)."""
    resolver = _Resolver(files)
    for owner, issue in expected:
        matches = [e for e in result.exceptions if _issue_matches(resolver, issue)(e)]
        problems: list[str] = []
        if len(matches) != 1:
            problems.append(f"found {len(matches)} matching issues")
        else:
            found = matches[0]
            if found.severity != Severity(issue.severity):
                problems.append(f"severity {found.severity.value} != {issue.severity}")
            if issue.amount_at_risk is not None and found.amount_at_risk != Decimal(
                issue.amount_at_risk
            ):
                problems.append(f"amount_at_risk {found.amount_at_risk} != {issue.amount_at_risk}")
        report.record(
            f"{label} {owner} {issue.rule} {list(issue.subjects)}",
            not problems,
            "; ".join(problems),
        )


def resolver_for(files: dict[str, bytes]) -> Any:
    return _Resolver(files)
