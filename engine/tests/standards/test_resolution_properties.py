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
