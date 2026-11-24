"""Fail fast on unusable prompts: test-render every prompt a run uses, before any model call."""

from jinja2 import TemplateError

from corelata.config import ConfigError, CorelataConfig
from corelata.prompts.library import PromptLibrary, PromptNotFoundError

_CHECKS: list[tuple[str, dict[str, object]]] = [
    ("gate", {"mode": "verify", "tone": ""}),
    ("gate", {"mode": "discover", "tone": "x"}),
    ("discover", {"audience_hint": "", "tone": ""}),
    ("digest", {}),
    ("writer", {"tone": "", "section_order": ["title"], "iteration": 0, "extra_guidance": ""}),
    ("writer", {"tone": "x", "section_order": ["title"], "iteration": 1, "extra_guidance": "g"}),
    (
        "writer",
        {
            "tone": "",
            "section_order": ["title"],
            "iteration": 0,
            "extra_guidance": "",
            "evidence_quotes": "required",
        },
    ),
    (
        "writer",
        {
            "tone": "",
            "section_order": ["title"],
            "iteration": 0,
            "extra_guidance": "",
            "evidence_quotes": "off",
            "prior_reports": True,
        },
    ),
    (
        "writer",
        {
            "tone": "",
            "section_order": ["title", "sources", "source_summary"],
            "iteration": 0,
            "extra_guidance": "",
            "source_details": True,
            "source_summary": True,
        },
    ),
    ("conveyor", {"tone": "", "heading_style": "plain", "findings": []}),
    (
        "conveyor",
        {
            "tone": "",
            "heading_style": "plain",
            "findings": [],
            "source_details": True,
            "source_summary": True,
        },
    ),
    (
        "conveyor",
        {"tone": "", "heading_style": "plain", "findings": [], "evidence_quotes": "optional"},
    ),
    ("auditor", {}),
    ("auditor", {"evidence_quotes": "required"}),
    ("auditor", {"evidence_quotes": "off", "prior_reports": True}),
    ("auditor", {"evidence_quotes": "required", "checked_report": True}),
    ("profiler", {}),
    ("structurer", {"section_order": ["title"], "evidence_quotes": "off"}),
    ("structurer", {"section_order": ["title"], "evidence_quotes": "required"}),
    ("structurer", {"section_order": ["title"], "evidence_quotes": "optional"}),
]


def run_prompt_ids() -> list[str]:
    return ["gate", "discover", "digest", "writer", "conveyor", "auditor"]


def check_prompt_ids() -> list[str]:
    """The prompts a check run uses (CRL-94), as its trace's `prompt_versions` lists them."""
    return ["digest", "structurer", "auditor"]


def validate_prompts(cfg: CorelataConfig, prompts: PromptLibrary) -> None:
    for prompt_id, variables in _CHECKS:
        try:
            prompts.render(prompt_id, **variables)
        except (PromptNotFoundError, TemplateError, OSError, UnicodeDecodeError) as e:
            raise ConfigError(f"prompt '{prompt_id}' is unusable: {e}") from e
