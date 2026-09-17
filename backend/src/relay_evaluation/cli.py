"""``relay-eval``: evaluation-only commands (they may reveal expected answers)."""

from __future__ import annotations

import argparse
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
    sub.add_parser("show-manifest", help="print the golden manifest (reveals expected answers)")
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    raise SystemExit(main())
