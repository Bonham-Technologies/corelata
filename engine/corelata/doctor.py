"""`corelata doctor` (spec §10.2): check an installation end to end and say how to fix what is
wrong. Every check reports pass, warn or fail with a plain-language fix. Adapted from Coglossa:
no scorer or language tiers; a standards-pack check instead."""

import asyncio
import contextlib
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from corelata.config import (
    ConfigError,
    CorelataConfig,
    EvidenceQuotes,
    ModelConfig,
    StructuredOutput,
    load_config,
)
from corelata.ingest import ocr
from corelata.integrations.coglossa import CoglossaClient
from corelata.llm.agent import (
    build_request,
    extract_json,
    rejection_errors,
    repair_messages,
    request_messages,
)
from corelata.llm.payload import render_input
from corelata.llm.registry import build_backends
from corelata.llm.types import (
    Backend,
    BackendError,
    ChatMessage,
    ChatRequest,
    ContextOverflowError,
    OutputTruncatedError,
    TransientBackendError,
)
from corelata.pipeline import load_run_pack
from corelata.prompts.check import validate_prompts
from corelata.prompts.library import PromptLibrary
from corelata.schema import (
    CheckStatus,
    DoctorCheck,
    DoctorReport,
    GateVerdict,
    Quote,
    ReportBody,
)
from corelata.stages.audit import auditor_payload
from corelata.stages.audit_schema import audit_output_type, to_audit_output
from corelata.standards.loader import PACK_NAME_MAX_LENGTH, PACK_NAME_PATTERN, PackError, list_packs
from corelata.storage import (
    ProbeLeftover,
    StorageError,
    build_storage,
    describe_storage,
    storage_call,
)
from corelata.store.db import redact
from corelata.store.migrate import connect_error, migration_state
from corelata.worker.execute import DB_ERRORS

PING_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
# The structured-output probe (R-M12-3) asks for the gate's real output type through the request
# builder every stage uses, so the server sees the same strict schema a run sends. The input is
# gate-shaped, so the synthetic responder (the fake server, the demo stack) answers it.
PROBE_SYSTEM = (
    "You judge whether a source passage supports an analyst's statement.\n"
    "Return your verdict on INPUT_JSON.value_statement against INPUT_JSON.units as one JSON object."
)
PROBE_PAYLOAD: dict[str, Any] = {
    "task": "gate",
    "value_statement": "The port of Tarvos expanded its container capacity in 2026.",
    "digests": [],
    "units": [
        {
            "ref": "probe/u1",
            "text": "Tarvos opened a second container terminal in May 2026, adding 70 percent "
            "to its container capacity.",
            "locator": "para 1",
            "source": "probe.txt",
        }
    ],
}
# The auditor probe (R-M13-1) sends the auditor's real by-rule schema for the configured pack:
# one required property per rule (17 for icd203-base), with these two units and two claims as
# its `UnitRef` and `ClaimId` enums. The input is auditor-shaped (`stages.audit.auditor_payload`),
# so the synthetic responder answers it.
AUDIT_PROBE_SYSTEM = (
    "You audit a draft intelligence report against every rule in INPUT_JSON.rules.\n"
    "Return one finding per rule, keyed by rule id, and a short summary, as one JSON object."
)
AUDIT_PROBE_UNITS: list[dict[str, str]] = [
    {"ref": "probe/u1", "text": PROBE_PAYLOAD["units"][0]["text"]},
    {
        "ref": "probe/u2",
        "text": "The terminal was financed by a loan from the Kelmar state development bank.",
    },
]
AUDIT_PROBE_CLAIMS = ["c1", "c2"]
AUDIT_PROBE_DRAFT = ReportBody.model_validate(
    {
        "title": "Tarvos container capacity",
        "handling_marking": "UNCLASSIFIED",
        "key_judgments": [
            {
                "text": "Tarvos expanded its container capacity in 2026.",
                "confidence": "high",
                "claim_ids": ["c1", "c2"],
            }
        ],
        "scope_note": "One port notice; nothing set aside.",
        "sources": [{"source_id": "probe", "descriptor": "official government publication"}],
        "analysis": [
            {
                "heading": "Capacity",
                "paragraphs": [
                    {
                        "text": "A second terminal opened in May 2026 with state bank funding.",
                        "claim_ids": ["c1", "c2"],
                    }
                ],
            }
        ],
        "alternatives": [],
        "gaps_and_indicators": ["Throughput figures for the new terminal."],
        "claims": [
            {
                "id": "c1",
                "text": "Tarvos opened a second container terminal in May 2026.",
                "kind": "fact",
                "evidence": ["probe/u1"],
            },
            {
                "id": "c2",
                "text": "A state development bank financed the terminal.",
                "kind": "fact",
                "evidence": ["probe/u2"],
            },
        ],
    }
)
# CRL-93: with `pipeline.evidence_quotes` on, a run's draft quotes its units and the auditor
# reads each quote next to its unit (`stages.audit.cited_unit_payload`); the probe does too.
AUDIT_PROBE_QUOTES: dict[str, dict[str, str]] = {
    "c1": {"ref": "probe/u1", "text": "Tarvos opened a second container terminal in May 2026"},
    "c2": {"ref": "probe/u2", "text": "financed by a loan from the Kelmar state development bank"},
}


