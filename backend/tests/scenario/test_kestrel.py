"""The generalization test: a second fictional company, the same engine, no engine changes.

Kestrel Instruments Ltd shares nothing with Brightwater but the accounting: a different legacy
system, delimiter, encoding, date and amount conventions, chart of accounts, fiscal year, functional
currency, parties, documents and defects. If the engine needed to know anything about Brightwater to
work, it fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

from relay_evaluation.kestrel.verify import fixtures_root, format_report, verify
from relay_scenarios.kestrel.defects import ALL_DEFECTS
from relay_scenarios.kestrel.scenario import (
    CHECKSUM_FILE,
    build_scenario,
    checksum_manifest,
)


def test_the_engine_meets_every_kestrel_expectation() -> None:
    report = verify()
    assert report.failures == [], format_report(report)
    assert len(report.checks) == 31


def test_generation_is_deterministic() -> None:
    assert build_scenario().files == build_scenario().files


def test_committed_fixtures_match_a_fresh_generation() -> None:
    root = fixtures_root()
    scenario = build_scenario()
    expected = {**scenario.files, CHECKSUM_FILE: checksum_manifest(scenario.files)}
    actual = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    assert actual == expected


def test_source_files_reveal_no_answers() -> None:
    """A defect must be found by the rules, not read off the file that carries it."""
    forbidden = [
        r"\bKS-0\d\b",
        r"defect",
        r"planted",
        r"seeded",
        r"expected",
        r"unbalanced",
        r"unmapped",
        r"quarantin",
        r"mismatch",
        r"discrepan",
    ]
    offenders: list[tuple[str, str]] = []
    for name, content in build_scenario().files.items():
        text = content.decode("utf-8", errors="replace")
        offenders += [
            (name, match.group(0))
            for pattern in forbidden
            for match in re.finditer(pattern, text, re.IGNORECASE)
        ]
    assert offenders == []


def test_every_defect_reaches_the_exported_files() -> None:
    """``apply_defects`` raises if a defect cannot be applied, so a silent no-op is impossible."""
    clean = build_scenario(defects=()).files
    for defect in ALL_DEFECTS:
        scenario = build_scenario(defects=(defect,))
        changed = [name for name, content in scenario.files.items() if clean[name] != content]
        assert changed, defect
        assert scenario.planted == (defect,)


def test_the_exports_do_not_look_like_brightwaters() -> None:
    """The point of this company: different conventions on disk, exercising the same engine."""
    journal = build_scenario(defects=()).files["tallyworks/journal.csv"].decode("utf-8")
    header = journal.splitlines()[0]
    assert header.startswith("﻿")  # UTF-8 byte-order mark
    assert ";" in header
    assert "," not in header
    assert re.search(r"\n\d\d\d\d;", journal)  # rows start with the legacy account code
    assert re.search(r";\d\d\.\d\d\.2026;", journal)  # DD.MM.YYYY
    assert re.search(r";-?\d{1,3}(\.\d\d\d)*,\d\d;", journal)  # 1.234,56


def test_expectations_are_not_readable_by_runtime_code() -> None:
    expected = Path(__file__).resolve().parents[3] / "evaluation" / "kestrel" / "expected.toml"
    assert expected.exists()
    assert "evaluation" not in fixtures_root().parts
