from hypothesis import given, settings
from hypothesis import strategies as st

from corelata.standards.loader import RawPack, resolve
from corelata.standards.schema import (
    Checkability,
    ItemLimits,
    Lexicon,
    PackMeta,
    Profile,
    ProfileRules,
    RouteTo,
    Rule,
    RuleOverride,
    Severity,
    Template,
)

ids = st.from_regex(r"\A[a-z]{1,4}\.[a-z]{1,3}\.[0-9]{1,2}\Z")


def rule(rule_id: str, severity: Severity = Severity.MAJOR) -> Rule:
    return Rule(
        id=rule_id,
        title="t",
        text="x",
        severity=severity,
        checkability=Checkability.VERIFIABLE,
        applies_to=["auditor"],
        evidence_required="e",
        route_to=RouteTo.WRITER,
    )


TEMPLATE = Template(
    section_order=["title"],
    key_judgments=ItemLimits(min=1, max=5),
    analysis_max_words=100,
    alternatives_required_unless_all_high=True,
    gaps_required=True,
)
LEXICON = Lexicon(
    likelihood=[], confidence_definitions={}, source_descriptors=[], handling_markings=["U"]
)


def raw(name: str, rules: list[Rule], extends: str | None = None) -> RawPack:
    return RawPack(
        meta=PackMeta(name=name, version="1", extends=extends),
        rules=rules,
        template=TEMPLATE if extends is None else None,
        lexicon=LEXICON if extends is None else None,
        profiles={},
        path=None,
    )


@settings(max_examples=60, deadline=None)
@given(base_ids=st.lists(ids, min_size=1, max_size=6, unique=True), data=st.data())
def test_disable_wins_and_add_appends_and_result_sorted(base_ids, data):
    base = raw("base", [rule(i) for i in base_ids])
    disabled = data.draw(st.lists(st.sampled_from(base_ids), max_size=3, unique=True))
    overridden = data.draw(st.lists(st.sampled_from(base_ids), max_size=3, unique=True))
    overridden = [i for i in overridden if i not in disabled]
    added = data.draw(st.lists(ids.filter(lambda i: i not in base_ids), max_size=3, unique=True))
    profile = Profile(
        name="p",
        extends="base",
        rules=ProfileRules(
            add=[rule(i, Severity.MINOR) for i in added],
            disable=disabled,
            override=[RuleOverride(id=i, severity=Severity.BLOCKING) for i in overridden],
        ),
    )
    resolved = resolve([base], profile)
    got = resolved.rule_ids()
    assert got == sorted(got)
    assert set(got) == (set(base_ids) - set(disabled)) | set(added)
    for i in overridden:
        if i not in disabled:
            assert resolved.rule(i).severity is Severity.BLOCKING
    # idempotent: resolving the resolved rules as a base with no profile changes nothing
    again = resolve([raw("base", resolved.rules)], None)
    assert again.rules == resolved.rules


@settings(max_examples=40, deadline=None)
@given(
    summary=st.sampled_from([None, True, False]),
    details=st.sampled_from([None, True, False]),
    order=st.permutations(["title", "sources", "source_summary", "analysis"]),
    access=st.lists(st.sampled_from(["direct", "indirect", "unknown"]), unique=True),
)
def test_source_switches_only_ever_turn_off_what_the_pack_has(summary, details, order, access):
    """CRL-96: `false` drops the section or the access terms; `true` or absent changes nothing;
    nothing else in the template or lexicon moves."""
    base = raw("base", [rule("a.b.1")])
    base.template = TEMPLATE.model_copy(update={"section_order": list(order)})
    base.lexicon = LEXICON.model_copy(update={"source_access": access})
    profile = Profile.model_validate(
        {
            "name": "p",
            "extends": "base",
            "template": {"source_summary": summary, "source_details": details},
        }
    )
    plain = resolve([base], None)
    resolved = resolve([base], profile)
    want_order = [s for s in order if summary is not False or s != "source_summary"]
    assert resolved.template.section_order == want_order
    assert resolved.lexicon.source_access == ([] if details is False else access)
    assert resolved.template.model_copy(update={"section_order": list(order)}) == plain.template
    assert resolved.lexicon.model_copy(update={"source_access": access}) == plain.lexicon
