"""CRL-96: the base pack's source summary section and `source_access` lexicon list, the profile
switches that turn them off, and what `corelata pack diff` says about the change."""

import json
import shutil

import yaml

from corelata.cli import main
from corelata.standards.loader import BUILTIN_PACKS_DIR, load_pack, pack_hash, validate_pack
from corelata.standards.schema import Lexicon
from tests.standards.test_loader import LEXICON, RULE, TEMPLATE, write_pack

ACCESS = ["direct", "indirect", "unknown"]
# icd206.src.1 as the 1.0.0 base pack had it, before it quoted ICD 206 D.3.d
OLD_SRC_1 = {
    "source": "ICD 206 (2015) D.2",
    "text": "Analytic products shall include a source summary statement that characterises the"
    " body of sourcing used, its strengths and weaknesses, and how it supports the key"
    " judgments.\n",
    "evidence_required": "The scope note or sources section contains a summary of the sourcing"
    " as a whole, not only per-source entries.\n",
}


def test_the_base_pack_asks_for_source_details_and_a_summary():
    pack = load_pack("icd203-base")
    assert pack.version == "1.1.0"
    assert pack.lexicon.source_access == ACCESS and pack.source_details
    order = pack.template.section_order
    assert pack.source_summary and order.index("source_summary") == order.index("sources") + 1
    rule = pack.rule("icd206.src.1")
    assert rule.source == "ICD 206 (2015) D.3.d"
    assert "strengths and weaknesses of the source base" in rule.text
    assert "meaningfully corroborative or conflicting" in rule.text
    assert validate_pack("icd203-base") == []


def test_a_lexicon_without_source_access_dumps_and_hashes_as_before(tmp_path):
    write_pack(tmp_path, "plain", rules=[RULE])
    pack = load_pack("plain", packs_dir=tmp_path)
    assert not pack.source_details and not pack.source_summary
    assert "source_access" not in pack.model_dump()["lexicon"]
    assert Lexicon.model_validate(LEXICON).model_dump() == LEXICON
    with_list = pack.model_copy(
        update={"lexicon": pack.lexicon.model_copy(update={"source_access": ACCESS})}
    )
    assert pack_hash(with_list) != pack_hash(pack)


def test_a_profile_turns_the_summary_and_the_details_off(tmp_path):
    template = {**TEMPLATE, "section_order": [*TEMPLATE["section_order"], "source_summary"]}
    profiles = {
        "terse": {"name": "terse", "extends": "base", "template": {"source_summary": False}},
        "bare": {
            "name": "bare",
            "extends": "base",
            "template": {
                "source_summary": False,
                "source_details": False,
                "analysis_max_words": 300,
            },
        },
        "keep": {
            "name": "keep",
            "extends": "base",
            "template": {"source_summary": True, "source_details": True},
        },
    }
    write_pack(
        tmp_path,
        "base",
        rules=[RULE],
        template=template,
        lexicon={**LEXICON, "source_access": ACCESS},
        profiles=profiles,
    )
    base = load_pack("base", packs_dir=tmp_path)
    terse = load_pack("base", packs_dir=tmp_path, profile="terse")
    bare = load_pack("base", packs_dir=tmp_path, profile="bare")
    keep = load_pack("base", packs_dir=tmp_path, profile="keep")
    assert (base.source_summary, base.source_details) == (True, True)
    assert (terse.source_summary, terse.source_details) == (False, True)
    assert (bare.source_summary, bare.source_details) == (False, False)
    assert bare.template.section_order == TEMPLATE["section_order"]
    assert bare.template.analysis_max_words == 300
    assert keep.template == base.template and keep.lexicon == base.lexicon
    assert validate_pack(str(tmp_path / "base")) == []


def _old_base_pack(root):
    """The 1.0.0 base pack, rebuilt from the current one by undoing CRL-96."""
    old = root / "icd203-base"
    shutil.copytree(BUILTIN_PACKS_DIR / "icd203-base", old)
    meta = yaml.safe_load((old / "pack.yaml").read_text())
    (old / "pack.yaml").write_text(yaml.safe_dump({**meta, "version": "1.0.0"}))
    template = yaml.safe_load((old / "template.yaml").read_text())
    template["section_order"].remove("source_summary")
    (old / "template.yaml").write_text(yaml.safe_dump(template))
    lexicon = yaml.safe_load((old / "lexicon.yaml").read_text())
    del lexicon["source_access"]
    (old / "lexicon.yaml").write_text(yaml.safe_dump(lexicon))
    rule_file = old / "rules" / "icd206.src.1.yaml"
    rule = yaml.safe_load(rule_file.read_text())
    rule_file.write_text(yaml.safe_dump({**rule, **OLD_SRC_1}))
    return old


def test_pack_diff_lists_exactly_the_rule_text_template_section_and_lexicon_list(tmp_path, capsys):
    old = _old_base_pack(tmp_path)
    assert main(["pack", "diff", str(old), "icd203-base", "--json"]) == 3
    diff = json.loads(capsys.readouterr().out)
    new_rule = load_pack("icd203-base").rule("icd206.src.1")
    assert diff["identity"] == [{"field": "version", "before": "1.0.0", "after": "1.1.0"}]
    assert diff["rules_added"] == [] and diff["rules_removed"] == []
    [changed] = diff["rules_changed"]
    assert changed["id"] == "icd206.src.1"
    assert changed["changes"] == [
        {
            "field": "evidence_required",
            "before": OLD_SRC_1["evidence_required"],
            "after": new_rule.evidence_required,
        },
        {"field": "source", "before": OLD_SRC_1["source"], "after": new_rule.source},
        {"field": "text", "before": OLD_SRC_1["text"], "after": new_rule.text},
    ]
    assert diff["template"] == [
        {"field": "section_order added", "before": None, "after": ["source_summary"]}
    ]
    assert diff["lexicon"] == [{"field": "source_access", "before": None, "after": ACCESS}]
    assert diff["tone_changed"] is False and diff["format"] == []
    assert main(["pack", "diff", str(old), "icd203-base"]) == 3
    text = capsys.readouterr().out
    assert "section_order added: ['source_summary']" in text
    assert "source_access: None -> ['direct', 'indirect', 'unknown']" in text
