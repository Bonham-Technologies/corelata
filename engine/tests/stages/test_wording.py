"""CRL-136: the engine's check of a judgment's uncertainty wording (ICD 203 D.6.e(2))."""

import json
import shutil

import pytest
import yaml

from corelata.cli import main
from corelata.schema import ReportBody, Verdict
from corelata.stages.audit import (
    ENGINE_CHECK,
    WORDING_FIX,
    apply_engine_checks,
    auditor_payload,
    engine_only_findings,
    run_auditor,
)
from corelata.stages.write import run_writer
from corelata.standards.loader import BUILTIN_PACKS_DIR, load_pack, pack_hash
from corelata.standards.schema import WORDING_LISTS, Lexicon
from corelata.testing.sources import text_source
from corelata.wording import WordingCheck, wording_problems
from tests.stages.conftest import PORT
from tests.stages.test_audit import lenient_reply
from tests.standards.test_loader import LEXICON, RULE, write_pack

BASE = load_pack("icd203-base").lexicon
CHECK = WordingCheck(BASE)


def _draft(kj: str = "Varna matters.", claims: list[dict] | None = None) -> ReportBody:
    claims = claims or [
        {
            "id": "c0",
            "text": "It is likely that Varna matters.",
            "kind": "judgment",
            "evidence": ["src1/u1"],
            "likelihood_term": "likely",
        }
    ]
    return ReportBody.model_validate(
        {
            "title": "t",
            "handling_marking": "UNCLASSIFIED",
            "key_judgments": [{"text": kj, "confidence": "moderate", "claim_ids": ["c0"]}],
            "scope_note": "s",
            "sources": [],
            "analysis": [],
            "alternatives": [],
            "gaps_and_indicators": [],
            "claims": claims,
        }
    )


def _judgment(cid: str, text: str, term: str | None = "likely", kind: str = "judgment") -> dict:
    return {"id": cid, "text": text, "kind": kind, "evidence": ["src1/u1"], "likelihood_term": term}


def test_the_base_pack_fills_the_three_lists_from_icd_203():
    assert {"probable", "highly probable", "nearly certain", "remote chance"} <= set(
        BASE.likelihood_alternates
    )
    assert {"possibly", "perhaps", "certainly"} <= set(BASE.unlisted_probability_words)
    assert {"high confidence", "moderate confidence", "low confidence"} <= set(
        BASE.confidence_phrases
    )
    assert BASE.checks_wording


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("It is unlikely to happen.", ["unlikely"]),
        ("It is very likely to happen.", ["very likely"]),
        ("It is VERY  LIKELY to happen.", ["very likely"]),
        ("It will almost certainly happen.", ["almost certain"]),
        ("It will certainly happen.", ["certainly"]),
        ("It will probably happen.", ["probable"]),
        ("It is highly probable.", ["highly probable"]),
        ("Chances are remote.", ["chances are remote"]),
        ("Chances are it happens.", ["chances are"]),
        ("A roughly even chance; an even chance.", ["roughly even chance", "even chance"]),
        ("We assess with high confidence.", ["high confidence"]),
        ("Remote sensing shows likelihood rising.", []),
        ("The unlikelyhood and likelyish ideas.", []),
        ("Dotless lıkely and dotted İmprobable are not the listed words.", []),
    ],
)
def test_matching_takes_whole_words_and_the_longest_phrase(text, found):
    assert [f.phrase for f in CHECK.find(text)] == found


def test_a_confidence_phrase_and_a_likelihood_in_one_sentence_is_a_problem():
    mixed = "We assess with high confidence that it is likely to grow."
    assert CHECK.problems(mixed, "likely") == [
        "puts a confidence level and a likelihood in one sentence ('high confidence', 'likely')"
    ]
    two = "It is likely to grow. We have moderate confidence in this judgment."
    assert CHECK.problems(two, "likely") == []
    assert CHECK.problems("Low confidence.  It is likely! High confidence?", "likely") == []


