"""How structured input is handed to agents: a marker line followed by pretty JSON."""

import json
from typing import Any

INPUT_MARKER = "INPUT_JSON:"


def render_input(payload: dict[str, Any]) -> str:
    return f"{INPUT_MARKER}\n{json.dumps(payload, ensure_ascii=False, indent=2)}"


def parse_input(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in messages:
        content = message.get("content") or ""
        if message.get("role") == "user" and INPUT_MARKER in content:
            return json.loads(content.split(INPUT_MARKER, 1)[1])
    raise ValueError(f"no {INPUT_MARKER} block in messages")