def audit_probe_input(quoting: bool) -> tuple[ReportBody, list[dict[str, Any]]]:
    """The auditor probe's draft and cited units; with `quoting` each claim quotes its unit."""
    if not quoting:
        return AUDIT_PROBE_DRAFT, AUDIT_PROBE_UNITS
    claims = [
        c.model_copy(update={"quotes": [Quote(**AUDIT_PROBE_QUOTES[c.id])]})
        for c in AUDIT_PROBE_DRAFT.claims
    ]
    units = [
        {
            **u,
            "quotes": [
                {"claim_id": cid, "text": q["text"]}
                for cid, q in AUDIT_PROBE_QUOTES.items()
                if q["ref"] == u["ref"]
            ],
        }
        for u in AUDIT_PROBE_UNITS
    ]
    return AUDIT_PROBE_DRAFT.model_copy(update={"claims": claims}), units


PING_OK = "test completion succeeded"
ERROR_CHARS = 200  # a server's error text in a check message is cut to this
SIMILAR_MAX = 5  # served ids a missing model's fix suggests

_ORDER = {CheckStatus.PASS: 0, CheckStatus.WARN: 1, CheckStatus.FAIL: 2}

BackendsFactory = Callable[[CorelataConfig], dict[str, Backend]]


def _check(name: str, status: CheckStatus, message: str, fix: str = "") -> DoctorCheck:
    return DoctorCheck(name=name, status=status, message=message, fix=fix)


def _crashed(name: str, e: Exception) -> DoctorCheck:
    return _check(name, CheckStatus.FAIL, f"internal error: {type(e).__name__}: {e}")


def _cut(text: str, limit: int = ERROR_CHARS) -> str:
    """One line of at most `limit` characters: a server's error body can be long."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _prefix(model_id: str) -> str:
    """The part before the first `/` or `:` (`openai` of `openai/gpt-4.1`, `phi4-mini` of
    `phi4-mini:3.8b`)."""
    return re.split(r"[/:]", model_id, maxsplit=1)[0]


def _served(name: str, served: list[str]) -> bool:
    """Ollama lists `phi4-mini:latest` for a configured `phi4-mini`, and a run works."""
    return name in served or f"{name}:latest" in served


def _similar(model_id: str, served: list[str]) -> list[str]:
    """Up to SIMILAR_MAX served ids with the same prefix as `model_id`, ignoring case (R-M17-4),
    sorted (R-M12-2)."""
    prefix = _prefix(model_id).casefold()
    return sorted({s for s in served if _prefix(s).casefold() == prefix})[:SIMILAR_MAX]


def _guard(name: str, fn: Callable[[], DoctorCheck]) -> DoctorCheck:
    """A diagnostic reports every check: an unexpected error becomes that check's failure."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return _crashed(name, e)


async def _aguard(name: str, fn: Callable[[], Awaitable[DoctorCheck]]) -> DoctorCheck:
    try:
        return await fn()
    except Exception as e:  # noqa: BLE001
        return _crashed(name, e)


