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
from relay.core.actor import Actor
from relay.core.config import get_settings
from relay.core.db import create_db_engine, create_session_factory, session_scope
from relay.core.logging import configure_logging
from relay.engine.inputs import build_inputs
from relay.engine.pipeline import run_engine
from relay.identity import service as identity
from relay.identity.models import DEMO_VISITOR_EMAIL, Role
from relay.imports.blob_store import LocalBlobStore
from relay.imports.service import ImportLimits
from relay_scenarios.brightwater.constants import DEFAULT_SEED
from relay_scenarios.brightwater.fast_forward import (
    brightwater_migration,
    enable_ai,
    fast_forward,
)
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
from relay_scenarios.kestrel import scenario as kestrel
from relay_scenarios.perf import measure_pipeline
from relay_scenarios.portfolio import seed_portfolio
from relay_scenarios.volume import build_volume_migration, export_volume_migration

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "fixtures" / "demo" / "brightwater"
DEFAULT_REEXPORT_OUT = REPO_ROOT / "fixtures" / "demo" / "brightwater_reexport"
DEFAULT_MAPPING_SET = (
    REPO_ROOT / "fixtures" / "demo" / "brightwater_config" / "column_mapping_set_v1.json"
)
DEFAULT_KESTREL_OUT = REPO_ROOT / "fixtures" / "demo" / "kestrel"


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


