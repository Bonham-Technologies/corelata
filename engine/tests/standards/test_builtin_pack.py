import json
from pathlib import Path

from corelata.standards.loader import BUILTIN_PACKS_DIR, load_pack, pack_hash, validate_pack
from corelata.standards.schema import Checkability, Severity

GOLDEN = Path(__file__).parent / "golden" / "icd203-base.resolved.json"
EXPECTED_IDS = [
    "icd203.as.1",
    "icd203.as.2",
    "icd203.as.3",
    "icd203.as.4",
    "icd203.as.5",
    "icd203.tc.1",
    "icd203.tc.2",
    "icd203.tc.3",
    "icd203.tc.4",
    "icd203.tc.5",
    "icd203.tc.6",
    "icd203.tc.7",
    "icd203.tc.8",
    "icd203.tc.9",
    "icd206.src.1",
    "icd206.src.2",
    "icd206.src.3",
]


def test_builtin_pack_loads_with_expected_rules():
    pack = load_pack("icd203-base")
    assert pack.rule_ids() == EXPECTED_IDS
    assert pack.rule("icd203.tc.8").severity is Severity.BLOCKING
    assert pack.rule("icd203.as.2").checkability is Checkability.ADVISORY
    assert pack.rule("icd203.tc.9").checkability is Checkability.ADVISORY
    advisory = {r.id for r in pack.rules if r.checkability is Checkability.ADVISORY}
    assert advisory == {"icd203.as.1", "icd203.as.2", "icd203.as.3", "icd203.tc.7", "icd203.tc.9"}
    assert pack.lexicon.terms() == {
        "almost no chance",
        "very unlikely",
        "unlikely",
        "roughly even chance",
        "likely",
        "very likely",
        "almost certain",
    }
    assert pack.lexicon.handling_markings == ["UNCLASSIFIED"]
    assert pack.template.key_judgments.max == 5
    assert validate_pack("icd203-base") == []
    assert BUILTIN_PACKS_DIR.joinpath("icd203-base", "pack.yaml").is_file()


def test_builtin_pack_matches_golden():
    pack = load_pack("icd203-base")
    resolved = json.loads(pack.model_dump_json())
    if not GOLDEN.is_file():  # first run writes the golden; review the diff, then commit it
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(resolved, indent=2, sort_keys=True) + "\n")
    assert resolved == json.loads(GOLDEN.read_text())
    assert pack_hash(pack) == pack_hash(load_pack("icd203-base"))


def test_tc7_is_checked_only_against_earlier_reports():
    """CRL-97: tc.7 is advisory as written; a run with earlier accepted reports reads it as
    verifiable with the block's evidence, and every rule dumps without the block."""
    pack = load_pack("icd203-base")
    assert pack.prior_report_rules() == ["icd203.tc.7"]
    written = pack.rule("icd203.tc.7")
    assert written.with_prior_reports is not None
    with_prior = pack.for_run(prior_reports=True)
    tc7 = with_prior.rule("icd203.tc.7")
    assert tc7.checkability is Checkability.VERIFIABLE
    assert tc7.evidence_required == written.with_prior_reports.evidence_required
    without = pack.for_run(prior_reports=False).rule("icd203.tc.7")
    assert without.checkability is Checkability.ADVISORY
    assert without.evidence_required == written.evidence_required
    for run_pack in (with_prior, pack.for_run(prior_reports=False)):
        assert all("with_prior_reports" not in r.model_dump() for r in run_pack.rules)
        assert run_pack.prior_report_rules() == []
    # a pack without such rules is the same object, and its rules dump as before
    plain = pack.model_copy(update={"rules": [r for r in pack.rules if r.id != "icd203.tc.7"]})
    assert plain.for_run(prior_reports=True) is plain
    assert "with_prior_reports" not in plain.rules[0].model_dump()
