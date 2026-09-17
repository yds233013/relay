"""Entity resolution: deterministic duplicate candidates and decision-based clusters.

Scoring is a documented, hand-weighted linear model over explainable features
(docs/validation-and-reconciliation.md Part C). There is no auto-merge at any score: parties are
clustered only by approved ``same_entity`` decisions.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from itertools import combinations
from typing import Final

from relay.canonical import natural_keys as nk
from relay.canonical.enums import PartyType
from relay.canonical.records import Party
from relay.engine.overlays import EntityDecision

SCORING_VERSION: Final = 1

_LEGAL_SUFFIXES: Final = frozenset(
    {
        "llc",
        "l l c",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "limited",
        "gmbh",
        "lp",
        "llp",
    }
)
_TOKEN_SYNONYMS: Final = {"coop": "cooperative", "co op": "cooperative"}
_STREET_WORDS: Final = {
    "avenue": "ave",
    "av": "ave",
    "street": "st",
    "boulevard": "blvd",
    "road": "rd",
    "drive": "dr",
    "suite": "ste",
    "highway": "hwy",
    "parkway": "pkwy",
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "northwest": "nw",
    "northeast": "ne",
    "southwest": "sw",
    "southeast": "se",
    "place": "pl",
    "court": "ct",
}
_LOCATION_TOKEN: Final = re.compile(
    r"(?:#\s*(\d+)|\b(?:store|location|unit|branch)\s+(\d+)\b)", re.IGNORECASE
)
_FREE_MAIL: Final = frozenset(
    {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com"}
)

WEIGHTS: Final = {
    "name_similarity": Decimal("0.45"),
    "address_similarity": Decimal("0.25"),
    "postal_code_match": Decimal("0.10"),
    "email_domain_match": Decimal("0.10"),
    "tax_id_match": Decimal("0.20"),
    "shared_document_reference": Decimal("0.15"),
    "tax_id_conflict": Decimal("-0.30"),
    "region_conflict": Decimal("-0.25"),
    "location_conflict": Decimal("-0.20"),
}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def normalize_name(name: str) -> tuple[str, str | None]:
    """Return (normalized name, location token)."""
    location = None
    match = _LOCATION_TOKEN.search(name)
    if match:
        location = match.group(1) or match.group(2)
        name = _LOCATION_TOKEN.sub(" ", name)
    text = _fold(name).replace("&", " and ")
    text = re.sub(r"\bco-op\b", "coop", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for phrase, replacement in _TOKEN_SYNONYMS.items():
        text = re.sub(rf"\b{phrase}\b", replacement, text)
    tokens = [t for t in text.split() if t not in _LEGAL_SUFFIXES]
    # Multi-token legal suffixes such as "l l c" after punctuation removal.
    joined = " ".join(tokens)
    for suffix in sorted(_LEGAL_SUFFIXES, key=len, reverse=True):
        if " " in suffix and joined.endswith(" " + suffix):
            joined = joined[: -len(suffix) - 1]
    return joined.strip(), location


def normalize_address(address: str) -> str:
    text = re.sub(r"[^\w\s]", " ", _fold(address))
    words = [_STREET_WORDS.get(word, word) for word in text.split()]
    # "n w" (from N.W.) -> "nw"
    merged: list[str] = []
    for word in words:
        if (
            merged
            and len(word) == 1
            and len(merged[-1]) == 1
            and merged[-1] in "nsew"
            and word in "ew"
        ):
            merged[-1] = merged[-1] + word
        else:
            merged.append(word)
    return " ".join(merged)


def _similarity(a: str, b: str) -> Decimal:
    if not a or not b:
        return Decimal(0)
    ratio = SequenceMatcher(None, a, b, autojunk=False).ratio()
    tokens_a, tokens_b = set(a.split()), set(b.split())
    containment = len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))
    best = max(ratio, containment if min(len(tokens_a), len(tokens_b)) >= 2 else 0.0)
    return Decimal(str(round(best, 4)))


def _email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].casefold()
    return None if domain in _FREE_MAIL else domain


@dataclass(frozen=True, slots=True)
class Candidate:
    party_type: PartyType
    left: str
    right: str
    score: Decimal
    features: dict[str, object]

    @property
    def members(self) -> tuple[str, str]:
        return (self.left, self.right)

    @property
    def subjects(self) -> tuple[str, str]:
        return (nk.party(self.party_type, self.left), nk.party(self.party_type, self.right))


def score_pair(a: Party, b: Party, shared_references: int) -> tuple[Decimal, dict[str, object]]:
    name_a, location_a = normalize_name(a.name)
    name_b, location_b = normalize_name(b.name)
    features: dict[str, object] = {
        "name_similarity": _similarity(name_a, name_b),
        "address_similarity": _similarity(
            normalize_address(a.address_line1), normalize_address(b.address_line1)
        ),
        "postal_code_match": bool(a.postal_code and a.postal_code == b.postal_code),
        "email_domain_match": bool(
            _email_domain(a.email) and _email_domain(a.email) == _email_domain(b.email)
        ),
        "tax_id_match": bool(a.tax_id_last4 and a.tax_id_last4 == b.tax_id_last4),
        "tax_id_conflict": bool(
            a.tax_id_last4 and b.tax_id_last4 and a.tax_id_last4 != b.tax_id_last4
        ),
        "region_conflict": bool(
            a.region and b.region and (a.region, a.country) != (b.region, b.country)
        ),
        "location_conflict": location_a != location_b,
        "shared_document_reference": shared_references > 0,
        "shared_document_reference_count": shared_references,
    }
    total = Decimal(0)
    for feature, weight in WEIGHTS.items():
        value = features[feature]
        if isinstance(value, bool):
            total += weight if value else Decimal(0)
        elif isinstance(value, Decimal):
            total += weight * value
    score = min(Decimal(1), max(Decimal(0), total)).quantize(Decimal("0.0001"))
    return score, features


def _blocking_keys(party: Party) -> set[str]:
    name, _ = normalize_name(party.name)
    keys = {f"name:{name[:4]}"} if len(name) >= 4 else set()
    if party.tax_id_last4:
        keys.add(f"tax:{party.tax_id_last4}")
    if party.postal_code:
        number = normalize_address(party.address_line1).split(" ")[0]
        keys.add(f"addr:{party.postal_code}:{number}")
    domain = _email_domain(party.email)
    if domain:
        keys.add(f"email:{domain}")
    return keys


def find_candidates(
    parties: dict[str, Party],
    party_type: PartyType,
    shared_references: dict[frozenset[str], int],
    threshold: Decimal,
) -> list[Candidate]:
    blocks: dict[str, list[str]] = defaultdict(list)
    for code in sorted(parties):
        for key in _blocking_keys(parties[code]):
            blocks[key].append(code)
    pairs: set[tuple[str, str]] = set()
    for members in blocks.values():
        pairs.update(combinations(sorted(members), 2))
    for pair in shared_references:
        left, right = sorted(pair)
        if left in parties and right in parties:
            pairs.add((left, right))
    candidates = []
    for left, right in sorted(pairs):
        score, features = score_pair(
            parties[left], parties[right], shared_references.get(frozenset((left, right)), 0)
        )
        if score >= threshold:
            candidates.append(Candidate(party_type, left, right, score, features))
    return candidates


@dataclass(frozen=True, slots=True)
class Clusters:
    """Party code → cluster id (the survivor's code, or the party's own code)."""

    cluster_of: dict[str, str]
    decided_pairs: frozenset[frozenset[str]]

    def cluster(self, code: str) -> str:
        return self.cluster_of.get(code, code)


def build_clusters(decisions: list[EntityDecision], party_type: PartyType) -> Clusters:
    parent: dict[str, str] = {}

    def find(code: str) -> str:
        while parent.get(code, code) != code:
            code = parent[code]
        return code

    decided: set[frozenset[str]] = set()
    for decision in decisions:
        if decision.party_type is not party_type:
            continue
        for a, b in combinations(sorted(decision.members), 2):
            decided.add(frozenset((a, b)))
        if decision.decision == "same_entity" and decision.survivor is not None:
            root = find(decision.survivor)
            for member in decision.members:
                member_root = find(member)
                if member_root != root:
                    parent[member_root] = root
    cluster_of = {
        code: find(code) for code in set(parent) | {c for d in decisions for c in d.members}
    }
    return Clusters(cluster_of=cluster_of, decided_pairs=frozenset(decided))
