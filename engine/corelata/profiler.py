"""`corelata profile extract` (spec §4.4, §6.5, §6.8): draft a team profile from example
reports. The profiler is the fifth role; it is never used in a run, and what it writes is a
draft a human must approve (`draft: true`)."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel

from corelata.config import ConfigError, CorelataConfig
from corelata.ingest.base import IngestError
from corelata.ingest.registry import check_supported
from corelata.ingest.units import make_source
from corelata.llm.agent import AgentRunner, CallLog
from corelata.llm.types import Backend
from corelata.prompts.library import PromptLibrary
from corelata.schema import ProfileDraft
from corelata.stages.context import estimate_tokens
from corelata.standards.loader import load_pack, resolve_profile
from corelata.standards.schema import (
    ItemLimits,
    LexiconAdditions,
    Profile,
    ProfileFormat,
    ProfileRules,
    ResolvedPack,
    RuleOverride,
    Severity,
    TemplateOverride,
)


@dataclass
class ExampleReport:
    name: str
    units: list[str]
    truncated: bool


def _shares(costs: list[int], budget: int) -> list[int]:
    """Split `budget` tokens over reports of the given sizes: a report that fits keeps all of its
    tokens, the rest is divided evenly among the longer ones (water-filling), and every report
    gets at least one token so one unit always survives."""
    shares = [0] * len(costs)
    remaining = budget
    pending = len(costs)
    for i in sorted(range(len(costs)), key=lambda i: costs[i]):
        shares[i] = max(min(costs[i], remaining // pending), 1)
        remaining = max(remaining - shares[i], 0)
        pending -= 1
    return shares


def read_examples(
    directory: Path, *, budget_tokens: int, bytes_per_token: float
) -> list[ExampleReport]:
    """Every regular, non-hidden file in `directory`, in name order, read through the ingestors
    and cut to a share of `budget_tokens` that favours long reports once the short ones are
    whole (at least one unit each). Unsupported or unreadable files raise IngestError naming the
    file, before any model call."""
    if not directory.is_dir():
        raise IngestError(f"not a directory: {directory}")
    files = sorted(p for p in directory.iterdir() if p.is_file() and not p.name.startswith("."))
    if not files:
        raise IngestError(f"no example reports in {directory}")
    for path in files:
        try:
            check_supported(path)
        except IngestError as e:  # the registry's message names the extension, not the file
            raise IngestError(f"{path.name}: {e}") from e
    sources = [make_source(f"ex{i}", path) for i, path in enumerate(files, 1)]
    costs = [
        [estimate_tokens(unit.text, bytes_per_token) for unit in source.units] for source in sources
    ]
    shares = _shares([sum(c) for c in costs], budget_tokens)
    reports: list[ExampleReport] = []
    for path, source, unit_costs, share in zip(files, sources, costs, shares, strict=True):
        units: list[str] = []
        spent = 0
        for unit, cost in zip(source.units, unit_costs, strict=True):
            if units and spent + cost > share:
                break
            units.append(unit.text)
            spent += cost
        reports.append(ExampleReport(path.name, units, truncated=len(units) < len(source.units)))
    return reports


def check_draft(draft: ProfileDraft, base: ResolvedPack) -> list[str]:
    """Problems the model must repair: unknown rule ids, a rule both disabled and overridden."""
    known = set(base.rule_ids())
    problems = [f"disable: unknown rule id '{r}'" for r in draft.disable if r not in known]
    # resolve() deletes each disabled rule, so a repeated id would fail to load
    seen: set[str] = set()
    for r in draft.disable:
        if r in seen and r in known:
            problems.append(f"disable: duplicate rule id '{r}'")
        seen.add(r)
    problems += [f"override: unknown rule id '{o.id}'" for o in draft.override if o.id not in known]
    both = sorted(set(draft.disable) & {o.id for o in draft.override})
    problems += [f"rule '{r}' is both disabled and overridden; choose one" for r in both]
    kj = draft.key_judgments
    if kj is not None and kj.min > kj.max:
        problems.append(f"key_judgments: min ({kj.min}) must not exceed max ({kj.max})")
    return problems


def _clean_text(text: str) -> str:
    """Model text as it goes into the profile: line breaks kept, every other control or
    non-printable character (NEL, U+2028, escapes, tabs) replaced by a space, ends stripped. The
    YAML dumper does not round-trip every such character (NEL, for one), and the writer compares
    markings byte for byte."""
    text = text.replace("\r\n", "\n")
    return "".join(c if c == "\n" or c.isprintable() else " " for c in text).strip()


def _new(items: list[str], known: list[str]) -> list[str]:
    seen = {k.strip().casefold() for k in known}
    out: list[str] = []
    for item in items:
        item = _clean_text(item)
        if item and item.casefold() not in seen:
            seen.add(item.casefold())
            out.append(item)
    return out


def to_profile(draft: ProfileDraft, base: ResolvedPack, *, name: str, extends: str) -> Profile:
    template = None
    if draft.key_judgments is not None or draft.analysis_max_words is not None:
        template = TemplateOverride(
            key_judgments=ItemLimits(min=draft.key_judgments.min, max=draft.key_judgments.max)
            if draft.key_judgments is not None
            else None,
            analysis_max_words=draft.analysis_max_words,
        )
    return Profile(
        name=name,
        extends=extends,
        draft=True,
        rules=ProfileRules(
            disable=list(draft.disable),
            override=[
                RuleOverride(id=o.id, severity=Severity(o.severity))
                for i, o in enumerate(draft.override)
                if o.id not in {p.id for p in draft.override[:i]}  # first occurrence wins
            ],
        ),
        template=template,
        tone=_clean_text(draft.tone),
        format=ProfileFormat(heading_style=draft.heading_style),
        lexicon=LexiconAdditions(
            handling_markings=_new(draft.handling_markings, base.lexicon.handling_markings),
            source_descriptors=_new(draft.source_descriptors, base.lexicon.source_descriptors),
        ),
    )


class ProfileExtraction(BaseModel):
    profile: Profile
    observations: list[str]
    examples: list[str]  # file names, in the order shown to the model
    model: str  # the model key of the profiler role


async def extract_profile(
    cfg: CorelataConfig,
    *,
    backends: dict[str, Backend],
    prompts: PromptLibrary,
    log: CallLog,
    examples: list[ExampleReport],
    name: str,
    extends: str,
    packs_dir: Path | None,
) -> ProfileExtraction:
    if cfg.roles.profiler is None:
        raise ConfigError(
            "roles.profiler is not configured; add `profiler: {model: <key>}` under roles"
        )
    base = load_pack(extends, packs_dir=packs_dir)
    model_key = cfg.roles.model_for("profiler")
    runner = AgentRunner(cfg, backends, prompts, log)
    draft = await runner.run(
        role="profiler",
        model_key=model_key,
        prompt_id="profiler",
        prompt_vars={},
        payload={
            "task": "profiler",
            "pack": {
                "name": base.name,
                "version": base.version,
                "rule_ids": base.rule_ids(),
                "rules": [
                    {"id": r.id, "title": r.title, "severity": r.severity.value} for r in base.rules
                ],
                "template": base.template.model_dump(mode="json"),
                "lexicon": {
                    "handling_markings": base.lexicon.handling_markings,
                    "source_descriptors": base.lexicon.source_descriptors,
                    "likelihood_terms": sorted(base.lexicon.terms()),
                },
            },
            "reports": [
                {"name": r.name, "units": r.units, "truncated": r.truncated} for r in examples
            ],
        },
        output_type=ProfileDraft,
        validate=lambda d: check_draft(d, base),
    )
    profile = to_profile(draft, base, name=name, extends=extends)
    resolve_profile(profile, packs_dir=packs_dir)  # a draft that cannot load is a bug here
    return ProfileExtraction(
        profile=profile,
        observations=draft.observations,
        examples=[r.name for r in examples],
        model=model_key,
    )


def profile_yaml(extraction: ProfileExtraction, *, written_at: datetime) -> str:
    """Commented YAML: provenance and observations for the reviewer, then the profile with
    `name`, `extends`, `draft` first and defaults left out."""
    p = extraction.profile

    def line(text: str) -> str:  # a header text is one comment line, whatever the model wrote
        text = "".join(c if c.isprintable() or c.isspace() else " " for c in text)
        return " ".join(text.split())

    head = [
        f"# Draft profile written by `corelata profile extract` on {written_at:%Y-%m-%d} "
        f"from {len(extraction.examples)} example reports:",
        *[f"#   - {line(name)}" for name in extraction.examples],
        f"# Model: {line(extraction.model)}. Observations:",
        *[f"#   - {line(o)}" for o in extraction.observations],
        "# Review every line, then set `draft: false` to let runs use this profile.",
    ]
    body = {"name": p.name, "extends": p.extends, "draft": True}
    rest = p.model_dump(mode="json", exclude_defaults=True, exclude={"name", "extends", "draft"})
    body.update(rest)
    text = "\n".join(head) + "\n\n" + yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
    if Profile.model_validate(yaml.safe_load(text)) != p:  # a bug guard, not a user error
        raise ValueError("profile_yaml: output does not round-trip")
    return text