async def run_doctor(
    config_path: Path,
    *,
    probe: bool = True,
    backends_factory: BackendsFactory = build_backends,
    coglossa_transport: httpx.AsyncBaseTransport | None = None,
) -> DoctorReport:
    try:
        # off the event loop, like every filesystem walk below: the API runs doctor (CRL-113)
        cfg, issues = await asyncio.to_thread(load_config, config_path)
    except ConfigError as e:
        return DoctorReport.of(
            [_check("config", CheckStatus.FAIL, str(e), "edit the file; see corelata.example.yaml")]
        )
    checks = [_check("config", CheckStatus.PASS, f"{config_path} is valid")]
    checks += [_check("config", CheckStatus.WARN, i.message) for i in issues]
    checks.append(await asyncio.to_thread(_guard, "prompts", lambda: _prompts(cfg)))
    checks.append(await asyncio.to_thread(_guard, "pack", lambda: _pack(cfg)))
    checks.append(await asyncio.to_thread(_guard, "pack names", lambda: _pack_names(cfg)))
    checks += await _backends(cfg, probe, backends_factory)
    checks.append(await _aguard("database", lambda: _database(cfg)))
    # off the event loop: the API runs doctor for Settings, and S3 is a network call
    checks.append(await storage_call(_guard, "storage", lambda: _storage(cfg)))
    checks.append(await _aguard("coglossa", lambda: _coglossa(cfg, probe, coglossa_transport)))
    # off the event loop: it starts tesseract, and the API runs doctor for Settings
    checks.append(await asyncio.to_thread(_guard, "ocr", lambda: _ocr(cfg)))
    checks += _hosted(cfg)
    return DoctorReport.of(checks)


def _hosted(cfg: CorelataConfig) -> list[DoctorCheck]:
    """The hosted demo's settings (M19), each a line only when it is set. validate_config has
    already failed the config check for a variable that is not set; the kick URL is never called
    here, since a call would start a worker."""
    checks = []
    if cfg.worker.kick_url:
        checks.append(
            _check("worker", CheckStatus.PASS, f"kicks {cfg.worker.kick_url} when a job is queued")
        )
    if cfg.auth.proxy_secret_env:
        checks.append(
            _check(
                "auth",
                CheckStatus.PASS,
                f"requests without the X-Corelata-Proxy-Secret header ({cfg.auth.proxy_secret_env})"
                " are refused, /api/health excepted",
            )
        )
    return checks


async def _coglossa(
    cfg: CorelataConfig, probe: bool, transport: httpx.AsyncBaseTransport | None
) -> DoctorCheck:
    integration = cfg.integrations.coglossa
    if integration is None:
        return _check("coglossa", CheckStatus.PASS, "integrations.coglossa not configured")
    if not probe:
        return _check("coglossa", CheckStatus.PASS, f"configured: {integration.base_url}")
    var = integration.api_key_env
    if var and os.environ.get(var) == "":
        return _check(
            "coglossa",
            CheckStatus.FAIL,
            f"{var} is empty",
            f"set {var} to Coglossa's API key in the API and worker environment",
        )
    url = integration.base_url.rstrip("/") + "/api/health"
    try:
        headers = CoglossaClient(integration)._headers(None)
        async with httpx.AsyncClient(transport=transport, timeout=10.0) as c:
            response = await c.get(url, headers=headers)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        return _check(
            "coglossa",
            CheckStatus.FAIL,
            f"cannot reach Coglossa at {integration.base_url}: {str(e) or type(e).__name__}",
            "check integrations.coglossa.base_url and that Coglossa is up",
        )
    if response.status_code in (401, 403):
        return _check(
            "coglossa",
            CheckStatus.FAIL,
            f"{url} answered {response.status_code}: Coglossa rejected the key "
            f"({var or 'no api_key_env is set'})",
            "check the API key and integrations.coglossa.api_key_env",
        )
    if response.status_code != 200:
        return _check(
            "coglossa",
            CheckStatus.FAIL,
            f"{url} answered {response.status_code}",
            "check integrations.coglossa.base_url: it should be Coglossa's root URL",
        )
    return _check("coglossa", CheckStatus.PASS, f"Coglossa at {integration.base_url} answers")


