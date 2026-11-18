import os
import sys
import time
from pathlib import Path

import pytest
import yaml
from docx import Document

from corelata.standards.loader import (
    PackError,
    chain_profiles,
    find_pack_dir,
    list_packs,
    load_pack,
    pack_hash,
    read_pack_dir,
    validate_pack,
)
from corelata.standards.schema import Checkability, ResolvedPack, RouteTo, Severity

RULE = {
    "id": "test.r.1",
    "title": "Rule one",
    "text": "Do the thing.",
    "severity": "major",
    "checkability": "verifiable",
    "applies_to": ["writer", "auditor"],
    "evidence_required": "Show the thing.",
    "route_to": "writer",
}
TEMPLATE = {
    "section_order": [
        "title",
        "handling_marking",
        "key_judgments",
        "scope_note",
        "sources",
        "analysis",
        "alternatives",
        "gaps_and_indicators",
    ],
    "key_judgments": {"min": 1, "max": 5},
    "analysis_max_words": 1200,
    "alternatives_required_unless_all_high": True,
    "gaps_required": True,
}
LEXICON = {
    "likelihood": [{"term": "likely", "low": 55, "high": 80}],
    "confidence_definitions": {"high": "H", "moderate": "M", "low": "L"},
    "source_descriptors": ["open-source report"],
    "handling_markings": ["UNCLASSIFIED"],
}


def write_pack(
    root: Path,
    name: str,
    *,
    rules: list[dict],
    extends: str | None = None,
    template: dict | None = TEMPLATE,
    lexicon: dict | None = LEXICON,
    profiles: dict[str, dict] | None = None,
) -> Path:
    pack = root / name
    (pack / "rules").mkdir(parents=True)
    meta = {"name": name, "version": "1.0", "extends": extends}
    (pack / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    for r in rules:
        (pack / "rules" / f"{r['id']}.yaml").write_text(yaml.safe_dump(r), encoding="utf-8")
    if template is not None:
        (pack / "template.yaml").write_text(yaml.safe_dump(template), encoding="utf-8")
    if lexicon is not None:
        (pack / "lexicon.yaml").write_text(yaml.safe_dump(lexicon), encoding="utf-8")
    if profiles:
        (pack / "profiles").mkdir()
        for pname, p in profiles.items():
            (pack / "profiles" / f"{pname}.yaml").write_text(yaml.safe_dump(p), encoding="utf-8")
    return pack


def test_read_and_resolve_single_pack(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE])
    pack = load_pack("base", packs_dir=tmp_path)
    assert pack.name == "base" and pack.rule_ids() == ["test.r.1"]
    assert pack.rule("test.r.1").severity is Severity.MAJOR
    assert pack.rules_for("auditor") == pack.rules and pack.rules_for("gate") == []
    assert pack.lexicon.terms() == {"likely"}
    assert len(pack_hash(pack)) == 16


def test_extends_chain_merges_rules_and_profile_applies(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE])
    child_rule = {**RULE, "id": "test.r.2", "severity": "minor"}
    profile = {
        "name": "team",
        "extends": "child",
        "rules": {
            "disable": ["test.r.2"],
            "override": [{"id": "test.r.1", "severity": "blocking", "route_to": "conveyor"}],
            "add": [{**RULE, "id": "team.r.1", "checkability": "advisory"}],
        },
        "template": {"key_judgments": {"min": 1, "max": 3}},
        "tone": "Terse.",
        "lexicon": {"handling_markings": ["UNCLASSIFIED//FOUO"]},
    }
    write_pack(
        tmp_path,
        "child",
        rules=[child_rule],
        extends="base",
        template=None,
        lexicon=None,
        profiles={"team": profile},
    )
    pack = load_pack("child", packs_dir=tmp_path, profile="team")
    assert pack.rule_ids() == ["team.r.1", "test.r.1"]
    assert pack.rule("test.r.1").severity is Severity.BLOCKING
    assert pack.rule("test.r.1").route_to is RouteTo.CONVEYOR
    assert pack.rule("team.r.1").checkability is Checkability.ADVISORY
    assert pack.template.key_judgments.max == 3 and pack.template.analysis_max_words == 1200
    assert pack.tone == "Terse." and pack.profile == "team"
    assert pack.lexicon.handling_markings == ["UNCLASSIFIED", "UNCLASSIFIED//FOUO"]


