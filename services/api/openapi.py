"""Write the API's OpenAPI schema for the web types: `python -m services.api.openapi`.
`web/lib/api.openapi.json` is committed; `npm run gen:types` turns it into `web/lib/api.gen.ts`."""

import json
import sys
from pathlib import Path
from typing import Any

from services.api.app import create_app

PATH = Path(__file__).resolve().parents[2] / "web/lib/api.openapi.json"


def schema() -> dict[str, Any]:
    spec: dict[str, Any] = create_app(None, "").openapi()  # type: ignore[arg-type]
    return spec


def text() -> str:
    return json.dumps(schema(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    PATH.write_text(text())
    sys.stdout.write(f"wrote {PATH}\n")
