"""Shared, session-scoped Brightwater scenarios (generation takes a few seconds)."""

from __future__ import annotations

import pytest

from relay_evaluation.brightwater.manifest import Manifest, load_manifest
from relay_scenarios.brightwater.clean import build_clean_universe
from relay_scenarios.brightwater.scenario import Scenario, build_scenario
from relay_scenarios.brightwater.universe import LegacyUniverse


@pytest.fixture(scope="session")
def clean_universe() -> LegacyUniverse:
    return build_clean_universe()


@pytest.fixture(scope="session")
def clean_scenario() -> Scenario:
    return build_scenario(defects=())


@pytest.fixture(scope="session")
def run1_scenario() -> Scenario:
    return build_scenario()


@pytest.fixture(scope="session")
def manifest() -> Manifest:
    return load_manifest()