def test_profile_hash_differs_from_base(tmp_path):
    write_pack(
        tmp_path,
        "base",
        rules=[RULE],
        profiles={"t": {"name": "t", "extends": "base", "tone": "x"}},
    )
    assert pack_hash(load_pack("base", packs_dir=tmp_path)) != pack_hash(
        load_pack("base", packs_dir=tmp_path, profile="t")
    )


def test_duplicate_rule_id_across_chain_is_error(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE])
    write_pack(tmp_path, "child", rules=[RULE], extends="base", template=None, lexicon=None)
    with pytest.raises(PackError, match="rule 'test.r.1' defined in both"):
        load_pack("child", packs_dir=tmp_path)


def test_disable_or_override_unknown_rule_is_error(tmp_path):
    write_pack(
        tmp_path,
        "base",
        rules=[RULE],
        profiles={
            "p1": {"name": "p1", "extends": "base", "rules": {"disable": ["nope.x.1"]}},
            "p2": {
                "name": "p2",
                "extends": "base",
                "rules": {"override": [{"id": "nope.x.2", "severity": "minor"}]},
            },
        },
    )
    with pytest.raises(PackError, match="disables unknown rule 'nope.x.1'"):
        load_pack("base", packs_dir=tmp_path, profile="p1")
    with pytest.raises(PackError, match="overrides unknown rule 'nope.x.2'"):
        load_pack("base", packs_dir=tmp_path, profile="p2")


def test_extends_cycle_and_missing_parent(tmp_path):
    write_pack(tmp_path, "a", rules=[RULE], extends="b")
    write_pack(tmp_path, "b", rules=[], extends="a", template=None, lexicon=None)
    with pytest.raises(PackError, match="extends cycle"):
        load_pack("a", packs_dir=tmp_path)
    write_pack(tmp_path, "c", rules=[RULE], extends="ghost")
    with pytest.raises(PackError, match="pack 'ghost' not found"):
        load_pack("c", packs_dir=tmp_path)


def test_chain_without_template_or_lexicon_is_error(tmp_path):
    write_pack(tmp_path, "bare", rules=[RULE], template=None)
    with pytest.raises(PackError, match="no template.yaml"):
        load_pack("bare", packs_dir=tmp_path)
    write_pack(tmp_path, "bare2", rules=[RULE], lexicon=None)
    with pytest.raises(PackError, match="no lexicon.yaml"):
        load_pack("bare2", packs_dir=tmp_path)


def test_draft_profile_refused_unless_allowed(tmp_path):
    write_pack(
        tmp_path,
        "base",
        rules=[RULE],
        profiles={"d": {"name": "d", "extends": "base", "draft": True}},
    )
    with pytest.raises(PackError, match="profile 'd' is a draft"):
        load_pack("base", packs_dir=tmp_path, profile="d")
    assert load_pack("base", packs_dir=tmp_path, profile="d", allow_draft=True).profile == "d"


def test_unknown_profile(tmp_path):
    write_pack(tmp_path, "base", rules=[RULE])
    with pytest.raises(PackError, match="profile 'nope' not found in pack 'base'"):
        load_pack("base", packs_dir=tmp_path, profile="nope")


def test_rule_file_errors_name_the_file(tmp_path):
    pack = write_pack(tmp_path, "base", rules=[RULE])
    (pack / "rules" / "bad.yaml").write_text("id: [\n", encoding="utf-8")
    with pytest.raises(PackError, match=r"bad\.yaml.*invalid YAML"):
        read_pack_dir(pack)
    (pack / "rules" / "bad.yaml").write_text(yaml.safe_dump({**RULE, "id": "Bad Id"}))
    with pytest.raises(PackError, match=r"bad\.yaml.*id"):
        read_pack_dir(pack)


