from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from corelata.config import ConfigError
from corelata.ingest.base import IngestError
from corelata.llm.agent import CallLog, StructuredOutputError
from corelata.profiler import (
    ProfileExtraction,
    _shares,
    check_draft,
    extract_profile,
    profile_yaml,
    read_examples,
    to_profile,
)
from corelata.prompts.library import PromptLibrary
from corelata.schema import DraftLimits, DraftRuleOverride, ProfileDraft
from corelata.standards.loader import load_pack, resolve_profile
from corelata.standards.schema import Profile
from corelata.testing.fake_backend import FakeBackend

REPORT = [
    "UNCLASSIFIED//FOUO",
    "## 1. Key Judgments",
    "BLUF: Varna's container capacity expansion matters to shippers.",
    "We assess it is likely that traffic keeps rising.",
    "## 2. Analysis",
    "The port of Varna expanded its container capacity in 2025.",
]


@pytest.fixture
def examples_dir(tmp_path) -> Path:
    d = tmp_path / "examples"
    d.mkdir()
    for i in range(1, 4):
        (d / f"report-{i}.md").write_text("\n\n".join(REPORT), encoding="utf-8")
    (d / ".DS_Store").write_bytes(b"\x00")  # hidden files are skipped
    return d


@pytest.fixture
def profiler_config(make_config):
    return make_config(
        roles={
            "gate": {"model": "model-a"},
            "writer": {"model": "model-a"},
            "conveyor": {"model": "model-b"},
            "auditor": {"model": "model-b"},
            "profiler": {"model": "model-b"},
        }
    )


def test_read_examples_in_name_order_within_budget(examples_dir):
    reports = read_examples(examples_dir, budget_tokens=100_000, bytes_per_token=2.5)
    assert [r.name for r in reports] == ["report-1.md", "report-2.md", "report-3.md"]
    assert reports[0].units[0] == "UNCLASSIFIED//FOUO" and not reports[0].truncated
    assert len(reports[0].units) == 6
    small = read_examples(examples_dir, budget_tokens=60, bytes_per_token=2.5)
    assert all(r.truncated for r in small)
    assert all(1 <= len(r.units) < 6 for r in small)  # at least one unit per report, always