def test_wording_off_the_lexicon_row_and_a_missing_term_are_problems():
    assert CHECK.problems("It will probably and perhaps grow.", None) == [
        "uses probability wording outside the lexicon ('probable', 'perhaps')"
    ]
    assert CHECK.problems("It is very likely to grow.", "likely") == [
        "does not use its likelihood term 'likely' in its text"
    ]
    assert CHECK.problems("It is unlikely to grow.", "likely") == [
        "does not use its likelihood term 'likely' in its text"
    ]
    assert CHECK.problems("It is Almost Certainly growing.", "almost certain") == []
    assert CHECK.problems("Growth continues.", None) == []


def test_wording_problems_name_key_judgments_and_judgment_claims_only():
    draft = _draft(
        kj="With high confidence, growth is likely. It is perhaps lasting.",
        claims=[
            _judgment("c0", "It is likely that Varna matters."),
            _judgment("c1", "Varna is probably growing.", term="very likely"),
            _judgment("c2", "A source says it is possibly growing.", term=None, kind="fact"),
            _judgment("c3", "It is likely, at high confidence, to grow."),
        ],
    )
    found = wording_problems(draft, BASE)
    assert found.problems == [
        "key judgment 1 puts a confidence level and a likelihood in one sentence "
        "('high confidence', 'likely')",
        "key judgment 1 uses probability wording outside the lexicon ('perhaps')",
        "c1 uses probability wording outside the lexicon ('probable')",
        "c1 does not use its likelihood term 'very likely' in its text",
        "c3 puts a confidence level and a likelihood in one sentence ('high confidence', 'likely')",
    ]
    assert found.claim_ids == ["c1", "c3"]


def test_a_lexicon_without_the_lists_checks_nothing():
    plain = Lexicon.model_validate(LEXICON)
    assert not plain.checks_wording
    draft = _draft(claims=[_judgment("c0", "Probably, with high confidence.", term="likely")])
    found = wording_problems(draft, plain)
    assert found.problems == [] and found.claim_ids == []


def test_a_phrase_on_two_lists_counts_as_the_earlier_list():
    lex = Lexicon.model_validate(
        {**LEXICON, "likelihood_alternates": ["likely"], "unlisted_probability_words": [" "]}
    )
    check = WordingCheck(lex)
    assert [(f.kind.value, f.phrase) for f in check.find("It is likely.")] == [("term", "likely")]


def _bad_draft() -> ReportBody:
    return _draft(
        claims=[
            _judgment("c0", "It is likely that Varna matters."),
            _judgment("c1", "We assess with high confidence that Varna is likely to grow."),
        ]
    )


def test_engine_fails_tc2_over_a_lenient_auditor_and_names_the_claim():
    pack = load_pack("icd203-base")
    draft = _bad_draft()
    seed = engine_only_findings(_draft(), pack, 0)
    assert seed == []
    [tc2] = engine_only_findings(draft, pack, 0)
    assert tc2.rule_id == "icd203.tc.2" and tc2.verdict is Verdict.FAIL
    assert tc2.evidence == (
        f"{ENGINE_CHECK}c1 puts a confidence level and a likelihood in one sentence "
        "('high confidence', 'likely')"
    )
    assert tc2.claim_ids == ["c1"] and tc2.recommendation == WORDING_FIX
    assert tc2.severity == "blocking" and tc2.route_to == "writer"


def test_an_auditor_failure_of_tc2_keeps_its_finding_with_the_engines_problems_added():
    pack = load_pack("icd203-base")
    [seed] = engine_only_findings(_bad_draft(), pack, 0)
    own = seed.model_copy(
        update={"evidence": "c0 hedges.", "claim_ids": ["c0"], "recommendation": "Fix c0."}
    )
    [kept] = apply_engine_checks(_bad_draft(), [own], pack)
    assert kept.evidence.startswith(f"c0 hedges.; {ENGINE_CHECK}c1 puts a confidence level")
    assert kept.claim_ids == ["c0", "c1"] and kept.recommendation == "Fix c0."
    blank = own.model_copy(update={"evidence": ""})
    [kept] = apply_engine_checks(_bad_draft(), [blank], pack)
    assert kept.evidence.startswith(f"{ENGINE_CHECK}c1 puts")


