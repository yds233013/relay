"""``relay``: operator commands for the runtime engine.

``relay engine run`` runs the deterministic pipeline over a migration directory (``migration.json``
plus source files) with an approved column mapping set and optional overlays, and prints a factual
summary or writes a JSON report. It knows nothing about any particular company.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from relay.core.hashing import canonical_json
from relay.engine.inputs import load_inputs
from relay.engine.overlays import Overlays, parse_overlays
from relay.engine.pipeline import EngineResult, run_engine
from relay.engine.policy import Policy
from relay.engine.readiness import GovernanceFacts, Readiness, evaluate_readiness


def _report(result: EngineResult, readiness: Readiness) -> dict[str, Any]:
    return {
        "input_fingerprint": result.input_fingerprint,
        "result_fingerprint": result.result_fingerprint,
        "ready": readiness.ready,
        "unresolved_exposure": str(readiness.unresolved_exposure),
        "gates": [
            {"gate": g.gate_id, "title": g.title, "status": g.status.value, "observed": g.observed}
            for g in readiness.gates
        ],
        "reconciliations": [
            {
                "recon": r.recon_id,
                "status": r.status,
                "lines": len(r.lines),
                "discrepancies": len(r.discrepancies()),
            }
            for r in result.reconciliations
        ],
        "findings": [
            {
                "rule": e.rule_id,
                "severity": e.severity.value,
                "subjects": list(e.subjects),
                "amount_at_risk": None if e.amount_at_risk is None else str(e.amount_at_risk),
                "status": readiness.issue_status[e.fingerprint],
                "fingerprint": e.fingerprint,
                "message": e.message,
            }
            for e in result.exceptions
        ],
        "candidates": [
            {"party_type": c.party_type.value, "members": list(c.members), "score": str(c.score)}
            for c in result.candidates
        ],
        "skipped_rules": [
            {"rule": s.rule_id, "missing": list(s.missing_datasets)} for s in result.skipped_rules
        ],
    }


def _summary(report: dict[str, Any]) -> str:
    lines = [
        f"input fingerprint   {report['input_fingerprint']}",
        f"ready               {report['ready']}",
        f"unresolved exposure {report['unresolved_exposure']}",
        "gates               " + " ".join(f"{g['gate']}:{g['status']}" for g in report["gates"]),
        "reconciliations     "
        + " ".join(f"{r['recon']}:{r['status']}" for r in report["reconciliations"]),
    ]
    by_severity = Counter(f["severity"] for f in report["findings"])
    lines.append(
        f"findings            {len(report['findings'])} "
        + "("
        + ", ".join(f"{k} {by_severity[k]}" for k in ("critical", "high", "medium", "low"))
        + ")"
    )
    for rule, count in sorted(Counter(f["rule"] for f in report["findings"]).items()):
        lines.append(f"  {rule:<40} {count}")
    lines.append(f"entity candidates   {len(report['candidates'])}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relay", description="Relay operator commands")
    sub = parser.add_subparsers(dest="area", required=True)
    engine = sub.add_parser("engine", help="deterministic engine").add_subparsers(
        dest="command", required=True
    )
    run = engine.add_parser("run", help="run the pipeline over a migration directory")
    run.add_argument("--migration", type=Path, required=True, help="directory with migration.json")
    run.add_argument("--mapping-set", type=Path, required=True, help="approved column mapping set")
    run.add_argument("--overlays", type=Path, help="approved overlays (JSON)")
    run.add_argument("--json", type=Path, help="write the full report to this file")
    args = parser.parse_args(argv)

    inputs = load_inputs(args.migration, args.mapping_set)
    overlays = (
        parse_overlays(json.loads(args.overlays.read_text(encoding="utf-8")))
        if args.overlays
        else Overlays()
    )
    policy = Policy()
    result = run_engine(inputs, overlays, policy)
    facts = GovernanceFacts(required_datasets=frozenset(s.dataset_type for s in inputs.datasets))
    report = _report(result, evaluate_readiness(result, overlays, policy, facts))
    if args.json:
        args.json.write_bytes(canonical_json(report) + b"\n")
    sys.stdout.write(_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
