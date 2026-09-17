"""``relay``: operator commands.

* ``relay worker [--once]`` processes queued jobs.
* ``relay verify-audit [--migration ID]`` recomputes audit hash chains.
* ``relay engine run`` runs the deterministic pipeline over a migration directory
  (``migration.json`` plus source files) with an approved column mapping set and optional
  overlays, and prints a factual summary or writes a JSON report. It knows nothing about any
  particular company.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from relay.audit.models import AuditEvent
from relay.audit.service import verify_chain
from relay.core.config import Settings, get_settings
from relay.core.db import create_db_engine, create_session_factory
from relay.core.hashing import canonical_json
from relay.core.logging import configure_logging
from relay.engine.inputs import load_inputs
from relay.engine.overlays import Overlays, parse_overlays
from relay.engine.pipeline import EngineResult, run_engine
from relay.engine.policy import Policy
from relay.engine.readiness import GovernanceFacts, Readiness, evaluate_readiness
from relay.imports.blob_store import LocalBlobStore
from relay.imports.service import ImportLimits
from relay.worker import WorkerContext, drain, run_forever


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


def _session_factory() -> tuple[Settings, sessionmaker[Session]]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    return settings, create_session_factory(create_db_engine(settings))


def _worker(*, once: bool) -> int:
    settings, factory = _session_factory()
    context = WorkerContext(
        session_factory=factory,
        blob_store=LocalBlobStore(settings.storage_dir),
        limits=ImportLimits(settings.max_upload_bytes, settings.max_rows_per_import),
    )
    if once:
        processed = drain(context)
        sys.stdout.write(f"processed {processed} jobs\n")
        return 0
    heartbeat = os.environ.get("RELAY_WORKER_HEARTBEAT_FILE")
    run_forever(context, heartbeat_file=Path(heartbeat) if heartbeat else None)
    return 0


def _verify_audit(migration_id: uuid.UUID | None) -> int:
    _, factory = _session_factory()
    with factory() as session:
        chains: list[uuid.UUID | None] = (
            [migration_id]
            if migration_id
            else [
                None,
                *session.scalars(
                    select(AuditEvent.migration_id)
                    .distinct()
                    .where(AuditEvent.migration_id.is_not(None))
                ),
            ]
        )
        ok = True
        for chain in chains:
            result = verify_chain(session, chain)
            label = str(chain) if chain else "platform"
            if result.valid:
                sys.stdout.write(f"{label}: valid ({result.events_checked} events)\n")
            else:
                ok = False
                sys.stdout.write(
                    f"{label}: BROKEN at sequence {result.first_broken_seq} ({result.problem})\n"
                )
    return 0 if ok else 1


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
    worker = sub.add_parser("worker", help="process queued jobs (imports, pipeline runs)")
    worker.add_argument("--once", action="store_true", help="drain the queue and exit")
    verify = sub.add_parser("verify-audit", help="verify audit hash chains")
    verify.add_argument("--migration", type=uuid.UUID, help="one migration (default: all chains)")
    args = parser.parse_args(argv)

    if args.area == "worker":
        return _worker(once=args.once)
    if args.area == "verify-audit":
        return _verify_audit(args.migration)

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
