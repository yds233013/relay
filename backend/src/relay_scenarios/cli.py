"""``relay-demo``: generate and inspect fictional demo scenarios.

Output describes the generated data only. It never prints expected findings: use the
evaluation-only ``relay-eval`` command for that.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from relay.canonical.enums import PaymentDirection
from relay_scenarios.brightwater.constants import DEFAULT_SEED
from relay_scenarios.brightwater.scenario import (
    CHECKSUM_FILE,
    Scenario,
    build_scenario,
    checksum_manifest,
    write_fixtures,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "fixtures" / "demo" / "brightwater"


def summary(scenario: Scenario, out_dir: Path | None) -> str:
    u = scenario.universe
    exported_customers = sum(1 for c in u.customers.values() if c.is_active)
    payments = Counter(p.direction for p in u.payments.values())
    plan = u.plan
    active_accounts = sum(1 for a in u.accounts.values() if a.account.is_active)
    journal_lines = sum(len(e.lines) for e in u.journals.values())
    state = (
        "Run #1 source data (seeded issues applied)"
        if u.applied_injectors
        else "clean books (no seeded issues)"
    )
    lines = [
        f"Brightwater Provisions, Inc. (fictional) - seed {u.seed}",
        f"  conversion plan     opening {plan.opening_balance_date}, "
        f"history {plan.history_start_date}..{plan.cutover_date}, go-live {plan.go_live_date}",
        f"  legacy accounts     {len(u.accounts)} ({active_accounts} active)",
        f"  target accounts     {len(u.target_accounts)}",
        f"  customers           {len(u.customers)} in LedgerPro ({exported_customers} exported)",
        f"  vendors             {len(u.vendors)}",
        f"  invoices            {len(u.invoices)}",
        f"  bills               {len(u.bills)}",
        f"  receipts            {payments[PaymentDirection.RECEIVED]}",
        f"  bill payments       {payments[PaymentDirection.DISBURSED]}",
        f"  journal entries     {len(u.journals)} ({journal_lines} lines)",
        f"  bank transactions   {len(u.bank_lines)}",
        f"  scenario            {state}",
        f"  files               {len(scenario.files)}",
    ]
    if out_dir is not None:
        lines.append(f"  output              {out_dir}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="relay-demo", description="Generate fictional demo migration data"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="generate Brightwater source files")
    generate.add_argument("--seed", type=int, default=DEFAULT_SEED)
    generate.add_argument("--out", type=Path, default=DEFAULT_OUT)
    generate.add_argument("--clean", action="store_true", help="clean books without seeded issues")
    check = sub.add_parser(
        "check", help="verify committed fixtures match a fresh generation byte for byte"
    )
    check.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.command == "generate":
        scenario = (
            build_scenario(args.seed, defects=()) if args.clean else build_scenario(args.seed)
        )
        write_fixtures(scenario, args.out)
        sys.stdout.write(summary(scenario, args.out))
        return 0

    scenario = build_scenario(DEFAULT_SEED)
    expected = {**scenario.files, CHECKSUM_FILE: checksum_manifest(scenario.files)}
    root: Path = args.out
    actual = (
        {
            p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }
        if root.exists()
        else {}
    )
    drift = sorted(
        path for path in set(expected) | set(actual) if expected.get(path) != actual.get(path)
    )
    if drift:
        sys.stdout.write(
            "Fixtures differ from a fresh generation:\n" + "".join(f"  {path}\n" for path in drift)
        )
        sys.stdout.write("Run `make demo-data` to regenerate, and review the diff.\n")
        return 1
    sys.stdout.write(
        f"{len(expected)} fixture files match a fresh generation (seed {DEFAULT_SEED}).\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