def seed_portfolio_database(mapping_set_path: Path) -> int:
    """Add the two extra fictional migrations to the database named by RELAY_DATABASE_URL."""
    settings = get_settings()
    configure_logging("WARNING", settings.log_format)
    factory = create_session_factory(create_db_engine(settings))
    result = seed_portfolio(
        factory,
        LocalBlobStore(settings.storage_dir),
        ImportLimits(settings.max_upload_bytes, settings.max_rows_per_import),
        mapping_set_path,
    )
    sys.stdout.write(
        "Seeded two more fictional migrations:\n"
        f"  launched     {result.launched} ({result.launched_status})\n"
        f"  early stage  {result.early} (imports only)\n"
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


def enable_ai_for_demo() -> int:
    """Record AI consent for the seeded migration, through the same approvals as any change."""
    settings = get_settings()
    configure_logging("WARNING", settings.log_format)
    factory = create_session_factory(create_db_engine(settings))
    with session_scope(factory) as session:
        migration_id = brightwater_migration(session)
    state = enable_ai(
        factory,
        LocalBlobStore(settings.storage_dir),
        ImportLimits(settings.max_upload_bytes, settings.max_rows_per_import),
        migration_id=migration_id,
    )
    sys.stdout.write(
        f"AI investigation for Brightwater (fictional): {state}\n"
        f"  provider in this process: {settings.ai_provider}\n"
        "  consent was recorded by a policy change approved by the lead and the controller\n"
    )
    return 0


def prepare_public_demo() -> int:
    """Make a seeded database serviceable as a public demo.

    Two things, both through the ordinary path: the read-only visitor every anonymous caller will
    be resolved to, and the customer's AI consent as an approved policy change. Idempotent, so
    re-running it after a reseed is safe.
    """
    settings = get_settings()
    configure_logging("WARNING", settings.log_format)
    factory = create_session_factory(create_db_engine(settings))
    with session_scope(factory) as session:
        migration_id = brightwater_migration(session)
        existing = identity.find_active_user_by_email(session, DEMO_VISITOR_EMAIL)
        if existing is None:
            identity.create_user(
                session,
                email=DEMO_VISITOR_EMAIL,
                display_name="Public demo visitor",
                role=Role.DEMO_VISITOR,
                actor=Actor.system(),
            )
        visitor = "created" if existing is None else "already present"
    state = enable_ai(
        factory,
        LocalBlobStore(settings.storage_dir),
        ImportLimits(settings.max_upload_bytes, settings.max_rows_per_import),
        migration_id=migration_id,
    )
    sys.stdout.write(
        f"Public demo visitor ({DEMO_VISITOR_EMAIL}): {visitor}\n"
        f"AI investigation for Brightwater (fictional): {state}\n"
        "  consent was recorded by a policy change approved by the lead and the controller\n"
        "  start the API with RELAY_ENV=demo and RELAY_AI_PROVIDER=demo\n"
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


def perf_pipeline(lines: int, mapping_set_path: Path) -> int:
    """Measure the persisted pipeline against RELAY_DATABASE_URL (use a throwaway database)."""
    settings = get_settings()
    configure_logging("WARNING", settings.log_format)
    factory = create_session_factory(create_db_engine(settings))
    report = measure_pipeline(
        factory,
        settings,
        LocalBlobStore(settings.storage_dir),
        ImportLimits(settings.max_upload_bytes, settings.max_rows_per_import),
        mapping_set_path,
        lines,
    )
    machine = (
        f"{platform.platform()}; {platform.machine()}; {os.cpu_count()} logical CPUs; "
        f"Python {platform.python_version()}"
    )
    sys.stdout.write(
        "Persisted pipeline on a synthetic clean migration (Harborline Supply Co., fictional)\n"
        f"  machine              {machine}\n"
        + "".join(f"  {line}\n" for line in report)
        + f"  peak RSS MiB         {_peak_rss_mib():.0f} (whole process, including generation)\n"
    )
    return 0


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


def kestrel_summary(scenario: kestrel.Scenario, out_dir: Path | None) -> str:
    """Describe the generated data. Which defects are planted is in relay_scenarios, not here."""
    books = scenario.books
    lines = [
        f"{kestrel.COMPANY} (fictional)",
        f"  legacy accounts     {len(books.accounts)}",
        f"  target accounts     {len(books.target_accounts)}",
        f"  customers           {len(books.customers)}",
        f"  suppliers           {len(books.suppliers)}",
        f"  invoices            {len(books.invoices)}",
        f"  bills               {len(books.bills)}",
        f"  settlements         {len(books.settlements)}",
        f"  journal entries     {len(books.entries)} "
        f"({sum(len(e.lines) for e in books.entries)} lines)",
        f"  bank transactions   {len(books.bank)}",
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
    perf_pipeline_parser = sub.add_parser(
        "perf-pipeline",
        help="measure imports, runs, readiness and reads against RELAY_DATABASE_URL "
        "(loads a synthetic migration; use a throwaway database)",
    )
    perf_pipeline_parser.add_argument("--lines", type=int, default=250_000)
    perf_pipeline_parser.add_argument("--mapping-set", type=Path, default=DEFAULT_MAPPING_SET)
    seed_parser = sub.add_parser(
        "seed",
        help="load Brightwater into the database named by RELAY_DATABASE_URL (day-9 state)",
    )
    seed_parser.add_argument("--fixtures", type=Path, default=DEFAULT_OUT)
    seed_parser.add_argument("--mapping-set", type=Path, default=DEFAULT_MAPPING_SET)
    portfolio = sub.add_parser(
        "seed-portfolio",
        help="add two more fictional migrations (one signed off, one early stage) to the database",
    )
    portfolio.add_argument("--mapping-set", type=Path, default=DEFAULT_MAPPING_SET)
    generate_kestrel = sub.add_parser(
        "generate-kestrel", help="generate the second company's source files (generalization test)"
    )
    generate_kestrel.add_argument("--out", type=Path, default=DEFAULT_KESTREL_OUT)
    generate_kestrel.add_argument(
        "--clean", action="store_true", help="clean books without planted defects"
    )
    check_kestrel = sub.add_parser(
        "check-kestrel",
        help="verify the committed second-company fixtures match a fresh generation",
    )
    check_kestrel.add_argument("--out", type=Path, default=DEFAULT_KESTREL_OUT)
    sub.add_parser(
        "public-demo",
        help="prepare a seeded database to be served publicly: create the read-only demo visitor "
        "and record AI consent (idempotent)",
    )
    sub.add_parser(
        "enable-ai",
        help="record customer consent to AI investigation for the seeded migration "
        "(a governed policy change, approved by the seeded lead and controller)",
    )
    forward = sub.add_parser(
        "fast-forward",
        help="apply the documented resolutions as the seeded users (demo walkthrough step 10)",
    )
    forward.add_argument("--to", choices=["before-signoff"], required=True)
    args = parser.parse_args(argv)

    if args.command == "generate-kestrel":
        second = kestrel.build_scenario(defects=()) if args.clean else kestrel.build_scenario()
        kestrel.write_fixtures(second, args.out)
        sys.stdout.write(kestrel_summary(second, args.out))
        return 0

    if args.command == "check-kestrel":
        fresh = kestrel.build_scenario().files
        drift = _drift({**fresh, kestrel.CHECKSUM_FILE: kestrel.checksum_manifest(fresh)}, args.out)
        if drift:
            sys.stdout.write(
                "Second-company fixtures differ from a fresh generation:\n"
                + "".join(f"  {path}\n" for path in drift)
            )
            sys.stdout.write("Run `make demo-kestrel` to regenerate, and review the diff.\n")
            return 1
        count = len(fresh) + 1
        sys.stdout.write(f"{count} second-company fixture files match a fresh generation.\n")
        return 0

    if args.command == "public-demo":
        return prepare_public_demo()

    if args.command == "enable-ai":
        return enable_ai_for_demo()

    if args.command == "fast-forward":
        return fast_forward_database()

    if args.command == "seed-portfolio":
        return seed_portfolio_database(args.mapping_set)

    if args.command == "seed":
        return seed_database(args.fixtures, args.mapping_set)

    if args.command == "perf-pipeline":
        return perf_pipeline(args.lines, args.mapping_set)

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
    drift = _drift(_with_checksums(scenario.files), args.out) + _drift(
        _with_checksums(reexport_files(scenario)), args.reexport_out
    )
    if drift:
        sys.stdout.write(
            "Fixtures differ from a fresh generation:\n" + "".join(f"  {path}\n" for path in drift)
        )
        sys.stdout.write("Run `make demo-data` to regenerate, and review the diff.\n")
        return 1
    count = len(scenario.files) + len(reexport_files(scenario)) + 2
    sys.stdout.write(f"{count} fixture files match a fresh generation (seed {DEFAULT_SEED}).\n")
    return 0


def _with_checksums(files: dict[str, bytes]) -> dict[str, bytes]:
    return {**files, CHECKSUM_FILE: checksum_manifest(files)}


def _drift(expected: dict[str, bytes], root: Path) -> list[str]:
    """Compare a freshly generated set of files, checksums included, with what is on disk."""
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
