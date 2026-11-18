from pathlib import Path

import pytest
from jinja2 import Environment, StrictUndefined, UndefinedError

from corelata.config import ConfigError
from corelata.prompts.check import _CHECKS, run_prompt_ids, validate_prompts
from corelata.prompts.library import PromptLibrary, PromptNotFoundError

# CRL-93 moved the prompts that mention quotes to a new version, CRL-97 those that mention
# earlier reports to the next, CRL-95 those that explain the OCR flag to the one after, and
# CRL-96 those that mention source details and the source summary to the one after that; the
# previous ones stay for the record (a trace names the version it ran with)
LATEST = {"writer": 5, "conveyor": 3, "auditor": 5}
QUOTES_VERSION = {"writer": 2, "conveyor": 2, "auditor": 3}
PRIOR_REPORTS_VERSION = {"writer": 3, "auditor": 4}
OCR_VERSION = {"writer": 4, "auditor": 5}
SOURCE_DETAILS_VERSION = {"writer": 5, "conveyor": 3}
_ARGS = {
    "writer": {"tone": "t", "section_order": ["title"], "iteration": 1, "extra_guidance": ""},
    "conveyor": {"tone": "", "heading_style": "plain", "findings": [{"x": 1}]},
    "auditor": {},
}


def _render_version(prompt_id: str, version: int, **variables: object) -> str:
    """One built-in version of a prompt, rendered as the library renders the latest."""
    _, path = PromptLibrary().resolve(prompt_id)
    text = path.with_name(f"v{version}.j2").read_text(encoding="utf-8")
    return Environment(undefined=StrictUndefined).from_string(text).render(**variables).strip()


@pytest.mark.parametrize(("prompt_id", "variables"), _CHECKS)
def test_builtin_templates_render(prompt_id, variables):
    rendered = PromptLibrary().render(prompt_id, **variables)
    assert rendered.id == prompt_id and rendered.version == LATEST.get(prompt_id, 1)
    assert "JSON" in rendered.text
    assert "{{" not in rendered.text and "{%" not in rendered.text


@pytest.mark.parametrize("prompt_id", sorted(QUOTES_VERSION))
def test_evidence_quotes_off_renders_the_prompt_unchanged(prompt_id):
    """CRL-93: with `off` a model reads what the previous version of the prompt said, the one
    sent before quotes existed."""
    variables = _ARGS[prompt_id]
    version = QUOTES_VERSION[prompt_id]
    before = _render_version(prompt_id, version - 1, **variables)
    assert _render_version(prompt_id, version, **variables, evidence_quotes="off") == before
    assert _render_version(prompt_id, version, **variables) == before
    assert "quotes" not in before
    assert "quotes" in _render_version(prompt_id, version, **variables, evidence_quotes="required")


@pytest.mark.parametrize("prompt_id", sorted(QUOTES_VERSION))
@pytest.mark.parametrize("prior_reports", [None, False, True])
def test_the_library_serves_the_latest_version(prompt_id, prior_reports):
    library = PromptLibrary()
    extra = {} if prior_reports is None else {"prior_reports": prior_reports}
    variables = _ARGS[prompt_id] | extra
    for quotes in ("off", "optional", "required"):
        latest = _render_version(prompt_id, LATEST[prompt_id], **variables, evidence_quotes=quotes)
        assert library.render(prompt_id, **variables, evidence_quotes=quotes).text == latest


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
    variables = {**variables, "evidence_quotes": evidence_quotes}
    version = PRIOR_REPORTS_VERSION[prompt_id]
    before = _render_version(prompt_id, version - 1, **variables)
    assert _render_version(prompt_id, version, **variables, prior_reports=False) == before
    assert _render_version(prompt_id, version, **variables) == before
    assert "prior_reports" not in before
    with_prior = _render_version(prompt_id, version, **variables, prior_reports=True)
    assert "INPUT_JSON.prior_reports" in with_prior and "changes_from_previous" in with_prior
    latest = PromptLibrary().render(prompt_id, **variables, prior_reports=True).text
    assert "INPUT_JSON.prior_reports" in latest and "changes_from_previous" in latest


@pytest.mark.parametrize("prompt_id", sorted(OCR_VERSION))
@pytest.mark.parametrize("quotes", [None, "off", "optional", "required"])
@pytest.mark.parametrize("prior_reports", [None, False, True])
def test_ocr_version_only_adds_the_ocr_wording(prompt_id, quotes, prior_reports):
    """CRL-95: the OCR version is the previous one, quotes and earlier reports and all, with one
    line extended by what the "ocr" flag on a unit means."""
    variables = (
        _ARGS[prompt_id]
        | ({} if quotes is None else {"evidence_quotes": quotes})
        | ({} if prior_reports is None else {"prior_reports": prior_reports})
    )
    version = OCR_VERSION[prompt_id]
    before = _render_version(prompt_id, version - 1, **variables).splitlines()
    after = _render_version(prompt_id, version, **variables).splitlines()
    assert len(before) == len(after)
    changed = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    assert len(changed) == 1
    b, a = changed[0]
    assert '"ocr": true' in a and '"ocr"' not in b and len(a) > len(b)


@pytest.mark.parametrize("prompt_id", sorted(SOURCE_DETAILS_VERSION))
@pytest.mark.parametrize("quotes", [None, "off", "required"])
@pytest.mark.parametrize("prior_reports", [None, False, True])
def test_without_source_details_or_summary_the_prompt_is_the_previous_version(
    prompt_id, quotes, prior_reports
):
    """CRL-96: a pack that asks for neither renders what the previous version said, quotes and
    earlier reports and all, so only the trace's prompt version tells such a run from one made
    before."""
    variables = (
        _ARGS[prompt_id]
        | ({} if quotes is None else {"evidence_quotes": quotes})
        | ({} if prior_reports is None else {"prior_reports": prior_reports})
    )
    version = SOURCE_DETAILS_VERSION[prompt_id]
    before = _render_version(prompt_id, version - 1, **variables)
    off = {"source_details": False, "source_summary": False}
    assert _render_version(prompt_id, version, **variables, **off) == before
    assert _render_version(prompt_id, version, **variables) == before
    on = (
        PromptLibrary()
        .render(prompt_id, **variables, source_details=True, source_summary=True)
        .text
    )
    assert "date_of_information" in on and "access" in on and "conflicting_sources" in on
    details_only = _render_version(
        prompt_id, version, **variables, source_details=True, source_summary=False
    )
    assert "date_of_information" in details_only and "conflicting_sources" not in details_only


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


def test_writer_and_auditor_explain_the_ocr_flag():
    """CRL-95: a unit OCR read carries "ocr": true; both prompts say what it means."""
    lib = PromptLibrary()
    writer = lib.render("writer", tone="", section_order=["title"], iteration=0, extra_guidance="")
    auditor = lib.render("auditor")
    for text in (writer.text, auditor.text):
        assert '"ocr": true' in text and "scanned page" in text
    assert "icd203.tc.1" in auditor.text and "reliability note" in writer.text
