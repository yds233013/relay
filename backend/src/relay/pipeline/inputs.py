"""Build engine inputs and the run fingerprint from a migration's governed configuration.

Engine input is the verified bytes of each dataset's active import (content-addressed, hash checked
on read) plus its approved column mapping set. The same CSV reader produced the stored source rows,
so staged-record lineage (import, row, lines) points at the rows users can browse.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from relay.canonical.enums import PartyType
from relay.changes import kinds as change_kinds
from relay.changes.models import OverrideTarget
from relay.core.hashing import fingerprint as content_fingerprint
from relay.engine.inputs import BankAccountLink, ConversionPlan, DatasetSpec, MigrationInputs
from relay.engine.overlays import (
    Disposition,
    EntityDecision,
    GateWaiver,
    Overlays,
    QuarantineRepair,
    RecordOverride,
    Signoff,
)
from relay.engine.pipeline import engine_versions, input_fingerprint
from relay.engine.policy import Policy
from relay.engine.readiness import gate_set_version
from relay.imports.blob_store import BlobStore
from relay.imports.models import Import, ImportStatus, StoredFile
from relay.mapping_sets import accounts as account_sets
from relay.mapping_sets import service as mapping_sets
from relay.workspace import service as workspace
from relay.workspace.models import Dataset, Migration, SourceSystem


@dataclass(frozen=True, slots=True)
class DatasetState:
    dataset: Dataset
    active_import: Import | None
    stored_file: StoredFile | None
    mapping_set_id: uuid.UUID | None
    mapping_config: dict[str, Any] | None
    source_system: str

    @property
    def usable(self) -> bool:
        return (
            self.active_import is not None
            and self.active_import.status == ImportStatus.PARSED.value
            and self.stored_file is not None
            and self.mapping_config is not None
        )


@dataclass(frozen=True, slots=True)
class RunConfiguration:
    migration: Migration
    datasets: tuple[DatasetState, ...]
    policy: Policy
    policy_version: int
    overlays: Overlays
    account_mapping_set_id: uuid.UUID | None
    governed_account_mapping: dict[str, str] | None
    fingerprint: str
    components: dict[str, Any]

    @property
    def required_dataset_types(self) -> frozenset[str]:
        return frozenset(s.dataset.dataset_type for s in self.datasets if s.dataset.is_required)

    @property
    def all_mapped(self) -> bool:
        return all(
            s.mapping_config is not None for s in self.datasets if s.active_import is not None
        )


def load_configuration(session: Session, migration_id: uuid.UUID) -> RunConfiguration:
    migration = workspace.get_migration(session, migration_id)
    states = []
    for dataset in workspace.datasets_for(session, migration.id):
        active = session.get(Import, dataset.active_import_id) if dataset.active_import_id else None
        stored = session.get(StoredFile, active.stored_file_id) if active else None
        approved = mapping_sets.approved_set(session, dataset.id)
        system = session.get(SourceSystem, dataset.source_system_id)
        states.append(
            DatasetState(
                dataset=dataset,
                active_import=active,
                stored_file=stored,
                mapping_set_id=approved.id if approved else None,
                mapping_config=(
                    mapping_sets.engine_config(session, approved, dataset.dataset_type)
                    if approved
                    else None
                ),
                source_system=system.name if system else "",
            )
        )
    policy_row = workspace.current_policy(session, migration.id)
    policy = workspace.policy_from_document(policy_row.policy)
    # Waivers and sign-offs are not part of the fingerprint (Overlays.identity).
    overlays = _overlays(session, migration.id)
    approved_accounts = account_sets.approved_set(session, migration.id)
    governed = (
        {k: e.target for k, e in account_sets.entries(session, approved_accounts.id).items()}
        if approved_accounts
        else None
    )
    plan = _plan(migration)
    # File contents are identified by their hashes; bytes are read only when the run executes.
    engine_fp = input_fingerprint(
        _inputs(migration, plan, states, files={}, governed=governed), overlays, policy
    )
    components = {
        "migration_id": migration.id,
        "conversion_plan": {
            "opening_balance_date": migration.opening_balance_date,
            "history_start_date": migration.history_start_date,
            "cutover_date": migration.cutover_date,
            "go_live_date": migration.go_live_date,
            "bank_clearing_window_days": migration.bank_clearing_window_days,
        },
        "active_imports": {
            str(s.dataset.id): {"import_id": s.active_import.id, "sha256": s.stored_file.sha256}
            for s in states
            if s.usable and s.active_import is not None and s.stored_file is not None
        },
        "column_mapping_sets": {
            str(s.dataset.id): s.mapping_set_id for s in states if s.mapping_set_id is not None
        },
        "required_datasets": sorted(
            {s.dataset.dataset_type for s in states if s.dataset.is_required}
        ),
        "account_mapping_set": approved_accounts.id if approved_accounts else None,
        "policy_version": policy_row.version,
        "overlays": overlays.identity(),
        "engine_input_fingerprint": engine_fp,
        "versions": engine_versions(),
        "gate_set": gate_set_version(),
    }
    fingerprint = content_fingerprint(components)
    # Sign-offs are recorded against Relay's run fingerprint; the engine checks them against its
    # own input fingerprint. Neither fingerprint depends on sign-offs, so translating is safe.
    overlays = dataclasses.replace(
        overlays,
        signoffs=tuple(
            Signoff(
                id=s.id,
                run_fingerprint=engine_fp
                if s.run_fingerprint == fingerprint
                else s.run_fingerprint,
            )
            for s in overlays.signoffs
        ),
    )
    return RunConfiguration(
        migration=migration,
        datasets=tuple(states),
        policy=policy,
        policy_version=policy_row.version,
        overlays=overlays,
        account_mapping_set_id=approved_accounts.id if approved_accounts else None,
        governed_account_mapping=governed,
        fingerprint=fingerprint,
        components=components,
    )


def _overlays(session: Session, migration_id: uuid.UUID) -> Overlays:
    """Every active overlay, in approval order."""
    overrides = []
    repairs = []
    for row in change_kinds.active_overrides(session, migration_id):
        if row.target == OverrideTarget.CANONICAL_FIELD.value:
            overrides.append(
                RecordOverride(
                    id=str(row.id),
                    record=row.natural_key,
                    field=str(row.field),
                    expected_current=str(row.expected_current_value),
                    new_value=str(row.new_value),
                    reason=row.reason,
                )
            )
        else:
            repairs.append(
                QuarantineRepair(
                    id=str(row.id),
                    file=str(row.import_id),
                    quarantine_key=str(row.new_value["quarantine_key"]),
                    replacement_text=str(row.new_value["replacement_text"]),
                    reason=row.reason,
                )
            )
    decisions = tuple(
        EntityDecision(
            id=str(row.id),
            party_type=PartyType(row.party_type),
            decision=row.decision,
            members=tuple(row.members),
            survivor=row.survivor,
            reason=row.reason,
        )
        for row in change_kinds.active_entity_decisions(session, migration_id)
    )
    dispositions = tuple(
        Disposition(id=str(row.id), fingerprint=row.fingerprint, kind=row.kind, reason=row.reason)
        for row in change_kinds.active_dispositions(session, migration_id)
    )
    waivers = tuple(
        GateWaiver(
            id=str(row.id),
            gate_id=row.gate_id,
            run_fingerprint=row.run_fingerprint,
            reason=row.reason,
            scope={str(k): str(v) for k, v in row.scope.items()},
        )
        for row in change_kinds.active_waivers(session, migration_id)
    )
    signoffs = tuple(
        Signoff(id=str(row.id), run_fingerprint=row.run_fingerprint)
        for row in change_kinds.active_signoffs(session, migration_id)
    )
    return Overlays(
        record_overrides=tuple(overrides),
        quarantine_repairs=tuple(repairs),
        entity_decisions=decisions,
        dispositions=dispositions,
        gate_waivers=waivers,
        signoffs=signoffs,
    )


def _plan(migration: Migration) -> ConversionPlan:
    return ConversionPlan(
        opening_balance_date=migration.opening_balance_date,
        history_start_date=migration.history_start_date,
        cutover_date=migration.cutover_date,
        go_live_date=migration.go_live_date,
        bank_clearing_window_days=migration.bank_clearing_window_days,
    )


def _file_key(state: DatasetState) -> str:
    if state.active_import is None:
        raise ValueError("dataset has no active import")
    return str(state.active_import.id)


def _specs(states: tuple[DatasetState, ...] | list[DatasetState]) -> tuple[DatasetSpec, ...]:
    return tuple(
        DatasetSpec(
            file=_file_key(s),
            dataset_type=s.dataset.dataset_type,
            source_system=s.source_system,
            encoding=(s.active_import.encoding if s.active_import else None) or "utf-8",
            as_of=s.dataset.as_of_date,
            delimiter=(s.active_import.delimiter if s.active_import else None) or ",",
        )
        for s in states
        if s.usable
    )


def _mapping_set(states: list[DatasetState]) -> dict[str, Any]:
    datasets = {_file_key(s): s.mapping_config for s in states if s.usable}
    links = [
        {
            "file": _file_key(s),
            "bank_account": s.dataset.settings["bank_account"],
            "gl_account": s.dataset.settings["gl_account"],
        }
        for s in states
        if s.usable and s.dataset.dataset_type == "bank_transactions"
    ]
    return {"datasets": datasets, "bank_account_links": links}


def _inputs(
    migration: Migration,
    plan: ConversionPlan,
    states: list[DatasetState],
    files: dict[str, bytes],
    governed: dict[str, str] | None,
) -> MigrationInputs:
    mapping = _mapping_set(states)
    return MigrationInputs(
        plan=plan,
        functional_currency=migration.functional_currency,
        fiscal_year_start_month=migration.fiscal_year_start_month,
        datasets=_specs(states),
        files=files,
        mapping_set=mapping,
        bank_links=tuple(BankAccountLink(**link) for link in mapping["bank_account_links"]),
        file_hashes={
            _file_key(s): s.stored_file.sha256 for s in states if s.usable and s.stored_file
        },
        governed_account_mapping=governed,
    )


def load_engine_inputs(configuration: RunConfiguration, blob_store: BlobStore) -> MigrationInputs:
    """Read and hash-verify every active import's bytes."""
    states = list(configuration.datasets)
    files = {
        _file_key(s): blob_store.read(s.stored_file.storage_key, s.stored_file.sha256)
        for s in states
        if s.usable and s.stored_file is not None
    }
    return _inputs(
        configuration.migration,
        _plan(configuration.migration),
        states,
        files,
        configuration.governed_account_mapping,
    )