def _ocr(cfg: CorelataConfig) -> DoctorCheck:
    """ingest.ocr (CRL-95): whether Tesseract is installed, which languages it has, and a warning
    when OCR is on without it or without a configured language."""
    mode = cfg.ingest.ocr
    wanted = cfg.ingest.ocr_languages
    install = (
        "install tesseract-ocr and a tesseract-ocr-<language> pack for each of "
        f"{', '.join(wanted)} (the app image has them; operator guide, Scanned PDFs)"
    )
    if ocr.tesseract_path() is None:
        if mode == "off":
            return _check("ocr", CheckStatus.PASS, "ingest.ocr is off; tesseract is not installed")
        return _check(
            "ocr",
            CheckStatus.WARN,
            "ingest.ocr is auto but tesseract is not installed: uploads with scanned PDF pages "
            "will be refused",
            f"{install}, or set ingest.ocr: off",
        )
    try:
        version = ocr.tesseract_version()
        languages = [lang for lang in ocr.installed_languages() if lang != "osd"]
    except ocr.OcrError as e:
        return _check(
            "ocr", CheckStatus.WARN, f"tesseract is installed but does not run: {e}", install
        )
    found = f"tesseract {version} with languages {', '.join(languages) or 'none'}"
    missing = [lang for lang in wanted if lang not in languages]
    if mode == "auto" and missing:
        return _check(
            "ocr",
            CheckStatus.WARN,
            f"ingest.ocr is auto but {found} lacks {', '.join(missing)}: uploads with scanned "
            "PDF pages will be refused",
            f"add the tesseract-ocr-<language> pack for {', '.join(missing)} to the image "
            "(operator guide, Scanned PDFs), or remove it from ingest.ocr_languages",
        )
    if mode == "off":
        return _check("ocr", CheckStatus.PASS, f"ingest.ocr is off; {found}")
    return _check("ocr", CheckStatus.PASS, f"ingest.ocr is auto ({', '.join(wanted)}); {found}")


def _prompts(cfg: CorelataConfig) -> DoctorCheck:
    try:
        validate_prompts(cfg, PromptLibrary(cfg.prompts_dir))
    except ConfigError as e:
        return _check(
            "prompts", CheckStatus.FAIL, str(e), "fix or remove the override in prompts_dir"
        )
    return _check("prompts", CheckStatus.PASS, "every prompt renders")


def _pack(cfg: CorelataConfig) -> DoctorCheck:
    try:
        pack = load_run_pack(cfg, None)
    except PackError as e:
        return _check(
            "pack",
            CheckStatus.FAIL,
            str(e),
            "fix standards.default_pack / default_profile or the pack directory",
        )
    profile = f" with profile {pack.profile}" if pack.profile else ""
    return _check(
        "pack", CheckStatus.PASS, f"{pack.name} {pack.version}{profile}: {len(pack.rules)} rules"
    )


def _addressable(name: str) -> bool:
    return len(name) <= PACK_NAME_MAX_LENGTH and PACK_NAME_PATTERN.match(name) is not None


def _pack_names(cfg: CorelataConfig) -> DoctorCheck:
    """A pack directory the API cannot address loads fine but has no `/api/packs/{name}` routes,
    so the Audit tab shows rule ids instead of titles for runs on it (CRL-16, R-M9-7). The rules
    are the route's own: the pattern and the length limit (R-M10-4)."""
    names = [p.name for p in list_packs(cfg.standards.packs_dir)]
    bad = sorted(name for name in names if not _addressable(name))
    if not bad:
        return _check("pack names", CheckStatus.PASS, "every pack directory is addressable")
    noun = "directory" if len(bad) == 1 else "directories"
    return _check(
        "pack names",
        CheckStatus.WARN,
        f"{len(bad)} pack {noun} cannot be addressed through the API: {', '.join(bad)}",
        f"rename to lowercase letters, digits and hyphens ({PACK_NAME_PATTERN.pattern}), at most "
        f"{PACK_NAME_MAX_LENGTH} characters, and point standards.default_pack at the new name",
    )


async def _backends(
    cfg: CorelataConfig, probe: bool, factory: BackendsFactory
) -> list[DoctorCheck]:
    try:
        backends = factory(cfg)
    except ConfigError as e:
        return [_check("backends", CheckStatus.FAIL, str(e), "fix the backend kind")]
    except Exception as e:  # noqa: BLE001
        return [_crashed("backends", e)]
    checks: list[DoctorCheck] = []
    try:
        for name, backend in backends.items():
            try:
                checks += await _backend(cfg, name, backend, probe)
            except Exception as e:  # noqa: BLE001
                checks.append(_crashed(f"backend {name}", e))
    finally:
        for backend in backends.values():
            with contextlib.suppress(Exception):
                await backend.aclose()
    return checks


