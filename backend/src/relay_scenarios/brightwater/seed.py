"""Seed Brightwater into a Relay database at the "day 9" state (docs/demo-scenario.md §3).

Everything goes through Relay's services, acting as the seeded users with permission checks and
audit events, exactly as the product would: no table is written directly. The seed knows which
files exist and which people do what; it contains no expected findings.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from relay.changes.models import (
    ApprovalDecision,
    ChangeRequest,
    ChangeRequestKind,
    ChangeRequestStatus,
)
from relay.core.actor import Actor
from relay.core.currency import Currency
from relay.core.db import session_scope
from relay.identity import service as identity
from relay.identity.models import Role
from relay.identity.permissions import Permission
from relay.imports import service as imports
from relay.imports.blob_store import BlobStore
from relay.imports.models import Import, ImportStatus
from relay.mapping_sets import accounts as account_sets
from relay.mapping_sets import service as mapping_sets
from relay.pipeline import approvals
from relay.pipeline import service as pipeline
from relay.pipeline.models import PipelineRun
from relay.worker import WorkerContext, drain
from relay.workspace import service as workspace
from relay.workspace.models import DatasetType, SourceSystemKind

PEOPLE: Final = (
    ("maya.chen@relay.example", "Maya Chen", Role.IMPLEMENTATION_SPECIALIST),
    ("daniel.okafor@relay.example", "Daniel Okafor", Role.IMPLEMENTATION_LEAD),
    ("priya.raman@brightwater.example", "Priya Raman", Role.CUSTOMER_CONTROLLER),
    ("sam.ortiz@brightwater.example", "Sam Ortiz", Role.VIEWER),
    ("alex.lindqvist@relay.example", "Alex Lindqvist", Role.ADMIN),
)


@dataclass(frozen=True, slots=True)
class SeedResult:
    migration_id: uuid.UUID
    run_id: uuid.UUID | None
    """``None`` when seeding stopped before any mapping was approved."""
    users: dict[str, uuid.UUID]


def _wait_for_imports(
    session_factory: sessionmaker[Session],
    context: WorkerContext,
    dataset_ids: list[uuid.UUID],
    timeout_seconds: int = 300,
) -> None:
    """Process jobs here, or wait for another worker sharing this database and blob store."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        drain(context)
        with session_scope(session_factory) as session:
            states = {
                dataset_id: session.scalars(
                    select(Import)
                    .where(Import.dataset_id == dataset_id)
                    .order_by(Import.sequence.desc())
                ).first()
                for dataset_id in dataset_ids
            }
        failed = [
            s for s in states.values() if s is not None and s.status == ImportStatus.FAILED.value
        ]
        if failed:
            raise RuntimeError(
                "imports failed: " + ", ".join(f"{s.original_filename} ({s.error})" for s in failed)
            )
        if all(s is not None and s.status == ImportStatus.PARSED.value for s in states.values()):
            return
        if time.monotonic() > deadline:
            raise RuntimeError("timed out waiting for imports to be parsed")
        time.sleep(1)


def _actor(session: Session, email: str, permission: Permission) -> Actor:
    user = identity.find_active_user_by_email(session, email)
    if user is None:
        raise RuntimeError(f"seed user {email} is missing")
    actor = identity.actor_for(user)
    identity.require(actor, permission)
    return actor


