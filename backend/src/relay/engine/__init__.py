"""Relay's deterministic engine: normalization, rules, reconciliation, entities and readiness.

Pure functions over in-memory inputs (docs/architecture.md §4). No database, no clock reads, no
network, no randomness. The engine knows nothing about any particular company or scenario.
"""
