"""Relay Canonical Accounting Model.

Typed, immutable records that every source system is normalized into. The model is deliberately
able to represent *defective* data (an unbalanced entry, an impossible date, an unknown party):
accounting invariants are checked by rules and reconciliations, never by the record types.

Identifiers are opaque. Chronology comes from business dates, never from identifier magnitude.
"""
