"""FC-01 static guard: financial code paths must not use binary floating point.

Scans the source of financial modules for float literals, ``float(...)`` calls and ``float``
annotations. Modules planned for later milestones are listed now so they are covered the moment
they exist; the test asserts that at least the M0 modules are present so it cannot pass vacuously.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "relay"

FINANCIAL_PATHS = [
    SRC / "core" / "money.py",
    SRC / "core" / "currency.py",
    SRC / "core" / "db_types.py",
    SRC / "core" / "hashing.py",
    # Planned modules (docs/architecture.md §3); scanned automatically once they exist.
    SRC / "canonical",
    SRC / "mapping",
    SRC / "pipeline",
    SRC / "validation",
    SRC / "reconciliation",
    SRC / "readiness",
    SRC / "issues",
    SRC / "engine",
    SRC / "imports",
    SRC / "mapping_sets",
    SRC / "ingestion",
]

# Non-financial float use, each with its reason.
EXEMPT = {
    SRC / "engine" / "entities.py": "name/address similarity ratios from difflib are not amounts",
}

REQUIRED_NOW = FINANCIAL_PATHS[:4]


def _python_files() -> list[Path]:
    files: list[Path] = []
    for path in FINANCIAL_PATHS:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(p for p in sorted(path.rglob("*.py")) if p not in EXEMPT)
    return files


def _float_usages(source: str) -> list[str]:
    problems: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            problems.append(f"line {node.lineno}: float literal {node.value!r}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "float"
        ):
            problems.append(f"line {node.lineno}: float() call")
        elif (
            isinstance(node, ast.Name)
            and node.id == "float"
            and not isinstance(getattr(node, "ctx", None), ast.Store)
        ):
            problems.append(f"line {node.lineno}: reference to float")
    return problems


# References to ``float`` that exist only to *reject* floats.
ALLOWED_REFERENCES = {
    ("money.py", "reference to float"),
    ("hashing.py", "reference to float"),
}


def test_m0_financial_modules_exist() -> None:
    for path in REQUIRED_NOW:
        assert path.is_file(), path


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_no_float_usage(path: Path) -> None:
    problems = [
        problem
        for problem in _float_usages(path.read_text(encoding="utf-8"))
        if (path.name, problem.split(": ", 1)[1]) not in ALLOWED_REFERENCES
    ]
    assert problems == [], f"{path}: {problems}"


def test_detector_catches_float_usage() -> None:
    assert _float_usages("x = 0.1")
    assert _float_usages("x = float('1.5')")
    assert _float_usages("def f(x: float) -> None: ...")
    assert not _float_usages("from decimal import Decimal\nx = Decimal('0.1')")
