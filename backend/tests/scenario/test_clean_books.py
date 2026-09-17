"""Clean Brightwater books satisfy the accounting invariants (M1 acceptance criterion 1)."""

from __future__ import annotations

import copy
import dataclasses
from collections import Counter
from datetime import date
from decimal import Decimal
from itertools import pairwise

import pytest

from relay.canonical.enums import AgingType, PaymentDirection
from relay_evaluation.brightwater.oracle import Oracle
from relay_scenarios.brightwater import controls
from relay_scenarios.brightwater.checks import (
    CLEAN_BOOK_CHECKS,
    run_clean_book_checks,
    verify_clean_books,
)
from relay_scenarios.brightwater.clean import build_clean_universe
from relay_scenarios.brightwater.scenario import Scenario
from relay_scenarios.brightwater.universe import LegacyUniverse
from relay_scenarios.errors import BooksInvariantError


@pytest.mark.parametrize("check_name", sorted(CLEAN_BOOK_CHECKS))
def test_clean_books_invariant(clean_universe: LegacyUniverse, check_name: str) -> None:
    assert CLEAN_BOOK_CHECKS[check_name](clean_universe) == []


def test_clean_books_reconcile_exactly(clean_scenario: Scenario) -> None:
    oracle = Oracle(clean_scenario.files)
    assert oracle.all_lines() == []
    r5 = oracle.r5()
    assert r5["gl_balance"] == Decimal("427768.68")
    assert r5["bank_balance"] == Decimal("442234.43")
    assert r5["unexplained"] == 0
    assert r5["bank_only_activity"] == {"count": 0, "total": Decimal(0)}


def test_clean_trial_balance_sums_to_zero_every_period(clean_universe: LegacyUniverse) -> None:
    totals: dict[date, Decimal] = Counter()  # type: ignore[assignment]
    for line in controls.trial_balance(clean_universe):
        totals[line.period_end] += line.balance.amount
    assert len(totals) == 7
    assert all(total == 0 for total in totals.values())


def test_opening_agings_tie_to_opening_trial_balance(clean_universe: LegacyUniverse) -> None:
    opening = clean_universe.plan.opening_balance_date
    ar = controls.aging_total(controls.aging(clean_universe, AgingType.AR, opening))
    ap = controls.aging_total(controls.aging(clean_universe, AgingType.AP, opening))
    assert ar == clean_universe.opening_balances["1200"] > 0
    assert -ap == clean_universe.opening_balances["2000"] < 0


def test_carried_forward_documents_explain_opening_balances(clean_universe: LegacyUniverse) -> None:
    carried = [n for n, info in clean_universe.invoice_info.items() if info.carried_forward]
    assert carried
    assert all(
        clean_universe.invoices[n].document_date <= clean_universe.plan.opening_balance_date
        for n in carried
    )
    opening = clean_universe.plan.opening_balance_date
    total = sum(
        (
            controls.open_amount(clean_universe, clean_universe.invoices[n], opening)
            for n in carried
        ),
        Decimal(0),
    )
    assert total == clean_universe.opening_balances["1200"]
    applied_to_carried = {
        a.document_number
        for p in clean_universe.payments.values()
        if p.direction is PaymentDirection.RECEIVED
        for a in p.applications
        if a.document_number in set(carried)
    }
    assert applied_to_carried, "H1 receipts must apply to carried-forward invoices"


def test_identifier_order_and_business_date_order_can_disagree(
    clean_universe: LegacyUniverse,
) -> None:
    """SC-05: identifiers establish identity; business dates establish chronology."""
    invoices = sorted(clean_universe.invoices.values(), key=lambda d: int(d.number.split("-")[1]))
    inversions = sum(1 for a, b in pairwise(invoices) if a.document_date > b.document_date)
    assert inversions > 0
    bills = sorted(clean_universe.bills.values(), key=lambda d: int(d.number.split("-")[1]))
    assert any(a.document_date > b.document_date for a, b in pairwise(bills))
    assert (
        clean_universe.bills["B-20931"].document_date
        < clean_universe.bills["B-20455"].document_date
    )


def test_inactive_historical_customers_have_no_activity(clean_universe: LegacyUniverse) -> None:
    inactive = {c for c, p in clean_universe.customers.items() if not p.is_active}
    assert len(inactive) > 150
    referenced = {d.party_code for d in clean_universe.invoices.values()} | {
        p.party_code for p in clean_universe.payments.values()
    }
    assert not inactive & referenced


def test_scenario_volume_is_coherent(clean_universe: LegacyUniverse) -> None:
    u = clean_universe
    h1_invoices = [n for n, i in u.invoice_info.items() if not i.carried_forward]
    assert 800 <= len(h1_invoices) <= 1000
    assert 1200 <= len(u.bills) <= 1500
    assert 160 <= sum(1 for c in u.customers.values() if c.is_active) <= 190
    assert 90 <= len(u.vendors) <= 100
    revenue = -sum(
        (
            line.functional_amount.amount
            for e in u.journals.values()
            for line in e.lines
            if line.account_code in {"4000", "4010", "4100"}
        ),
        Decimal(0),
    )
    assert Decimal("10000000") < revenue < Decimal("13000000")  # ~ $24M a year
    assert Decimal("250000") < u.opening_balances["1010"] < Decimal("700000")


@pytest.mark.parametrize("seed", [7, 424242])
def test_clean_invariants_hold_for_other_seeds(seed: int) -> None:
    universe = build_clean_universe(seed, verify=False)
    violations = {
        name: problems for name, problems in run_clean_book_checks(universe).items() if problems
    }
    assert violations == {}


def test_invalid_books_fail_loudly(clean_universe: LegacyUniverse) -> None:
    broken = copy.deepcopy(clean_universe)
    number, entry = next(iter(broken.journals.items()))
    first = entry.lines[0]
    broken.journals[number] = dataclasses.replace(
        entry,
        lines=(
            dataclasses.replace(
                first, functional_amount=first.functional_amount + first.functional_amount
            ),
            *entry.lines[1:],
        ),
    )
    with pytest.raises(BooksInvariantError, match="does not balance"):
        verify_clean_books(broken)
