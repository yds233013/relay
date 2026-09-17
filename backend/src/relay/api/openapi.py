"""OpenAPI document export (committed to web/src/lib/api/openapi.json; CI fails on drift)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from relay.api.app import create_app
from relay.core.config import Settings

OPENAPI_PATH: Final = (
    Path(__file__).resolve().parents[4] / "web" / "src" / "lib" / "api" / "openapi.json"
)


def openapi_document() -> str:
    # The database URL is never connected to while generating the schema.
    settings = Settings(database_url="postgresql+psycopg://openapi@localhost/openapi")  # type: ignore[arg-type]
    return json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_text(openapi_document(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