async def _backend(
    cfg: CorelataConfig, name: str, backend: Backend, probe: bool
) -> list[DoctorCheck]:
    label = f"backend {name}"
    try:
        served = await backend.list_models()
    except BackendError as e:
        return [
            _check(
                label,
                CheckStatus.FAIL,
                f"unreachable: {_cut(str(e))}",
                "check the URL and that the server is up",
            )
        ]
    # R-M12-2: a count and the configured models' state, never the served list (468 ids on
    # OpenRouter)
    state = [
        f"{key} → {m.name or key} {'found' if _served(m.name or key, served) else 'missing'}"
        for key, m in cfg.models.items()
        if m.backend == name
    ]
    noun = "model" if len(served) == 1 else "models"
    summary = "; ".join([f"serves {len(served)} {noun}", *state])
    checks = [_check(label, CheckStatus.PASS, summary)]
    for key, model in cfg.models.items():
        if model.backend != name:
            continue
        try:
            check, pinged = await _model(key, model, backend, served, probe)
        except Exception as e:  # noqa: BLE001
            check, pinged = _crashed(f"model {key}", e), False
        checks.append(check)
        # R-M13-1: the auditor's schema is the largest a run sends; probe it on its own line
        # once the model has answered the test completion
        if key == cfg.roles.auditor.model and pinged:
            audit = f"model {key} auditor schema"
            checks.append(
                await _aguard(
                    audit, lambda a=audit, k=key, m=model: _auditor_schema(cfg, a, k, m, backend)
                )
            )
    return checks


def _ping(model_id: str, mode: StructuredOutput) -> ChatRequest:
    return ChatRequest(
        model=model_id,
        messages=[
            ChatMessage(role="system", content='Reply with the JSON object {"ok": true}.'),
            ChatMessage(role="user", content=render_input({"task": "ping"})),
        ],
        schema_name="Ping",
        json_schema=PING_SCHEMA,
        structured_output=mode,
        temperature=0,
        max_tokens=50,
    )


async def _model(
    key: str, model: ModelConfig, backend: Backend, served: list[str], probe: bool
) -> tuple[DoctorCheck, bool]:
    """The `model <key>` check and whether the model answered the test completion, which is what
    decides if the model can take a further probe (the auditor's schema line)."""
    label = f"model {key}"
    model_id = model.name or key
    if not _served(model_id, served):
        similar = _similar(model_id, served)
        fix = (
            f"set models.{key}.name to a served id, such as: {', '.join(similar)}"
            if similar
            else f"set models.{key}.name to a served id; see the server's model list"
        )
        return (
            _check(
                label,
                CheckStatus.FAIL,
                f"'{model_id}' is not served by backend {model.backend}",
                fix,
            ),
            False,
        )
    if not probe:
        return _check(label, CheckStatus.PASS, "served"), False
    parts: list[DoctorCheck] = []
    try:
        await backend.chat(_ping(model_id, StructuredOutput.NONE))
        parts.append(_check(label, CheckStatus.PASS, PING_OK))
    except OutputTruncatedError:  # cut at max_tokens: the model answered
        parts.append(_check(label, CheckStatus.PASS, PING_OK))
    except BackendError as e:
        parts.append(
            _check(
                label,
                CheckStatus.FAIL,
                f"test completion failed: {_cut(str(e))}",
                "check the model id and server logs",
            )
        )
    pinged = parts[0].status is CheckStatus.PASS
    if model.structured_output is not StructuredOutput.NONE and pinged:
        parts.append(await _structured(label, key, model, backend))
    worst = max(parts, key=lambda c: _ORDER[c.status])
    fix = next((c.fix for c in parts if c.status is not CheckStatus.PASS), "")
    return _check(label, worst.status, "; ".join(c.message for c in parts), fix), pinged


