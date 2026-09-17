"""Determinism (criterion 5), runtime boundary (criterion 6), no answer leakage (criterion 7)."""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import re
import subprocess

import pytest

from relay_evaluation.brightwater import resolution
from relay_evaluation.paths import BRIGHTWATER_FIXTURES, BRIGHTWATER_REEXPORT, REPO_ROOT
from relay_scenarios.brightwater.clean import build_clean_universe
from relay_scenarios.brightwater.exports import export_all
from relay_scenarios.brightwater.injectors import ALL_DEFECTS, apply_defects
from relay_scenarios.brightwater.scenario import (
    CHECKSUM_FILE,
    Scenario,
    checksum_manifest,
    reexport_files,
)

BACKEND = REPO_ROOT / "backend"
RUNTIME_SRC = BACKEND / "src" / "relay"


def test_generation_is_byte_identical_across_independent_builds() -> None:
    first = export_all(apply_defects(build_clean_universe(), ALL_DEFECTS))
    second = export_all(apply_defects(build_clean_universe(), ALL_DEFECTS))
    assert first == second


def test_generation_is_identical_in_a_separate_process(run1_scenario: Scenario) -> None:
    code = (
        "import hashlib,json;from relay_scenarios.brightwater.scenario import build_scenario;"
        "s=build_scenario();"
        "print(json.dumps({p:hashlib.sha256(c).hexdigest() for p,c in s.files.items()}))"
    )
    # Fixed command, no external input: the test needs a genuinely separate interpreter.
    output = subprocess.run(  # noqa: S603
        ["uv", "run", "python", "-c", code],  # noqa: S607
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(output.stdout) == {
        p: hashlib.sha256(c).hexdigest() for p, c in run1_scenario.files.items()
    }


def test_different_seed_changes_generated_values_but_not_documented_facts() -> None:
    other = export_all(apply_defects(build_clean_universe(7), ALL_DEFECTS))
    default = export_all(apply_defects(build_clean_universe(), ALL_DEFECTS))
    assert (
        other["ledgerpro/ledgerpro_gl_detail_2026H1.csv"]
        != default["ledgerpro/ledgerpro_gl_detail_2026H1.csv"]
    )
    for text in (b"JE-AP-20455", b"03/14/2062", b"INV-10301", b"PCP-88231"):
        assert (
            text
            in other["ledgerpro/ledgerpro_gl_detail_2026H1.csv"]
            + other["ledgerpro/ledgerpro_invoices.csv"]
            + other["ledgerpro/ledgerpro_bills.csv"]
        )


def test_committed_fixtures_match_generation(run1_scenario: Scenario) -> None:
    expected = {**run1_scenario.files, CHECKSUM_FILE: checksum_manifest(run1_scenario.files)}
    actual = {
        p.relative_to(BRIGHTWATER_FIXTURES).as_posix(): p.read_bytes()
        for p in sorted(BRIGHTWATER_FIXTURES.rglob("*"))
        if p.is_file()
    }
    assert sorted(actual) == sorted(expected), "run `make demo-data`"
    assert [p for p in expected if expected[p] != actual[p]] == []


# ------------------------------------------------------------------------------ answer leakage
LEAK_PATTERNS = [
    r"\bDS-\d",
    r"\bTN-\d",
    r"\bdefect",
    r"\binject",
    r"\btrap\b",
    # Evaluation vocabulary, not the adjective: an inactive customer is named "Golden Hollow Foods".
    r"\bgolden[ _-]*(manifest|truth|file|answer|result)",
    r"\bmanifest\b",
    r"\bexpected\b",
    r"\banswer",
    r"\btest\b",
    r"\bfake\b",
    r"\bdummy\b",
    r"\bbroken\b",
    r"\bbad_",
    r"\bbad (row|record|vendor|customer|invoice|bill|data|entry)",
    r"\bseeded\b",
    r"\bplanted\b",
    r"\bscenario\b",
    r"\bduplicate\b",
    r"\bdo not merge\b",
]


def test_committed_reexports_match_generation(run1_scenario: Scenario) -> None:
    files = reexport_files(run1_scenario)
    expected = {**files, CHECKSUM_FILE: checksum_manifest(files)}
    actual = {
        p.relative_to(BRIGHTWATER_REEXPORT).as_posix(): p.read_bytes()
        for p in sorted(BRIGHTWATER_REEXPORT.rglob("*"))
        if p.is_file()
    }
    assert actual == expected, "run `make demo-data`"
    # The same unfiltered exports the documented resolution uses (evaluation).
    documented = resolution.reexported_files(run1_scenario)
    assert all(documented[path] == content for path, content in files.items())


def test_source_fixtures_do_not_leak_answers(run1_scenario: Scenario) -> None:
    for path, content in {**run1_scenario.files, **reexport_files(run1_scenario)}.items():
        encoding = "cp1252" if path.startswith("ledgerpro/") else "utf-8-sig"
        text = content.decode(encoding)
        for pattern in LEAK_PATTERNS:
            assert not re.search(pattern, path, re.IGNORECASE), (path, pattern)
            match = re.search(pattern, text, re.IGNORECASE)
            if match is not None:
                context = text[max(0, match.start() - 60) : match.end() + 60]
                pytest.fail(f"{path}: {pattern} matched in {context!r}")


def test_fixture_directory_contains_no_evaluation_truth() -> None:
    names = [
        p.name.lower()
        for root in (BRIGHTWATER_FIXTURES, BRIGHTWATER_REEXPORT)
        for p in root.rglob("*")
    ]
    assert not [n for n in names if "manifest" in n or "expected" in n or n.endswith(".toml")]


# ------------------------------------------------------------------------------ runtime boundary
FORBIDDEN_RUNTIME_TEXT = [
    r"\bDS-\d\d\b",
    r"\bTN-\d\d\b",
    r"brightwater",
    r"golden",
    r"relay_scenarios",
    r"relay_evaluation",
    r"evaluation/",
    r"JE-AP-20455",
    r"JE-2026-0\d\d\d",
    r"INV-10\d\d\d",
    r"\bB-2\d\d\d\d\b",
    r"\bV-1\d\d\d\b",
    r"\bC-0\d\d\d\b",
    r"PMT-3\d\d\d\d",
    r"PAY-D-7\d\d\d",
    r"Pacific Coast",
    r"Green Valley",
    r"Alpenkost",
    r"Rose City",
    r"Cedar & Salt",
    r"Summit Refrigeration",
    r"Portland General",
    r"LedgerPro",
    r"14,?862\.50",
    r"38,?400",
    r"9,?340\.00",
    r"1,?184\.62",
    r"2,?315\.77",
    r"21,?730",
    r"412,?906",
    r"427,?101",
]


def _scanned_files() -> list[pathlib.Path]:
    """Everything that ships as product: the runtime package, its migrations, and the web app.

    Not just ``*.py``: a JSON, SQL or TypeScript file could carry the same knowledge, and the web
    app is as much the product as the engine is.
    """
    roots = [RUNTIME_SRC, BACKEND / "migrations", REPO_ROOT / "web" / "src"]
    suffixes = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".sql", ".toml", ".yaml", ".yml"}
    return sorted(
        path
        for root in roots
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in suffixes
        and "__pycache__" not in path.parts
        and "node_modules" not in path.parts
        # Generated from the API's own schema; it names endpoints, never scenario data.
        and path.name not in {"openapi.json", "schema.d.ts"}
    )


