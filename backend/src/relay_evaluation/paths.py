"""Locations of evaluation data in the repository."""

from __future__ import annotations

from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
EVALUATION_DIR: Final = REPO_ROOT / "evaluation"
FIXTURES_DIR: Final = REPO_ROOT / "fixtures"
BRIGHTWATER_MANIFEST: Final = EVALUATION_DIR / "brightwater" / "golden_manifest.toml"
BRIGHTWATER_FIXTURES: Final = FIXTURES_DIR / "demo" / "brightwater"
BRIGHTWATER_REEXPORT: Final = FIXTURES_DIR / "demo" / "brightwater_reexport"
