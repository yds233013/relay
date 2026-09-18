"""``relay-eval``: evaluation-only commands (they may reveal expected answers)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from relay_evaluation.brightwater.manifest import load_manifest
from relay_evaluation.brightwater.verify import verify_scenario
from relay_evaluation.paths import BRIGHTWATER_FIXTURES, BRIGHTWATER_MANIFEST


def _read_fixtures(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "SHA256SUMS"
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="relay-eval", description="EVALUATION ONLY: golden-manifest tooling"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser(
        "verify-brightwater", help="verify fixtures against the golden manifest"
    )
    verify.add_argument("--fixtures", type=Path, default=BRIGHTWATER_FIXTURES)
    sub.add_parser(
        "verify-kestrel",
        help="run the engine over the second company and compare with its expectations",
    )
    sub.add_parser("show-manifest", help="print the golden manifest (reveals expected answers)")
    ai = sub.add_parser(
        "ai",
        help="run investigator evals E1-E6 against the seeded day-9 database (RELAY_DATABASE_URL)",
    )
    ai.add_argument("--provider", choices=["scripted", "anthropic"], default="scripted")
    ai.add_argument("--out", type=Path, default=None, help="write results JSON here")
    args = parser.parse_args(argv)

    if args.command == "ai":
        return run_ai_evals(args.provider, args.out)

    if args.command == "verify-kestrel":
        return verify_kestrel()

    if args.command == "show-manifest":
        sys.stdout.write(BRIGHTWATER_MANIFEST.read_text(encoding="utf-8"))
        return 0

    manifest = load_manifest()
    report = verify_scenario(_read_fixtures(args.fixtures), manifest)
    for name, ok, detail in report.results:
        if not ok:
            sys.stdout.write(f"FAIL {name}: {detail}\n")
    passed = len(report.results) - len(report.failures)
    sys.stdout.write(f"{passed}/{len(report.results)} manifest checks passed\n")
    return 0 if report.ok else 1


def verify_kestrel() -> int:
    """The generalization test: the same engine, a company it has never seen."""
    from relay_evaluation.kestrel.verify import format_report, verify  # noqa: PLC0415 - slow import

    report = verify()
    sys.stdout.write(format_report(report) + "\n")
    return 0 if not report.failures else 1


def run_ai_evals(provider_name: str, out: Path | None) -> int:
    """Live runs call the provider and cost money; they are manual only (never CI)."""
    from relay.ai.prompts import INVESTIGATOR_VERSION  # noqa: PLC0415 - optional command
    from relay.ai.providers.factory import provider_from_settings  # noqa: PLC0415
    from relay.core.config import get_settings  # noqa: PLC0415
    from relay.core.db import (  # noqa: PLC0415
        create_db_engine,
        create_session_factory,
        session_scope,
    )
    from relay_evaluation.ai.harness import run_all  # noqa: PLC0415
    from relay_scenarios.brightwater.fast_forward import brightwater_migration  # noqa: PLC0415

    settings = get_settings().model_copy(update={"ai_provider": provider_name})
    if provider_name == "anthropic" and settings.anthropic_api_key is None:
        sys.stderr.write("ANTHROPIC_API_KEY is not set; a live eval was not run.\n")
        return 2
    factory = create_session_factory(create_db_engine(settings))
    with session_scope(factory) as session:
        migration_id = brightwater_migration(session)
    provider = provider_from_settings(settings) if provider_name == "anthropic" else None
    result = {
        **run_all(factory, settings, migration_id, provider),
        "prompt_version": INVESTIGATOR_VERSION,
    }
    text = json.dumps(result, indent=2, sort_keys=True)
    sys.stdout.write(text + "\n")
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0 if result["fabricated_references"] == 0 and result["injection_violations"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
