"""``relay-demo``: generate and inspect fictional demo scenarios.

Output describes the generated data only. It never prints expected findings: use the
evaluation-only ``relay-eval`` command for that.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import sys
import time
from collections import Counter
from pathlib import Path

from relay.canonical.enums import PaymentDirection
from relay.core.config import get_settings
from relay.core.db import create_db_engine, create_session_factory, session_scope
from relay.core.logging import configure_logging
from relay.engine.inputs import build_inputs
from relay.engine.pipeline import run_engine
from relay.imports.blob_store import LocalBlobStore
from relay.imports.service import ImportLimits
from relay_scenarios.brightwater.constants import DEFAULT_SEED
from relay_scenarios.brightwater.fast_forward import brightwater_migration, fast_forward
from relay_scenarios.brightwater.scenario import (
    CHECKSUM_FILE,
    Scenario,
    build_scenario,
    checksum_manifest,
    reexport_files,
    write_files,
    write_fixtures,
)
from relay_scenarios.brightwater.seed import seed
from relay_scenarios.volume import build_volume_migration, export_volume_migration

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "fixtures" / "demo" / "brightwater"
DEFAULT_REEXPORT_OUT = REPO_ROOT / "fixtures" / "demo" / "brightwater_reexport"
DEFAULT_MAPPING_SET = (
    REPO_ROOT / "fixtures" / "demo" / "brightwater_config" / "column_mapping_set_v1.json"
)


def _peak_rss_mib() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux reports kibibytes.
    return usage / (1024 * 1024) if sys.platform == "darwin" else usage / 1024


def seed_database(fixtures: Path, mapping_set: Path) -> int:
    settings = get_settings()
    configure_logging("WARNING", settings.log_format)
    factory = create_session_factory(create_db_engine(settings))
    result = seed(
        factory,
        LocalBlobStore(settings.storage_dir),
        ImportLimits(settings.max_upload_bytes, settings.max_rows_per_import),
        fixtures,
        mapping_set,
    )
    sys.stdout.write(
        f"Seeded Brightwater (fictional): migration {result.migration_id}, run {result.run_id}\n"
        "Users: " + ", ".join(sorted(result.users)) + "\n"
    )
    return 0


def fast_forward_database() -> int:
    settings = get_settings()
    configure_logging("WARNING", settings.log_format)
    factory = create_session_factory(create_db_engine(settings))
    with session_scope(factory) as session:
        migration_id = brightwater_migration(session)
    result = fast_forward(
        factory,
        LocalBlobStore(settings.storage_dir),
        ImportLimits(settings.max_upload_bytes, settings.max_rows_per_import),
        migration_id=migration_id,
    )
    sys.stdout.write(
        f"Fast-forwarded Brightwater (fictional) {result.migration_id} to before sign-off\n"
        + "".join(f"  applied: {step}\n" for step in result.applied)
        + f"  failing gates: {', '.join(result.failing_gates)}\n"
    )
    return 0


def perf_engine(lines: int, mapping_set_path: Path) -> int:
    """Generate a clean synthetic migration, run the engine once, and report measured facts only."""
    started = time.perf_counter()
    migration = build_volume_migration(lines)
    files = export_volume_migration(migration)
    generated = time.perf_counter() - started
    mapping = json.loads(mapping_set_path.read_text(encoding="utf-8"))
    inputs = build_inputs(json.loads(files["migration.json"]), files, mapping)
    started = time.perf_counter()
    result = run_engine(inputs)
    elapsed = time.perf_counter() - started
    discrepancies = sum(len(r.discrepancies()) for r in result.reconciliations)
    report = [
        "Synthetic clean migration (Harborline Supply Co., fictional)",
        f"  machine             {platform.platform()}; {platform.machine()}; "
        f"{os.cpu_count()} logical CPUs; Python {platform.python_version()}",
        f"  GL detail lines     {migration.line_count}",
        f"  journal entries     {len(migration.entries)}",
        f"  invoices / bills    {len(migration.invoices)} / {len(migration.bills)}",
        f"  payments            {len(migration.payments)}",
        f"  parties             {len(migration.customers)} customers, "
        f"{len(migration.vendors)} vendors",
        f"  source bytes        {sum(len(v) for v in files.values())}",
        f"  generation seconds  {generated:.2f} (not part of the engine measurement)",
        f"  engine seconds      {elapsed:.2f} (single run, wall clock, one process)",
        f"  peak RSS MiB        {_peak_rss_mib():.0f} (whole process, including generation)",
        f"  findings            {len(result.exceptions)}",
        f"  recon discrepancies {discrepancies}",
        f"  entity candidates   {len(result.candidates)}",
    ]
    sys.stdout.write("\n".join(report) + "\n")
    # Clean books: any finding means the measurement is not of a correct run.
    return 0 if not result.exceptions and discrepancies == 0 else 1


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
    generate.add_argument(
        "--reexport-out",
        type=Path,
        default=DEFAULT_REEXPORT_OUT,
        help="where the unfiltered re-exports are written (not with --clean)",
    )
    check = sub.add_parser(
        "check", help="verify committed fixtures match a fresh generation byte for byte"
    )
    check.add_argument("--out", type=Path, default=DEFAULT_OUT)
    check.add_argument("--reexport-out", type=Path, default=DEFAULT_REEXPORT_OUT)
    perf = sub.add_parser(
        "perf-engine", help="measure the engine on a synthetic clean migration of a given size"
    )
    perf.add_argument("--lines", type=int, default=250_000)
    perf.add_argument("--mapping-set", type=Path, default=DEFAULT_MAPPING_SET)
    seed_parser = sub.add_parser(
        "seed",
        help="load Brightwater into the database named by RELAY_DATABASE_URL (day-9 state)",
    )
    seed_parser.add_argument("--fixtures", type=Path, default=DEFAULT_OUT)
    seed_parser.add_argument("--mapping-set", type=Path, default=DEFAULT_MAPPING_SET)
    forward = sub.add_parser(
        "fast-forward",
        help="apply the documented resolutions as the seeded users (demo walkthrough step 10)",
    )
    forward.add_argument("--to", choices=["before-signoff"], required=True)
    args = parser.parse_args(argv)

    if args.command == "fast-forward":
        return fast_forward_database()

    if args.command == "seed":
        return seed_database(args.fixtures, args.mapping_set)

    if args.command == "perf-engine":
        return perf_engine(args.lines, args.mapping_set)

    if args.command == "generate":
        scenario = (
            build_scenario(args.seed, defects=()) if args.clean else build_scenario(args.seed)
        )
        write_fixtures(scenario, args.out)
        sys.stdout.write(summary(scenario, args.out))
        if not args.clean:
            reexports = reexport_files(scenario)
            write_files(reexports, args.reexport_out)
            sys.stdout.write(
                f"  unfiltered re-exports {len(reexports)} files in {args.reexport_out}\n"
            )
        return 0

    scenario = build_scenario(DEFAULT_SEED)
    drift = _drift(scenario.files, args.out) + _drift(reexport_files(scenario), args.reexport_out)
    if drift:
        sys.stdout.write(
            "Fixtures differ from a fresh generation:\n" + "".join(f"  {path}\n" for path in drift)
        )
        sys.stdout.write("Run `make demo-data` to regenerate, and review the diff.\n")
        return 1
    count = len(scenario.files) + len(reexport_files(scenario)) + 2
    sys.stdout.write(f"{count} fixture files match a fresh generation (seed {DEFAULT_SEED}).\n")
    return 0


def _drift(files: dict[str, bytes], root: Path) -> list[str]:
    expected = {**files, CHECKSUM_FILE: checksum_manifest(files)}
    actual = (
        {
            p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }
        if root.exists()
        else {}
    )
    return sorted(
        f"{root.name}/{path}"
        for path in set(expected) | set(actual)
        if expected.get(path) != actual.get(path)
    )


if __name__ == "__main__":
    raise SystemExit(main())