def test_rule_id_mismatch_with_filename_is_error(tmp_path):
    pack = write_pack(tmp_path, "base", rules=[RULE])
    (pack / "rules" / "other.yaml").write_text(yaml.safe_dump({**RULE, "id": "test.r.9"}))
    with pytest.raises(PackError, match="other.yaml: rule id 'test.r.9' must match the file name"):
        read_pack_dir(pack)


def test_find_pack_dir_prefers_customer_dir_then_builtin(tmp_path):
    write_pack(tmp_path, "icd203-base", rules=[RULE])
    assert find_pack_dir("icd203-base", tmp_path) == tmp_path / "icd203-base"
    assert find_pack_dir("icd203-base", None).name == "icd203-base"
    with pytest.raises(PackError, match="pack 'zzz' not found"):
        find_pack_dir("zzz", tmp_path)


def test_validate_pack_reports_issues_instead_of_raising(tmp_path):
    write_pack(
        tmp_path,
        "base",
        rules=[RULE],
        profiles={
            "d": {"name": "d", "extends": "base", "draft": True},
            "bad": {"name": "bad", "extends": "base", "rules": {"disable": ["nope.x.1"]}},
        },
    )
    issues = validate_pack("base", packs_dir=tmp_path)
    assert any(i.level == "warning" and "draft" in i.message for i in issues)
    assert any(
        i.level == "error" and "profile 'bad'" in i.message and "nope.x.1" in i.message
        for i in issues
    )
    assert validate_pack(str(tmp_path / "base"), packs_dir=None)


def test_lexicon_band_validation(tmp_path):
    bad = {**LEXICON, "likelihood": [{"term": "likely", "low": 80, "high": 55}]}
    write_pack(tmp_path, "base", rules=[RULE], lexicon=bad)
    with pytest.raises(PackError, match="likelihood 'likely': low must be below high"):
        load_pack("base", packs_dir=tmp_path)


def _profile_with_reference(ref: str) -> dict:
    return {"name": "east", "extends": "base", "format": {"docx_reference": ref}}


def test_docx_reference_resolves_relative_to_the_profile_pack(tmp_path):
    pack = write_pack(
        tmp_path,
        "base",
        rules=[RULE],
        profiles={"east": _profile_with_reference("templates/east.docx")},
    )
    (pack / "templates").mkdir()
    Document().save(str(pack / "templates" / "east.docx"))
    resolved = load_pack("base", packs_dir=tmp_path, profile="east")
    assert resolved.docx_reference_path == (pack / "templates" / "east.docx").resolve()
    assert resolved.format.docx_reference == Path("templates/east.docx")
    dumped = resolved.model_dump(mode="json")
    assert "docx_reference_path" not in dumped
    assert "docx_reference_path" not in resolved.model_dump_json()
    assert ResolvedPack.model_validate(dumped).docx_reference_path is None
    without = load_pack("base", packs_dir=tmp_path)
    assert without.docx_reference_path is None


def test_docx_reference_absolute_path_is_kept(tmp_path):
    ref = tmp_path / "elsewhere.docx"
    Document().save(str(ref))
    write_pack(tmp_path, "base", rules=[RULE], profiles={"east": _profile_with_reference(str(ref))})
    resolved = load_pack("base", packs_dir=tmp_path, profile="east")
    assert resolved.docx_reference_path == ref.resolve()


@pytest.mark.parametrize(
    ("ref", "prepare"),
    [
        ("templates/missing.docx", lambda pack: None),
        ("templates/notes.txt", lambda pack: (pack / "templates" / "notes.txt").write_text("x")),
    ],
)
def test_docx_reference_must_be_an_existing_docx(tmp_path, ref, prepare):
    pack = write_pack(
        tmp_path, "base", rules=[RULE], profiles={"east": _profile_with_reference(ref)}
    )
    (pack / "templates").mkdir()
    prepare(pack)
    with pytest.raises(
        PackError, match=f"profile 'east': docx_reference '{ref}' is not an existing .docx file"
    ):
        load_pack("base", packs_dir=tmp_path, profile="east")
    issues = validate_pack("base", packs_dir=tmp_path)
    assert [i.level for i in issues] == ["error"] and "docx_reference" in issues[0].message


