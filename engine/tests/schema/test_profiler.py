import pytest
from pydantic import ValidationError

from corelata.schema import DraftLimits, DraftRuleOverride, ProfileDraft


def test_profile_draft_minimal_and_full():
    d = ProfileDraft(observations=["x"], tone="Be brief.")
    assert d.heading_style == "plain" and d.key_judgments is None and d.override == []
    full = ProfileDraft(
        observations=["a", "b"],
        tone="t",
        key_judgments=DraftLimits(min=1, max=3),
        analysis_max_words=800,
        heading_style="numbered",
        handling_markings=["UNCLASSIFIED//FOUO"],
        source_descriptors=["a liaison service"],
        disable=["icd203.tc.4"],
        override=[DraftRuleOverride(id="icd203.tc.9", severity="major")],
    )
    assert full.model_dump()["override"] == [{"id": "icd203.tc.9", "severity": "major"}]


@pytest.mark.parametrize(
    "data",
    [
        {"observations": [], "tone": "t"},
        {"observations": ["x"], "tone": ""},
        {"observations": ["x"], "tone": "t", "analysis_max_words": 10},
        {"observations": ["x"], "tone": "t", "heading_style": "fancy"},
        {"observations": ["x"], "tone": "t", "override": [{"id": "a.b", "severity": "fatal"}]},
    ],
)
def test_profile_draft_rejects(data):
    with pytest.raises(ValidationError):
        ProfileDraft.model_validate(data)


def test_profile_draft_schema_is_model_friendly():
    schema = ProfileDraft.model_json_schema()
    assert set(schema["required"]) == {"observations", "tone"}
    assert "description" in schema["properties"]["tone"]
