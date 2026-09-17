"""Two more fictional migrations so the portfolio shows a real spread of states (demo only).

Both use the synthetic clean generator, loaded through the same services as the Brightwater seed:

- **Harborline Supply Co.** — clean books, every gate passing, signed off by the lead and the
  customer controller: what a finished migration looks like.
- **Northwind Timber Co.** — files uploaded and profiled, nothing mapped or run yet: what the first
  week looks like.

Neither carries planted defects, and neither is used for evaluation.
"""

from __future__ import annotations

import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from relay.changes.models import ApprovalDecision, ChangeRequest, ChangeRequestKind
from relay.core.actor import Actor
from relay.core.db import session_scope
from relay.identity import service as identity
from relay.imports.blob_store import BlobStore
from relay.imports.service import ImportLimits
from relay.pipeline import approvals
from relay.pipeline import service as pipeline
from relay.pipeline.models import PipelineRun
from relay.workspace.models import Migration
from relay_scenarios.brightwater.seed import PEOPLE, SeedResult, seed
from relay_scenarios.volume import build_volume_migration, export_volume_migration

LAUNCHED_COMPANY = "Harborline Supply Co."
EARLY_COMPANY = "Northwind Timber Co."
LAUNCHED_LINES = 4_000
EARLY_LINES = 1_200


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    launched: uuid.UUID
    launched_status: str
    early: uuid.UUID


def _actor(session: Session, email: str) -> Actor:
    user = identity.find_active_user_by_email(session, email)
    if user is None:
        raise RuntimeError(f"seed user {email} is missing")
    return identity.actor_for(user)


def _load(
    factory: sessionmaker[Session],
    blob_store: BlobStore,
    limits: ImportLimits,
    mapping_set_path: Path,
    *,
    company: str,
    lines: int,
    seed_value: int,
    migration_name: str,
    issue_key_prefix: str,
    stop_after: str,
) -> SeedResult:
    files = export_volume_migration(build_volume_migration(lines, seed=seed_value), company)
    with tempfile.TemporaryDirectory(prefix="relay-portfolio-") as directory:
        root = Path(directory)
        for name, content in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(content)
        return seed(
            factory,
            blob_store,
            limits,
            root,
            mapping_set_path,
            migration_name=migration_name,
            issue_key_prefix=issue_key_prefix,
            stop_after="imports" if stop_after == "imports" else "run",
        )


def _sign_off(factory: sessionmaker[Session], migration_id: uuid.UUID) -> str:
    """Request and approve a go-live sign-off exactly as people would (governance.md §4.2)."""
    maya, daniel, priya = PEOPLE[0][0], PEOPLE[1][0], PEOPLE[2][0]
    with session_scope(factory) as session:
        actor = _actor(session, maya)
        change = approvals.create(
            session, actor=actor, migration_id=migration_id,
            kind=ChangeRequestKind.READINESS_SIGNOFF, title="Go-live sign-off", payload={},
        )  # fmt: skip
        approvals.submit(
            session,
            actor=actor,
            change=change,
            justification="Every gate passes on this run; balances agreed with the customer.",
        )
        change_id = change.id
    for email in (daniel, priya):
        with session_scope(factory) as session:
            approvals.review(
                session, actor=_actor(session, email),
                change=session.get_one(ChangeRequest, change_id),
                decision=ApprovalDecision.APPROVE, comment="Reviewed against the evidence.",
            )  # fmt: skip
    with session_scope(factory) as session:
        return session.get_one(Migration, migration_id).status


def _await_run(factory: sessionmaker[Session], run_id: uuid.UUID, seconds: int = 300) -> None:
    deadline = time.monotonic() + seconds
    while True:
        with session_scope(factory) as session:
            run = session.get_one(PipelineRun, run_id)
            status, error = run.status, run.error
        if status == "succeeded":
            return
        if status == "failed" or time.monotonic() > deadline:
            raise RuntimeError(f"portfolio run ended as {status}: {error}")
        time.sleep(1)


def seed_portfolio(
    factory: sessionmaker[Session],
    blob_store: BlobStore,
    limits: ImportLimits,
    mapping_set_path: Path,
) -> PortfolioResult:
    launched = _load(
        factory, blob_store, limits, mapping_set_path,
        company=LAUNCHED_COMPANY, lines=LAUNCHED_LINES, seed_value=7_001,
        migration_name="HarborERP to new ERP", issue_key_prefix="HRB", stop_after="run",
    )  # fmt: skip
    if launched.run_id is None:
        raise RuntimeError("the launched migration produced no run")
    _await_run(factory, launched.run_id)
    with session_scope(factory) as session:
        pipeline.request_readiness_evaluation(session, migration_id=launched.migration_id)
    status = _sign_off(factory, launched.migration_id)

    early = _load(
        factory, blob_store, limits, mapping_set_path,
        company=EARLY_COMPANY, lines=EARLY_LINES, seed_value=7_002,
        migration_name="Timberline to new ERP", issue_key_prefix="NWT", stop_after="imports",
    )  # fmt: skip
    return PortfolioResult(
        launched=launched.migration_id, launched_status=status, early=early.migration_id
    )