def test_a_profile_without_tc2_skips_the_check():
    pack = load_pack("icd203-base")
    relaxed = pack.model_copy(update={"rules": [r for r in pack.rules if r.id != "icd203.tc.2"]})
    assert engine_only_findings(_bad_draft(), relaxed, 0) == []


async def test_run_auditor_applies_the_wording_check(make_ctx, fake_backend):
    ctx = make_ctx(text_source("src1", *PORT, "OFFLEXICON appears in the coverage."))
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    fake_backend.script("auditor", lenient_reply(ctx.pack))
    by_rule = {f.rule_id: f for f in (await run_auditor(ctx, iteration=0, draft=draft)).findings}
    tc2 = by_rule["icd203.tc.2"]
    assert tc2.verdict is Verdict.FAIL and tc2.claim_ids == ["c0"]
    assert tc2.evidence == (
        f"{ENGINE_CHECK}c0 uses probability wording outside the lexicon ('probable')"
    )


async def test_the_model_is_not_sent_the_wording_lists(make_ctx):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    content = ctx.runner.log.records[-1].request["messages"][1]["content"]
    writer = json.loads(content.split("\n", 1)[1])
    sent = auditor_payload(ctx.pack, draft, [], ctx.value_statement)
    for lexicon in (writer["lexicon"], sent["lexicon"]):
        assert not set(WORDING_LISTS) & set(lexicon)
        assert lexicon["likelihood"] and lexicon["handling_markings"]


async def test_a_pack_without_the_lists_sends_byte_identical_requests_and_hashes_as_before(
    tmp_path, make_ctx
):
    """Acceptance criterion 4: the lists are additive. The same pack with and without empty
    lists dumps, hashes and is sent alike; filling them changes the hash but not the request."""
    write_pack(tmp_path, "plain", rules=[RULE])
    plain = load_pack("plain", packs_dir=tmp_path)
    empty = {name: [] for name in WORDING_LISTS}
    write_pack(tmp_path, "empty", rules=[RULE], lexicon={**LEXICON, **empty})
    with_empty = load_pack("empty", packs_dir=tmp_path).model_copy(update={"name": "plain"})
    assert plain.model_dump() == with_empty.model_dump()
    assert pack_hash(plain) == pack_hash(with_empty)
    assert not set(WORDING_LISTS) & set(plain.model_dump()["lexicon"])
    filled = plain.model_copy(
        update={"lexicon": plain.lexicon.model_copy(update={"confidence_phrases": ["x"]})}
    )
    assert pack_hash(filled) != pack_hash(plain)

    async def requests(pack) -> list[str]:
        ctx = make_ctx()
        ctx.pack = pack
        draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
        await run_auditor(ctx, iteration=0, draft=draft)
        return [json.dumps(r.request, sort_keys=True) for r in ctx.runner.log.records]

    sent = await requests(plain)
    assert sent == await requests(with_empty)
    assert sent == await requests(filled)


def test_pack_diff_from_1_1_0_lists_exactly_the_three_lexicon_lists(tmp_path, capsys):
    old = tmp_path / "icd203-base"
    shutil.copytree(BUILTIN_PACKS_DIR / "icd203-base", old)
    meta = yaml.safe_load((old / "pack.yaml").read_text())
    (old / "pack.yaml").write_text(yaml.safe_dump({**meta, "version": "1.1.0"}))
    lexicon = yaml.safe_load((old / "lexicon.yaml").read_text())
    for name in WORDING_LISTS:
        del lexicon[name]
    (old / "lexicon.yaml").write_text(yaml.safe_dump(lexicon))
    assert main(["pack", "diff", str(old), "icd203-base", "--json"]) == 3
    diff = json.loads(capsys.readouterr().out)
    assert diff["identity"] == [{"field": "version", "before": "1.1.0", "after": "1.2.0"}]
    assert diff["rules_changed"] == [] and diff["template"] == []
    assert [c["field"] for c in diff["lexicon"]] == sorted(WORDING_LISTS)
