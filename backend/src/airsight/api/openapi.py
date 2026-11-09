"""The API contract: docs/openapi.json, generated from the code (ADR 0008).

tests/test_openapi.py fails when the code and the committed file disagree, so every change to
the API shows up as a diff of this file in the PR, where a breaking change is easy to spot.
Within /v1 changes must be additive: new endpoints, optional parameters and fields only.

Regenerate after changing the API, from backend/:
    uv run python -m airsight.api.openapi
"""

import json
from pathlib import Path
from typing import Any

from airsight.api.main import create_app
from airsight.api.store import MemoryStore

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "docs" / "openapi.json"


def current_schema() -> dict[str, Any]:
    return create_app(store=MemoryStore()).openapi()


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    SCHEMA_PATH.write_text(render(current_schema()))
    print(f"Wrote {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
