"""Write the OpenAPI document the web client is generated from. Usage:
python -m corelata_api.openapi ../schema/openapi.json"""

import json
import sys
from pathlib import Path
from typing import Any

from corelata.config import CorelataConfig

from corelata_api.app import create_app

# The document depends only on the routes and models, not on any setting.
_PLACEHOLDER: dict[str, Any] = {
    "backends": {},
    "models": {},
    "roles": {role: {"model": "-"} for role in ("gate", "writer", "conveyor", "auditor")},
}


def openapi_document() -> dict[str, Any]:
    app = create_app(CorelataConfig.model_validate(_PLACEHOLDER), Path("corelata.yaml"))
    return app.openapi()  # the served /api/openapi.json is this same document


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out = Path(args[0]) if args else Path("../schema/openapi.json")
    text = json.dumps(openapi_document(), indent=2, sort_keys=True, ensure_ascii=False)
    out.write_text(text + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
