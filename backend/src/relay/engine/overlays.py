"""Overlays: approved modifications applied on top of immutable source data (docs/governance.md §2).

In later milestones these are created only by applying approved change requests. The engine applies
whatever overlays it is given, verifies their preconditions, and reports stale ones.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from relay.canonical.enums import PartyType
from relay.core.errors import InvalidInputError


class OverlayError(InvalidInputError):
    code: ClassVar[str] = "engine.invalid_overlay"
    title: ClassVar[str] = "Invalid overlay"


@dataclass(frozen=True, slots=True)
class RecordOverride:
    id: str
    record: str
    """Natural key, e.g. ``je:JE-1``."""
    field: str
    expected_current: str
    new_value: str
    reason: str


@dataclass(frozen=True, slots=True)
class QuarantineRepair:
    id: str
    file: str
    quarantine_key: str
    replacement_text: str
    reason: str


@dataclass(frozen=True, slots=True)
class EntityDecision:
    id: str
    party_type: PartyType
    decision: str
    members: tuple[str, ...]
    survivor: str | None
    reason: str

    def __post_init__(self) -> None:
        if self.decision not in {"same_entity", "distinct"}:
            raise OverlayError("entity decision must be same_entity or distinct")
        if len(set(self.members)) < 2:
            raise OverlayError("an entity decision needs at least two distinct members")
        if self.decision == "same_entity" and self.survivor not in self.members:
            raise OverlayError("same_entity decisions need a survivor among the members")


@dataclass(frozen=True, slots=True)
class AccountMappingChange:
    id: str
    legacy_account: str
    target_account: str
    reason: str


@dataclass(frozen=True, slots=True)
class Disposition:
    id: str
    fingerprint: str
    kind: str
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in {
            "carry_forward_adjustment",
            "accepted_risk",
            "false_positive",
            "not_applicable",
        }:
            raise OverlayError(f"unknown disposition kind {self.kind}")


@dataclass(frozen=True, slots=True)
class GateWaiver:
    id: str
    gate_id: str
    run_fingerprint: str
    """A waiver applies only to the run whose input fingerprint it was approved against."""
    reason: str


@dataclass(frozen=True, slots=True)
class Signoff:
    id: str
    run_fingerprint: str


@dataclass(frozen=True, slots=True)
class Overlays:
    record_overrides: tuple[RecordOverride, ...] = ()
    quarantine_repairs: tuple[QuarantineRepair, ...] = ()
    entity_decisions: tuple[EntityDecision, ...] = ()
    account_mapping_changes: tuple[AccountMappingChange, ...] = ()
    dispositions: tuple[Disposition, ...] = ()
    gate_waivers: tuple[GateWaiver, ...] = ()
    signoffs: tuple[Signoff, ...] = ()
    notes: dict[str, str] = field(default_factory=dict)

    def identity(self) -> dict[str, list[str]]:
        """Stable description used in the input fingerprint.

        Gate waivers and sign-offs are bound *to* a fingerprint, so they cannot be part of it.
        """
        return {
            "record_overrides": sorted(
                f"{o.id}:{o.record}:{o.field}:{o.new_value}" for o in self.record_overrides
            ),
            "quarantine_repairs": sorted(
                f"{r.id}:{r.file}:{r.quarantine_key}" for r in self.quarantine_repairs
            ),
            "entity_decisions": sorted(
                f"{d.id}:{d.decision}:{','.join(sorted(d.members))}" for d in self.entity_decisions
            ),
            "account_mapping_changes": sorted(
                f"{c.id}:{c.legacy_account}>{c.target_account}"
                for c in self.account_mapping_changes
            ),
            "dispositions": sorted(f"{d.id}:{d.fingerprint}:{d.kind}" for d in self.dispositions),
        }


def _items(raw: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise OverlayError(f"{key} must be a list")
    return value


def parse_overlays(raw: Mapping[str, Any]) -> Overlays:
    try:
        return Overlays(
            record_overrides=tuple(
                RecordOverride(
                    o["id"],
                    o["record"],
                    o["field"],
                    str(o["expected_current"]),
                    str(o["new_value"]),
                    o["reason"],
                )
                for o in _items(raw, "record_overrides")
            ),
            quarantine_repairs=tuple(
                QuarantineRepair(
                    r["id"], r["file"], r["quarantine_key"], r["replacement_text"], r["reason"]
                )
                for r in _items(raw, "quarantine_repairs")
            ),
            entity_decisions=tuple(
                EntityDecision(
                    d["id"],
                    PartyType(d["party_type"]),
                    d["decision"],
                    tuple(d["members"]),
                    d.get("survivor"),
                    d["reason"],
                )
                for d in _items(raw, "entity_decisions")
            ),
            account_mapping_changes=tuple(
                AccountMappingChange(c["id"], c["legacy_account"], c["target_account"], c["reason"])
                for c in _items(raw, "account_mapping_changes")
            ),
            dispositions=tuple(
                Disposition(d["id"], d["fingerprint"], d["kind"], d["reason"])
                for d in _items(raw, "dispositions")
            ),
            gate_waivers=tuple(
                GateWaiver(w["id"], w["gate_id"], w["run_fingerprint"], w["reason"])
                for w in _items(raw, "gate_waivers")
            ),
            signoffs=tuple(Signoff(s["id"], s["run_fingerprint"]) for s in _items(raw, "signoffs")),
        )
    except KeyError as exc:
        raise OverlayError(f"overlay is missing field {exc.args[0]}") from exc
