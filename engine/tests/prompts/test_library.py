from pathlib import Path

import pytest
from jinja2 import Environment, StrictUndefined, UndefinedError

from corelata.config import ConfigError
from corelata.prompts.check import _CHECKS, run_prompt_ids, validate_prompts
from corelata.prompts.library import PromptLibrary, PromptNotFoundError

# CRL-93 moved the prompts that mention quotes to a new version, and CRL-97 those that mention
# earlier reports; the previous ones stay for the record (a trace names the version it ran with)
LATEST = {"writer": 3, "conveyor": 2, "auditor": 4}
# The versions sent before quotes existed (CRL-93) and before project memory existed (CRL-97)
BEFORE_QUOTES = {"writer": 1, "conveyor": 1, "auditor": 2}
BEFORE_PRIOR_REPORTS = {"writer": 2, "auditor": 3}


def _render_file(prompt_id: str, version: int, **variables: object) -> str:
    path = PromptLibrary().resolve(prompt_id)[1].with_name(f"v{version}.j2")
    template = Environment(undefined=StrictUndefined).from_string(path.read_text("utf-8"))
    return template.render(**variables).strip()


@pytest.mark.parametrize(("prompt_id", "variables"), _CHECKS)
def test_builtin_templates_render(prompt_id, variables):
    rendered = PromptLibrary().render(prompt_id, **variables)
    assert rendered.id == prompt_id and rendered.version == LATEST.get(prompt_id, 1)
    assert "JSON" in rendered.text
    assert "{{" not in rendered.text and "{%" not in rendered.text


@pytest.mark.parametrize(
    ("prompt_id", "variables"),
    [
        ("writer", {"tone": "t", "section_order": ["title"], "iteration": 1, "extra_guidance": ""}),
        ("conveyor", {"tone": "", "heading_style": "plain", "findings": [{"x": 1}]}),
        ("auditor", {}),
    ],
)
def test_evidence_quotes_off_renders_the_prompt_unchanged(prompt_id, variables):
    """CRL-93: with `off` a model reads what the prompt said before quotes existed."""
    library = PromptLibrary()
    before = _render_file(prompt_id, BEFORE_QUOTES[prompt_id], **variables)
    assert library.render(prompt_id, **variables, evidence_quotes="off").text == before
    assert library.render(prompt_id, **variables).text == before
    assert "quotes" not in before
    assert "quotes" in library.render(prompt_id, **variables, evidence_quotes="required").text


@pytest.mark.parametrize("evidence_quotes", ["off", "optional", "required"])
@pytest.mark.parametrize(
    ("prompt_id", "variables"),
    [
        (
            "writer",
            {"tone": "t", "section_order": ["title"], "iteration": 0, "extra_guidance": "g"},
        ),
        ("writer", {"tone": "", "section_order": ["title"], "iteration": 1, "extra_guidance": ""}),
        ("auditor", {}),
    ],
)
def test_without_prior_reports_the_prompt_renders_as_the_previous_version(
    prompt_id, variables, evidence_quotes
):
    """CRL-97: a run that read no earlier report (`max_reports: 0`, a project with none, a run
    outside a project) sends what the prompt said before project memory existed."""
    library = PromptLibrary()
    variables = {**variables, "evidence_quotes": evidence_quotes}
    before = _render_file(prompt_id, BEFORE_PRIOR_REPORTS[prompt_id], **variables)
    assert library.render(prompt_id, **variables, prior_reports=False).text == before
    assert library.render(prompt_id, **variables).text == before
    assert "prior_reports" not in before
    with_prior = library.render(prompt_id, **variables, prior_reports=True).text
    assert "INPUT_JSON.prior_reports" in with_prior and "changes_from_previous" in with_prior


def test_gate_modes_differ():
    verify = PromptLibrary().render("gate", mode="verify", tone="").text
    discover = PromptLibrary().render("gate", mode="discover", tone="").text
    assert "supported" in verify and "candidates" in discover and "supported" not in discover


def test_writer_iteration_one_mentions_findings():
    text = (
        PromptLibrary()
        .render("writer", tone="", section_order=["title"], iteration=1, extra_guidance="")
        .text
    )
    assert "prior_draft" in text


def test_missing_variable_fails_loudly():
    with pytest.raises(UndefinedError):
        PromptLibrary().render("writer", tone="")


def test_override_dir_wins(tmp_path):
    (tmp_path / "auditor").mkdir()
    (tmp_path / "auditor" / "v2.j2").write_text("custom auditor JSON", encoding="utf-8")
    lib = PromptLibrary(tmp_path)
    assert lib.render("auditor").text == "custom auditor JSON"
    assert lib.versions(["auditor", "gate"]) == {"auditor": 2, "gate": 1}


def test_unknown_prompt():
    with pytest.raises(PromptNotFoundError):
        PromptLibrary().resolve("nope")


def test_validate_prompts_reports_broken_override(make_config, tmp_path):
    (tmp_path / "digest").mkdir()
    (tmp_path / "digest" / "v1.j2").write_text("{{ undefined_thing }}", encoding="utf-8")
    with pytest.raises(ConfigError, match="prompt 'digest' is unusable"):
        validate_prompts(make_config(), PromptLibrary(tmp_path))
    validate_prompts(make_config(), PromptLibrary())
    assert run_prompt_ids() == ["gate", "discover", "digest", "writer", "conveyor", "auditor"]
    assert Path("corelata/prompts/templates/ping").exists() is False
