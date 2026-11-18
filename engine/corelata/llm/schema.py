"""The strict JSON-schema form every OpenAI-compatible server accepts for response_format.

OpenAI-family servers validate a `json_schema` response format and reject anything outside their
strict subset: every object must list every property in `required`, carry
`additionalProperties: false`, and must not use `default`. Pydantic emits none of that for fields
with defaults. `strict_json_schema` rewrites a model's schema into that subset without changing
what the parser accepts: a field with a default is still parsed the same way when the model
emits it, and nullable fields are already `anyOf [..., null]`. Servers that do not validate
(Ollama, vLLM, TGI, LM Studio) accept the stricter form unchanged.
"""

import copy
from typing import Any

_SUBSCHEMA_KEYS = ("anyOf", "oneOf", "allOf", "prefixItems")


def strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """A deep copy of `schema` in the strict subset. Idempotent."""
    out = copy.deepcopy(schema)
    _walk(out)
    return out


def _walk(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _walk(item)
        return
    if not isinstance(node, dict):
        return
    node.pop("default", None)
    props = node.get("properties")
    if isinstance(props, dict):
        node["additionalProperties"] = False
        node["required"] = list(props)
        for sub in props.values():
            _walk(sub)
    elif node.get("type") == "object" and "additionalProperties" not in node:
        node["additionalProperties"] = False
    for key in ("items", "additionalProperties", "not"):
        if isinstance(node.get(key), dict):
            _walk(node[key])
    for key in _SUBSCHEMA_KEYS:
        if isinstance(node.get(key), list):
            _walk(node[key])
    defs = node.get("$defs")
    if isinstance(defs, dict):
        for sub in defs.values():
            _walk(sub)