def _fixes(key: str, mode: StructuredOutput) -> tuple[str, str]:
    """The fix for a rejected request and for a reply that is not the requested JSON (R-M12-9,
    R-M13-8). A `none` model sends no response format, so its server cannot reject a schema."""
    schema_fix = f"set models.{key}.structured_output to json_object or none"
    if mode is StructuredOutput.JSON_OBJECT:
        return "check the model id and server logs", (
            f"set models.{key}.structured_output to none, or pick a model that follows a "
            "JSON schema"
        )
    if mode is StructuredOutput.NONE:
        return "check the model id and server logs", (
            "pick a model that follows a JSON schema given in the prompt"
        )
    return schema_fix, schema_fix


async def _probe(
    label: str,
    key: str,
    model: ModelConfig,
    backend: Backend,
    output_type: type[BaseModel],
    system: str,
    payload: dict[str, Any],
    parse: Callable[[str], object],
    *,
    works: str,
    needs: str,
) -> DoctorCheck:
    """One structured call exactly as a run makes it: the stages' request builder, so the backend
    applies `strict_json_schema` as in a run, no `max_tokens` of its own (the model's cap if it
    has one, else none), and the one repair turn a run gives a rejected reply, built by the same
    code (R-M15-5). Passes when `parse` accepts the first reply, warns when it accepts the
    repaired one, fails when it accepts neither."""
    name = output_type.__name__
    article = "an" if name[0] in "AEIOU" else "a"
    mode = model.structured_output.value
    schema = output_type.model_json_schema()
    messages = request_messages(system, payload, model, schema)
    first = await _send(label, key, model, backend, output_type, schema, messages, needs)
    if isinstance(first, DoctorCheck):
        return first
    error = _rejected(parse, first)
    if error is None:
        return _check(label, CheckStatus.PASS, f"{mode} output works ({works})")
    # R-M15-5: a run repairs a rejected reply once (llm/agent.py); so does the probe
    repaired = repair_messages(messages, first, rejection_errors(error))
    second = await _send(
        label, key, model, backend, output_type, schema, repaired, needs, repair_turn=True
    )
    if isinstance(second, DoctorCheck):
        return second
    error = _rejected(parse, second)
    if error is None:
        return _check(
            label,
            CheckStatus.WARN,
            f"{mode} output works after one repair turn ({works})",
            f"nothing to change for a run, which repairs the reply the same way; every structured "
            f"call on models.{key} may cost a second request",
        )
    first_error = error.errors()[0]
    where = ".".join(str(p) for p in first_error["loc"]) or "<root>"
    return _check(
        label,
        CheckStatus.FAIL,
        f"the server did not return the requested JSON ({mode}), even after one repair turn: "
        + _cut(f"not {article} {name}: {where}: {first_error['msg']}"),
        _fixes(key, model.structured_output)[1],
    )


def _rejected(parse: Callable[[str], object], content: str) -> ValidationError | None:
    try:
        parse(extract_json(content))
    except ValidationError as e:
        return e
    return None


async def _send(
    label: str,
    key: str,
    model: ModelConfig,
    backend: Backend,
    output_type: type[BaseModel],
    schema: dict[str, Any],
    messages: list[ChatMessage],
    needs: str,
    *,
    repair_turn: bool = False,
) -> str | DoctorCheck:
    """The reply's text, or the failed check a run would also fail on: a reply cut at the output
    limit, or a backend error (no repair turn follows either, as in a run)."""
    name = output_type.__name__
    mode = model.structured_output.value
    request = build_request(key, model, output_type, schema, messages)
    try:
        return (await backend.chat(request)).content
    except OutputTruncatedError:
        if request.max_tokens is None:  # no cap of ours: the server's own default cut the reply
            return _check(
                label,
                CheckStatus.FAIL,
                f"the {name} reply was cut by the server's default output limit",
                f"set models.{key}.max_output_tokens above the server's default: {needs}",
            )
        return _check(
            label,
            CheckStatus.FAIL,
            f"the {name} reply was cut at max_tokens={request.max_tokens}",
            f"raise models.{key}.max_output_tokens or unset it: {needs}",
        )
    except BackendError as e:
        # R-M13-11: the advice follows the cause, not only a rejected schema
        turn = " on the repair turn" if repair_turn else ""
        failed = f"{mode} request failed{turn}: {_cut(str(e))}"
        if isinstance(e, ContextOverflowError):
            fix = (
                "the request exceeds the model's context: raise the server's context length, "
                f"or set models.{key}.context_window to the server's real length; json_schema "
                "sends the schema out of band, json_object and none spell it into the prompt"
            )
        elif isinstance(e, TransientBackendError):
            fix = f"check the server logs; on a timeout raise backends.{model.backend}.timeout_s"
        elif repair_turn:  # the schema was accepted on the first turn: do not blame it (R-M15-21)
            fix = "check the model id and server logs"
        else:
            fix = _fixes(key, model.structured_output)[0]
        return _check(label, CheckStatus.FAIL, failed, fix)


