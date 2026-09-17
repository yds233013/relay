"""The committed OpenAPI document matches the application (regenerate with `make openapi`)."""

from __future__ import annotations

from relay.api.openapi import OPENAPI_PATH, openapi_document


def test_committed_openapi_matches_the_application() -> None:
    assert OPENAPI_PATH.read_text(encoding="utf-8") == openapi_document()