def test_pack_hash_ignores_dict_key_order_and_reference_path(tmp_path):
    pack = write_pack(tmp_path, "base", rules=[RULE])
    a = load_pack("base", packs_dir=tmp_path)
    flipped = dict(reversed(list(LEXICON["confidence_definitions"].items())))
    (pack / "lexicon.yaml").write_text(
        yaml.safe_dump({**LEXICON, "confidence_definitions": flipped}, sort_keys=False),
        encoding="utf-8",
    )
    b = load_pack("base", packs_dir=tmp_path)
    assert list(a.lexicon.confidence_definitions) != list(b.lexicon.confidence_definitions)
    assert pack_hash(a) == pack_hash(b) and len(pack_hash(a)) == 16
    c = a.model_copy(update={"docx_reference_path": tmp_path / "any.docx"})
    assert pack_hash(c) == pack_hash(a)


@pytest.mark.parametrize("content", [b"not a zip", b"\xd0\xcf\x11\xe0 encrypted OLE container"])
def test_docx_reference_must_open_as_a_docx_at_pack_load(tmp_path, content):
    pack = write_pack(
        tmp_path, "base", rules=[RULE], profiles={"east": _profile_with_reference("t.docx")}
    )
    (pack / "t.docx").write_bytes(content)
    with pytest.raises(PackError, match="not a readable .docx"):
        load_pack("base", packs_dir=tmp_path, profile="east")
    issues = validate_pack("base", packs_dir=tmp_path)
    where = (pack / "t.docx").resolve()
    assert [(i.level, i.message) for i in issues] == [
        (
            "error",
            f"profile 'east': docx_reference 't.docx' is not a readable .docx: "
            f"Package not found at '{where}'",
        )
    ]


def test_resolved_pack_json_schema_hides_the_reference_path():
    assert "docx_reference_path" not in ResolvedPack.model_json_schema()["properties"]


def test_validate_pack_prefixes_profile_errors_that_do_not_name_the_profile(tmp_path, monkeypatch):
    import corelata.standards.loader as loader

    write_pack(
        tmp_path, "base", rules=[RULE], profiles={"east": {"name": "east", "extends": "base"}}
    )
    real = loader.load_pack

    def failing(name, *, profile=None, **kw):
        if profile is not None:
            raise PackError("something broke")
        return real(name, **kw)

    monkeypatch.setattr(loader, "load_pack", failing)
    issues = validate_pack("base", packs_dir=tmp_path)
    assert [i.message for i in issues] == ["profile 'east': something broke"]


def test_list_packs_shows_the_builtin_pack_alone_without_a_packs_dir():
    [pack] = list_packs(None)
    assert pack.name == "icd203-base" and pack.builtin and pack.error is None
    assert pack.version and pack.profiles == []


def test_list_packs_merges_customer_packs_and_reports_broken_ones(tmp_path):
    write_pack(
        tmp_path,
        "team",
        rules=[],
        extends="icd203-base",
        profiles={
            "east": {"name": "east", "extends": "team", "draft": True, "tone": "brisk"},
            "west": {"name": "west", "extends": "team"},
        },
    )
    write_pack(tmp_path, "icd203-base", rules=[])  # a customer copy shadows the built-in one
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "pack.yaml").write_text("name: 1\n", encoding="utf-8")
    (tmp_path / "not-a-pack").mkdir()  # no pack.yaml: ignored
    packs = {p.name: p for p in list_packs(tmp_path)}
    assert sorted(packs) == ["broken", "icd203-base", "team"]
    assert not packs["icd203-base"].builtin
    team = packs["team"]
    assert team.extends == "icd203-base" and team.error is None
    assert [(p.name, p.draft, p.tone) for p in team.profiles] == [
        ("east", True, "brisk"),
        ("west", False, ""),
    ]
    assert packs["broken"].error is not None and "pack.yaml" in packs["broken"].error
    assert packs["broken"].profiles == [] and packs["broken"].version == ""


def test_resolve_profile_resolves_against_the_chain():
    from corelata.standards.loader import resolve_profile
    from corelata.standards.schema import Profile

    profile = Profile(name="p", extends="icd203-base", draft=True, tone="x")
    resolved = resolve_profile(profile)
    assert resolved.profile == "p" and resolved.tone == "x" and len(resolved.rules) == 17