async def _structured(label: str, key: str, model: ModelConfig, backend: Backend) -> DoctorCheck:
    """R-M12-3: the real GateVerdict schema; passes only on a reply that parses as one."""
    return await _probe(
        label,
        key,
        model,
        backend,
        GateVerdict,
        PROBE_SYSTEM,
        PROBE_PAYLOAD,
        GateVerdict.model_validate_json,
        works="GateVerdict",
        needs="a GateVerdict needs about 150 tokens plus any reasoning the model emits first",
    )


async def _auditor_schema(
    cfg: CorelataConfig, label: str, key: str, model: ModelConfig, backend: Backend
) -> DoctorCheck:
    """R-M13-1: the auditor's by-rule schema for the configured pack, the largest schema a run
    sends (one required property per rule); passes only on a reply that converts to an
    `AuditOutput`. On `none` it runs too: the schema is then spelled in the prompt."""
    try:
        pack = load_run_pack(cfg, None)
    except PackError as e:
        return _check(
            label,
            CheckStatus.FAIL,
            f"cannot build the AuditByRule schema: {_cut(str(e))}",
            "fix the pack check first",
        )
    refs = [u["ref"] for u in AUDIT_PROBE_UNITS]
    output_type = audit_output_type(pack, refs, AUDIT_PROBE_CLAIMS)
    draft, units = audit_probe_input(cfg.pipeline.evidence_quotes is not EvidenceQuotes.OFF)
    payload = auditor_payload(pack, draft, units, PROBE_PAYLOAD["value_statement"])
    rules = len(pack.rules)
    noun = "rule" if rules == 1 else "rules"
    return await _probe(
        label,
        key,
        model,
        backend,
        output_type,
        AUDIT_PROBE_SYSTEM,
        payload,
        lambda text: to_audit_output(output_type.model_validate_json(text), pack),
        works=f"AuditByRule, {rules} {noun}",
        needs=f"an AuditByRule needs about 60 tokens per rule ({rules} here) plus any reasoning "
        "the model emits first",
    )


async def _database(cfg: CorelataConfig) -> DoctorCheck:
    url = cfg.database.url()
    env = cfg.database.url_env
    if url is None:
        return _check(
            "database",
            CheckStatus.WARN,
            f"{env} is not set: needed by corelata worker and the queued commands, "
            "not by corelata run",
            f"set {env}=postgresql://user:password@host:5432/corelata",
        )
    try:
        state = await asyncio.to_thread(migration_state, url)
    except ConfigError as e:
        return _check("database", CheckStatus.FAIL, str(e), f"fix {env}")
    except DB_ERRORS as e:
        return _check(
            "database",
            CheckStatus.FAIL,
            str(connect_error(url, e)),
            "check the URL, the credentials and that Postgres is running",
        )
    if not state.up_to_date:
        return _check(
            "database",
            CheckStatus.FAIL,
            f"schema at revision {state.current or 'none'}, expected {state.head}",
            "run corelata migrate",
        )
    return _check("database", CheckStatus.PASS, f"{redact(url)} at revision {state.head}")


def _storage(cfg: CorelataConfig) -> DoctorCheck:
    fix = (
        "fix storage (bucket, endpoint_url, keys)"
        if cfg.storage.kind == "s3"
        else "fix storage.path or its permissions"
    )
    try:
        build_storage(cfg.storage).check_writable()
    except ProbeLeftover as e:
        return _check(
            "storage",
            CheckStatus.WARN,
            f"{describe_storage(cfg.storage)} is writable, but {e}",
            f"let the storage keys delete objects (Corelata cleans up files with them), then "
            f"delete {e.key} by hand",
        )
    except StorageError as e:
        return _check("storage", CheckStatus.FAIL, str(e), fix)
    return _check("storage", CheckStatus.PASS, f"{describe_storage(cfg.storage)} is writable")