def test_the_boundary_scan_covers_the_whole_product() -> None:
    scanned = {str(path.relative_to(REPO_ROOT)) for path in _scanned_files()}
    assert len(scanned) > 150
    assert any(p.startswith("backend/src/relay/engine/") for p in scanned)
    assert any(p.startswith("backend/migrations/") for p in scanned)
    assert any(p.startswith("web/src/app/") for p in scanned)


def test_runtime_code_has_no_scenario_specific_knowledge() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _scanned_files():
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_RUNTIME_TEXT:
            offenders.extend(
                (str(path.relative_to(REPO_ROOT)), match.group(0))
                for match in re.finditer(pattern, text, re.IGNORECASE)
            )
    assert offenders == []


def test_runtime_code_does_not_import_generators_or_evaluation() -> None:
    offenders: list[tuple[str, str]] = []
    for path in sorted(RUNTIME_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [
                (str(path), n)
                for n in names
                if n.split(".")[0] in {"relay_scenarios", "relay_evaluation"}
            ]
    assert offenders == []


def test_boundary_detector_catches_violations() -> None:
    sample = "from relay_evaluation.brightwater import manifest\nif number == 'JE-AP-20455': pass\n"
    hits = [p for p in FORBIDDEN_RUNTIME_TEXT if re.search(p, sample, re.IGNORECASE)]
    assert r"relay_evaluation" in hits
    assert r"JE-AP-20455" in hits


def test_import_contracts_hold() -> None:
    result = subprocess.run(
        ["uv", "run", "lint-imports"],  # noqa: S607 - fixed developer tool invocation
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert (
        "Runtime code never imports scenario generators or evaluation truth KEPT" in result.stdout
    )
    assert "Scenario generators never read evaluation truth KEPT" in result.stdout