def seed(
    session_factory: sessionmaker[Session],
    blob_store: BlobStore,
    limits: imports.ImportLimits,
    migration_dir: Path,
    mapping_set_path: Path,
    migration_name: str = "LedgerPro to new ERP",
    issue_key_prefix: str = "BWP",
    stop_after: Literal["imports", "run"] = "run",
) -> SeedResult:
    """Load a migration through the services as the seeded people.

    ``stop_after="imports"`` leaves it where a real project sits in its first week: files uploaded
    and profiled, no mapping approved, no run.
    """
    descriptor: dict[str, Any] = json.loads((migration_dir / "migration.json").read_text("utf-8"))
    mapping_config: dict[str, Any] = json.loads(mapping_set_path.read_text("utf-8"))
    context = WorkerContext(session_factory=session_factory, blob_store=blob_store, limits=limits)
    maya, daniel = PEOPLE[0][0], PEOPLE[1][0]

    with session_scope(session_factory) as session:
        users = {}
        for email, name, role in PEOPLE:
            existing = identity.find_active_user_by_email(session, email)
            user = existing or identity.create_user(
                session, email=email, display_name=name, role=role, actor=Actor.system()
            )
            users[email] = user.id

    with session_scope(session_factory) as session:
        lead = _actor(session, daniel, Permission.MANAGE_WORKSPACE)
        company_info = descriptor["company"]
        plan = descriptor["conversion_plan"]
        company = workspace.create_company(
            session,
            actor=lead,
            name=company_info["name"],
            legal_name=company_info["name"],
            country="US",
            functional_currency=Currency.of(company_info["functional_currency"]),
            fiscal_year_start_month=int(company_info["fiscal_year_start_month"]),
        )
        migration = workspace.create_migration(
            session,
            actor=lead,
            company=company,
            name=migration_name,
            plan=workspace.ConversionPlanInput(**plan),
            issue_key_prefix=issue_key_prefix,
            lead_user_id=lead.user_id,
        )
        migration_id = migration.id
        systems = {
            item["id"]: workspace.create_source_system(
                session,
                actor=lead,
                migration=migration,
                name=item["name"],
                kind=SourceSystemKind(item["kind"]),
            )
            for item in descriptor["source_systems"]
        }
        links = {link["file"]: link for link in mapping_config.get("bank_account_links", [])}
        datasets: dict[str, uuid.UUID] = {}
        for item in descriptor["datasets"]:
            dataset_type = DatasetType(item["dataset_type"])
            link = links.get(item["file"])
            dataset = workspace.create_dataset(
                session,
                actor=lead,
                source_system=systems[item["source_system"]],
                dataset_type=dataset_type,
                name=Path(item["file"]).name,
                as_of_date=date.fromisoformat(item["as_of"]) if item.get("as_of") else None,
                settings=workspace.DatasetSettings(
                    bank_account=link["bank_account"], gl_account=link["gl_account"]
                )
                if link
                else None,
            )
            datasets[item["file"]] = dataset.id

    for file_name, dataset_id in datasets.items():
        content = (migration_dir / file_name).read_bytes()
        with session_scope(session_factory) as session:
            specialist = _actor(session, maya, Permission.UPLOAD_IMPORT)
            imports.upload(
                session,
                actor=specialist,
                dataset=workspace.get_dataset(session, dataset_id),
                filename=Path(file_name).name,
                chunks=[content],
                blob_store=blob_store,
                limits=limits,
            )
    _wait_for_imports(session_factory, context, list(datasets.values()))
    if stop_after == "imports":
        return SeedResult(migration_id=migration_id, run_id=None, users=users)

    for file_name, dataset_id in datasets.items():
        with session_scope(session_factory) as session:
            specialist = _actor(session, maya, Permission.DRAFT_CHANGE_REQUEST)
            dataset = workspace.get_dataset(session, dataset_id)
            file_config = dict(mapping_config["datasets"][file_name])
            # The file-based mapping set repeats the aging date; in Relay it belongs to the dataset.
            as_of = file_config.pop("as_of", None)
            if (date.fromisoformat(as_of) if as_of else None) != dataset.as_of_date:
                raise RuntimeError(f"{file_name}: mapping as_of disagrees with the dataset")
            mapping_set = mapping_sets.create_draft(
                session, actor=specialist, dataset=dataset, config=file_config
            )
            change = approvals.create(
                session,
                actor=specialist,
                migration_id=migration_id,
                kind=ChangeRequestKind.COLUMN_MAPPING_SET,
                title=f"Column mapping for {dataset.name}",
                payload={"mapping_set_id": str(mapping_set.id)},
            )
            approvals.submit(
                session,
                actor=specialist,
                change=change,
                justification="Mapping reviewed against the export header and sample rows.",
            )
            change_id = change.id
        with session_scope(session_factory) as session:
            reviewer = _actor(session, daniel, Permission.REVIEW_CHANGE_REQUEST)
            reviewed = approvals.review(
                session,
                actor=reviewer,
                change=session.get_one(ChangeRequest, change_id),
                decision=ApprovalDecision.APPROVE,
                comment="Approved.",
            )
            if reviewed.change.status != ChangeRequestStatus.APPLIED.value:
                raise RuntimeError(f"mapping change request ended as {reviewed.change.status}")

    controller = PEOPLE[2][0]
    with session_scope(session_factory) as session:
        # The project's account mapping file becomes governed account mapping set version 1.
        specialist = _actor(session, maya, Permission.DRAFT_CHANGE_REQUEST)
        account_set = account_sets.create_draft(
            session, actor=specialist, migration_id=migration_id, base="import", changes=[]
        )
        change = approvals.create(
            session,
            actor=specialist,
            migration_id=migration_id,
            kind=ChangeRequestKind.ACCOUNT_MAPPING_SET,
            title="Account mapping from the implementation mapping file",
            payload={"mapping_set_id": str(account_set.id)},
        )
        approvals.submit(
            session,
            actor=specialist,
            change=change,
            justification="Mapping agreed in the chart of accounts workshop.",
        )
        change_id = change.id
    for reviewer_email in (daniel, controller):
        with session_scope(session_factory) as session:
            reviewer = _actor(session, reviewer_email, Permission.REVIEW_CHANGE_REQUEST)
            approvals.review(
                session,
                actor=reviewer,
                change=session.get_one(ChangeRequest, change_id),
                decision=ApprovalDecision.APPROVE,
                comment="Approved.",
            )
    with session_scope(session_factory) as session:
        status = session.get_one(ChangeRequest, change_id).status
        if status != ChangeRequestStatus.APPLIED.value:
            raise RuntimeError(f"account mapping change request ended as {status}")

    with session_scope(session_factory) as session:
        specialist = _actor(session, maya, Permission.REQUEST_PIPELINE_RUN)
        request = pipeline.request_run(session, actor=specialist, migration_id=migration_id)
        run_id = request.run.id
    deadline = time.monotonic() + 600
    while True:
        drain(context)
        with session_scope(session_factory) as session:
            run = session.get_one(PipelineRun, run_id)
            status, error = run.status, run.error
        if status == "succeeded":
            break
        if status == "failed" or time.monotonic() > deadline:
            raise RuntimeError(f"seed pipeline run ended as {status}: {error}")
        time.sleep(1)
    return SeedResult(migration_id=migration_id, run_id=run_id, users=users)