def test_read_examples_errors(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(IngestError, match="no example reports in"):
        read_examples(empty, budget_tokens=100, bytes_per_token=2.5)
    (empty / "a.xyz").write_text("x")
    with pytest.raises(IngestError, match=r"a\.xyz"):
        read_examples(empty, budget_tokens=100, bytes_per_token=2.5)
    with pytest.raises(IngestError, match="not a directory"):
        read_examples(tmp_path / "missing", budget_tokens=100, bytes_per_token=2.5)


def test_check_draft_names_every_problem():
    base = load_pack("icd203-base")
    draft = ProfileDraft(
        observations=["x"],
        tone="t",
        disable=["icd203.tc.4", "nope.rule.1"],
        override=[
            DraftRuleOverride(id="icd203.tc.4", severity="minor"),
            DraftRuleOverride(id="bogus.id", severity="major"),
        ],
    )
    problems = check_draft(draft, base)
    assert problems == [
        "disable: unknown rule id 'nope.rule.1'",
        "override: unknown rule id 'bogus.id'",
        "rule 'icd203.tc.4' is both disabled and overridden; choose one",
    ]
    assert check_draft(ProfileDraft(observations=["x"], tone="t"), base) == []


def test_check_draft_key_judgment_bounds_and_duplicates():
    base = load_pack("icd203-base")
    draft = ProfileDraft(
        observations=["x"],
        tone="t",
        key_judgments=DraftLimits(min=5, max=3),
        disable=["nope.rule.1", "icd203.tc.4", "icd203.tc.4"],
    )
    assert check_draft(draft, base) == [
        "disable: unknown rule id 'nope.rule.1'",
        "disable: duplicate rule id 'icd203.tc.4'",
        "key_judgments: min (5) must not exceed max (3)",
    ]


def test_to_profile_keeps_the_first_of_duplicate_overrides_and_skips_blanks():
    base = load_pack("icd203-base")
    draft = ProfileDraft(
        observations=["x"],
        tone="t",
        handling_markings=["  ", "", "NEW//MARK", " new//mark", "NEW//MARK "],
        source_descriptors=[" "],
        override=[
            DraftRuleOverride(id="icd203.tc.9", severity="major"),
            DraftRuleOverride(id="icd203.tc.9", severity="minor"),
        ],
    )
    profile = to_profile(draft, base, name="n", extends="icd203-base")
    assert [(o.id, o.severity) for o in profile.rules.override] == [("icd203.tc.9", "major")]
    assert profile.lexicon.handling_markings == ["NEW//MARK"]
    assert profile.lexicon.source_descriptors == []


def test_to_profile_is_a_draft_that_resolves():
    base = load_pack("icd203-base")
    draft = ProfileDraft(
        observations=["x"],
        tone="Be brief.",
        key_judgments=DraftLimits(min=1, max=3),
        analysis_max_words=800,
        heading_style="numbered",
        handling_markings=[
            "UNCLASSIFIED",
            "UNCLASSIFIED//FOUO",
            " UNCLASSIFIED//FOUO",
            "UNCLASSIFIED//FOUO ",
            "unclassified//fouo",
        ],
        source_descriptors=["a liaison service"],
        disable=["icd203.tc.4"],
        override=[DraftRuleOverride(id="icd203.tc.9", severity="major")],
    )
    profile = to_profile(draft, base, name="team-east", extends="icd203-base")
    assert profile.draft is True and profile.name == "team-east"
    assert profile.tone == "Be brief." and profile.format.heading_style == "numbered"
    assert profile.template is not None and profile.template.key_judgments.max == 3
    assert profile.template.analysis_max_words == 800
    assert profile.lexicon.handling_markings == [
        "UNCLASSIFIED//FOUO"
    ]  # already-known dropped, deduped
    assert profile.rules.disable == ["icd203.tc.4"]
    assert (
        profile.rules.override[0].id == "icd203.tc.9"
        and profile.rules.override[0].severity == "major"
    )
    resolved = resolve_profile(profile)
    assert "icd203.tc.4" not in resolved.rule_ids()
    assert resolved.rule("icd203.tc.9").severity == "major"
    assert resolved.profile == "team-east"
    bare = to_profile(
        ProfileDraft(observations=["x"], tone="t"), base, name="n", extends="icd203-base"
    )
    assert bare.template is None and bare.lexicon.handling_markings == []


def _extraction(observations, examples, tone, model="strong", markings=()):
    base = load_pack("icd203-base")
    draft = ProfileDraft(
        observations=["x"],
        tone=tone,
        heading_style="numbered",
        handling_markings=list(markings),
        source_descriptors=list(markings),
    )
    return ProfileExtraction(
        profile=to_profile(draft, base, name="team-east", extends="icd203-base"),
        observations=observations,
        examples=examples,
        model=model,
    )


def test_profile_yaml_collapses_multiline_header_text():
    extraction = _extraction(["A.\nB.", "C.\r\n  D."], ["we\nird.md"], "t", model="m\nk")
    text = profile_yaml(extraction, written_at=datetime(2026, 10, 14, tzinfo=UTC))
    head, body = text.split("\n\n", 1)
    assert all(line.startswith("#") for line in head.splitlines())
    assert "#   - A. B." in head and "#   - C. D." in head and "#   - we ird.md" in head
    assert Profile.model_validate(yaml.safe_load(body)) == extraction.profile


def test_profile_yaml_refuses_output_that_does_not_round_trip(monkeypatch):
    extraction = _extraction(["x"], ["a.md"], "t")
    monkeypatch.setattr(
        yaml, "safe_load", lambda _text: {**extraction.profile.model_dump(), "tone": "other"}
    )
    with pytest.raises(ValueError, match="does not round-trip"):
        profile_yaml(extraction, written_at=datetime(2026, 10, 14, tzinfo=UTC))


@settings(max_examples=100, deadline=None)
@given(
    observations=st.lists(st.text(), max_size=3),
    examples=st.lists(st.text(), max_size=3),
    tone=st.text(min_size=1),
    markings=st.lists(st.text(), max_size=2),
)
def test_profile_yaml_always_loads_back_to_an_equal_profile(observations, examples, tone, markings):
    extraction = _extraction(observations, examples, tone, markings=markings)
    assert (
        "\x85" not in extraction.profile.tone
    )  # NEL does not survive PyYAML; cleaned on the way in
    text = profile_yaml(extraction, written_at=datetime(2026, 10, 14, tzinfo=UTC))
    head, body = text.split("\n\n", 1)
    assert all(line.startswith("#") for line in head.splitlines())
    assert Profile.model_validate(yaml.safe_load(body)) == extraction.profile


async def test_extract_profile_end_to_end(profiler_config, examples_dir):
    examples = read_examples(examples_dir, budget_tokens=16000, bytes_per_token=2.5)
    backend = FakeBackend(name="fake")
    log = CallLog()
    extraction = await extract_profile(
        profiler_config,
        backends={"fake": backend},
        prompts=PromptLibrary(),
        log=log,
        examples=examples,
        name="team-east",
        extends="icd203-base",
        packs_dir=None,
    )
    assert extraction.profile.draft and extraction.profile.name == "team-east"
    assert extraction.profile.lexicon.handling_markings == ["UNCLASSIFIED//FOUO"]
    assert extraction.profile.format.heading_style == "numbered"
    assert extraction.observations[0] == "3 example reports read"
    assert extraction.examples == ["report-1.md", "report-2.md", "report-3.md"]
    assert extraction.model == "model-b"
    assert log.usage().by_role.keys() == {"profiler"}
    request = backend.requests[0]
    assert request.schema_name == "ProfileDraft"
    assert "icd203.tc.8" in request.messages[1].content  # the pack's rule ids are shown


async def test_extract_profile_requires_the_role_and_a_known_pack(
    make_config, profiler_config, examples_dir
):
    examples = read_examples(examples_dir, budget_tokens=16000, bytes_per_token=2.5)
    with pytest.raises(ConfigError, match="roles.profiler"):
        await extract_profile(
            make_config(),
            backends={"fake": FakeBackend()},
            prompts=PromptLibrary(),
            log=CallLog(),
            examples=examples,
            name="n",
            extends="icd203-base",
            packs_dir=None,
        )
    from corelata.standards.loader import PackError

    with pytest.raises(PackError, match="nope"):
        await extract_profile(
            profiler_config,
            backends={"fake": FakeBackend()},
            prompts=PromptLibrary(),
            log=CallLog(),
            examples=examples,
            name="n",
            extends="nope",
            packs_dir=None,
        )


async def test_extract_profile_invalid_draft_gets_one_repair_then_fails(profiler_config, tmp_path):
    d = tmp_path / "ex"
    d.mkdir()
    (d / "r.md").write_text("BADRULE everywhere.\n")
    examples = read_examples(d, budget_tokens=1000, bytes_per_token=2.5)
    backend = FakeBackend(name="fake")
    with pytest.raises(StructuredOutputError, match="unknown rule id 'nope.rule.1'"):
        await extract_profile(
            profiler_config,
            backends={"fake": backend},
            prompts=PromptLibrary(),
            log=CallLog(),
            examples=examples,
            name="n",
            extends="icd203-base",
            packs_dir=None,
        )
    assert len(backend.requests) == 2  # first answer + one repair turn


def test_profile_yaml_round_trips_with_a_review_header():
    base = load_pack("icd203-base")
    draft = ProfileDraft(
        observations=["Three reports.", "Numbered headings."],
        tone="Be brief.",
        heading_style="numbered",
        handling_markings=["UNCLASSIFIED//FOUO"],
    )
    extraction = ProfileExtraction(
        profile=to_profile(draft, base, name="team-east", extends="icd203-base"),
        observations=draft.observations,
        examples=["a.md", "b.docx", "c.md"],
        model="strong",
    )
    text = profile_yaml(extraction, written_at=datetime(2026, 10, 14, 12, 0, tzinfo=UTC))
    head, body = text.split("\n\n", 1)
    assert head.startswith("# Draft profile written by `corelata profile extract` on 2026-10-14")
    assert "#   - a.md" in head and "#   - c.md" in head and "# Model: strong" in head
    assert "#   - Three reports." in head
    assert "set `draft: false`" in head
    assert all(line.startswith("#") for line in head.splitlines())
    data = yaml.safe_load(body)
    assert list(data)[:3] == ["name", "extends", "draft"] and data["draft"] is True
    assert Profile.model_validate(data) == extraction.profile
    assert "rules" not in data  # defaults are not written
    assert data["format"] == {"heading_style": "numbered"}
    assert "docx_reference" not in body


def test_shares_water_fill_the_budget():
    assert _shares([8, 200], 108) == [8, 100]  # the short report keeps all, the long one the rest
    assert _shares([50, 50, 50], 90) == [30, 30, 30]  # all long: an even split
    assert _shares([5, 5], 100) == [5, 5]  # budget to spare
    assert _shares([100], 0) == [1]  # never less than one token per report
    assert _shares([30, 10, 20], 45) == [18, 10, 17]  # order is kept; allotment goes by size


def test_read_examples_gives_long_reports_what_short_ones_leave(tmp_path):
    (tmp_path / "a.txt").write_text("\n\n".join(["x" * 10] * 2), encoding="utf-8")  # 2 x 4 tokens
    (tmp_path / "b.txt").write_text("\n\n".join(["y" * 25] * 20), encoding="utf-8")  # 20 x 10
    reports = read_examples(tmp_path, budget_tokens=108, bytes_per_token=2.5)
    assert [r.name for r in reports] == ["a.txt", "b.txt"]
    assert len(reports[0].units) == 2 and not reports[0].truncated
    assert len(reports[1].units) == 10 and reports[1].truncated  # 100 of the budget, not 54