def test_chain_profiles_names_the_nearest_owner(tmp_path):
    write_pack(
        tmp_path, "base", rules=[RULE], profiles={"shared": {"name": "shared", "extends": "base"}}
    )
    write_pack(
        tmp_path,
        "derived",
        rules=[],
        extends="base",
        template=None,
        lexicon=None,
        profiles={
            "shared": {"name": "shared", "extends": "derived"},
            "own": {"name": "own", "extends": "derived", "draft": True},
        },
    )
    assert chain_profiles("base", packs_dir=tmp_path) == {"shared": "base"}
    assert chain_profiles("derived", packs_dir=tmp_path) == {"shared": "derived", "own": "derived"}
    with pytest.raises(PackError, match="not found"):
        chain_profiles("nope", packs_dir=tmp_path)


def test_pack_dirs_signature_sees_a_nested_edit(tmp_path):
    from corelata.standards.loader import PACK_NAME_PATTERN, pack_dirs_signature

    write_pack(tmp_path, "team", rules=[RULE], extends="icd203-base")
    before = pack_dirs_signature(tmp_path)
    assert pack_dirs_signature(tmp_path) == before  # stable while nothing changes
    assert any(entry[0].endswith("icd203-base/pack.yaml") for entry in before)  # built-in included
    rule_file = next(tmp_path.glob("team/rules/*.yaml"))
    later = time.time() + 10
    os.utime(rule_file, (later, later))  # an edit inside rules/: the directory's mtime is unchanged
    assert pack_dirs_signature(tmp_path) != before
    assert pack_dirs_signature(None) == pack_dirs_signature(tmp_path / "missing")  # built-in only
    assert PACK_NAME_PATTERN.match("team-east") and not PACK_NAME_PATTERN.match("Customer_A")


def test_pack_dirs_signature_skips_a_file_that_vanished_mid_scan(tmp_path, monkeypatch):
    from corelata.standards.loader import pack_dirs_signature

    write_pack(tmp_path, "team", rules=[RULE])
    gone = tmp_path / "team" / "pack.yaml"
    before = pack_dirs_signature(tmp_path)
    assert any(entry[0] == str(gone) for entry in before)
    real_stat = Path.stat

    def stat(self, *args, **kwargs):
        # only the signature's own stat call fails; is_file() in the scan still sees the file
        if self == gone and sys._getframe(1).f_code.co_name == "pack_dirs_signature":
            raise FileNotFoundError(str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    after = pack_dirs_signature(tmp_path)
    assert all(entry[0] != str(gone) for entry in after)
    assert len(after) == len(before) - 1


def test_pack_dirs_signature_follows_a_symlinked_pack_and_stops_at_a_cycle(tmp_path):
    from corelata.standards.loader import list_packs, pack_dirs_signature

    elsewhere = write_pack(tmp_path / "elsewhere", "team", rules=[RULE], extends="icd203-base")
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "team").symlink_to(elsewhere, target_is_directory=True)
    (elsewhere / "rules" / "loop").symlink_to(elsewhere, target_is_directory=True)  # a cycle
    assert "team" in [p.name for p in list_packs(packs)]
    rule_file = next((elsewhere / "rules").glob("*.yaml"))
    before = pack_dirs_signature(packs)
    seen = [entry[0] for entry in before if entry[0].endswith(rule_file.name)]
    assert seen == [str(packs / "team" / "rules" / rule_file.name)]  # through the link, once
    assert list(before) == sorted(before)
    later = time.time() + 10
    os.utime(rule_file, (later, later))  # an edit inside the linked pack
    assert pack_dirs_signature(packs) != before


def test_pack_dirs_signature_skips_a_looping_symlink(tmp_path):
    from corelata.standards.loader import pack_dirs_signature

    packs = tmp_path / "packs"
    team = write_pack(packs, "team", rules=[RULE], extends="icd203-base")
    loop = team / "rules" / "self"
    loop.symlink_to(loop)  # stat() raises ELOOP
    signature = pack_dirs_signature(packs)
    assert signature
    assert str(loop) not in [entry[0] for entry in signature]
