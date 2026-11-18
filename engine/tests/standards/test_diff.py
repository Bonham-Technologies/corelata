import json

from corelata.standards.diff import FieldChange, PackDiff, diff_packs, format_diff
from corelata.standards.loader import load_pack
from tests.standards.test_loader import LEXICON, RULE, TEMPLATE, write_pack

RULE2 = {**RULE, "id": "test.r.2", "title": "Second rule", "severity": "minor"}
PROFILE = {
    "name": "team",
    "extends": "base",
    "rules": {
        "disable": ["test.r.2"],
        "override": [{"id": "test.r.1", "severity": "blocking", "text": "Stricter."}],
        "add": [{**RULE, "id": "team.r.1", "title": "House rule"}],
    },
    "template": {"key_judgments": {"min": 1, "max": 3}},
    "tone": "Lead with the judgment.",
    "format": {"heading_style": "numbered"},
    "lexicon": {"handling_markings": ["UNCLASSIFIED//FOUO"]},
}


def _packs(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE, RULE2], profiles={"team": PROFILE})
    base = load_pack("base", packs_dir=tmp_path)
    team = load_pack("base", packs_dir=tmp_path, profile="team")
    return base, team


def test_identical_packs_have_an_empty_diff(tmp_path):
    base, _ = _packs(tmp_path)
    diff = diff_packs(base, base, left_name="a", right_name="b")
    assert diff.empty
    assert diff.model_dump(exclude={"left", "right"}) == {
        "identity": [],
        "rules_added": [],
        "rules_removed": [],
        "rules_changed": [],
        "template": [],
        "lexicon": [],
        "tone_changed": False,
        "format": [],
    }
    assert format_diff(diff) == "pack diff: a -> b\nno differences\n"


def test_profile_changes_are_listed_by_kind(tmp_path):
    base, team = _packs(tmp_path)
    diff = diff_packs(base, team, left_name="base", right_name="base@team")
    assert not diff.empty
    assert [c.model_dump() for c in diff.identity] == [
        {"field": "profile", "before": None, "after": "team"}
    ]
    assert diff.rules_added == ["team.r.1"] and diff.rules_removed == ["test.r.2"]
    assert [r.id for r in diff.rules_changed] == ["test.r.1"]
    assert [c.model_dump() for c in diff.rules_changed[0].changes] == [
        {"field": "severity", "before": "major", "after": "blocking"},
        {"field": "text", "before": RULE["text"], "after": "Stricter."},
    ]
    assert [c.model_dump() for c in diff.template] == [
        {"field": "key_judgments.max", "before": 5, "after": 3}
    ]
    assert [c.model_dump() for c in diff.lexicon] == [
        {"field": "handling_markings added", "before": None, "after": ["UNCLASSIFIED//FOUO"]}
    ]
    assert diff.tone_changed
    assert [c.model_dump() for c in diff.format] == [
        {"field": "heading_style", "before": "plain", "after": "numbered"}
    ]
    text = format_diff(diff, left=base, right=team)
    assert "profile: None -> team" in text
    assert "rules added (1):\n  team.r.1  House rule [major, verifiable]" in text
    assert "rules removed (1):\n  test.r.2  Second rule [minor, verifiable]" in text
    assert "rules changed (1):\n  test.r.1:\n    severity: major -> blocking" in text
    assert "template:\n  key_judgments.max: 5 -> 3" in text
    assert "lexicon:\n  handling_markings added: ['UNCLASSIFIED//FOUO']" in text
    assert "tone changed" in text
    assert "format:\n  heading_style: plain -> numbered" in text
    PackDiff.model_validate_json(diff.model_dump_json())  # round trip


def test_lexicon_terms_are_keyed_by_term_and_versions_by_identity(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE])
    lexicon = {
        **LEXICON,
        "likelihood": [
            {"term": "likely", "low": 55, "high": 85},
            {"term": "unlikely", "low": 20, "high": 45},
        ],
        "confidence_definitions": {**LEXICON["confidence_definitions"], "high": "Changed."},
        "source_descriptors": ["press report"],
    }
    write_pack(tmp_path, "other", rules=[RULE], lexicon=lexicon, template=TEMPLATE)
    left = load_pack("base", packs_dir=tmp_path)
    right = load_pack("other", packs_dir=tmp_path)
    diff = diff_packs(left, right, left_name="base", right_name="other")
    assert [c.field for c in diff.identity] == ["name"]
    assert [c.model_dump() for c in diff.lexicon] == [
        {
            "field": "confidence_definitions.high",
            "before": LEXICON["confidence_definitions"]["high"],
            "after": "Changed.",
        },
        {"field": "likelihood[likely].high", "before": 80, "after": 85},
        {
            "field": "likelihood[unlikely]",
            "before": None,
            "after": {"term": "unlikely", "low": 20, "high": 45},
        },
        {"field": "source_descriptors removed", "before": ["open-source report"], "after": None},
        {"field": "source_descriptors added", "before": None, "after": ["press report"]},
    ]
    text = format_diff(diff, left=left, right=right)
    assert "source_descriptors removed: ['open-source report']" in text
    assert "source_descriptors added: ['press report']" in text
    assert json.loads(diff.model_dump_json())["lexicon"][2]["after"]["term"] == "unlikely"


def test_a_reordered_scalar_list_is_a_difference(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE])
    order = TEMPLATE["section_order"]
    write_pack(
        tmp_path,
        "other",
        rules=[RULE],
        template={**TEMPLATE, "section_order": list(reversed(order))},
    )
    left = load_pack("base", packs_dir=tmp_path)
    right = load_pack("other", packs_dir=tmp_path)
    diff = diff_packs(left, right, left_name="base", right_name="other")
    assert diff.template == [
        FieldChange(field="section_order order", before=order, after=list(reversed(order)))
    ]
    assert not diff.empty
    assert "section_order order:" in format_diff(diff, left=left, right=right)
