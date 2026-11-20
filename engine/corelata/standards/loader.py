"""Read pack directories, follow `extends`, apply a profile, hash the result (spec §6)."""

import hashlib
import json
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import docx
import yaml
from docx.opc.exceptions import PackageNotFoundError
from lxml import etree
from pydantic import BaseModel, ValidationError

from corelata.config import ConfigIssue
from corelata.standards.schema import (
    SOURCE_SUMMARY,
    Lexicon,
    PackMeta,
    Profile,
    ProfileFormat,
    ResolvedPack,
    Rule,
    Template,
)

BUILTIN_PACKS_DIR = Path(__file__).parent / "packs"
# What `/api/packs/{name}` accepts; a directory named otherwise loads but cannot be addressed
# through the API (the doctor warns about it, R-M9-7).
PACK_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
# ...and its length limit. The route's `max_length` and the doctor share both (R-M10-4).
PACK_NAME_MAX_LENGTH = 100
# What python-docx raises for a file it cannot open as a .docx (shared with the DOCX renderer).
DOCX_OPEN_ERRORS = (
    PackageNotFoundError,
    KeyError,
    ValueError,
    OSError,
    zipfile.BadZipFile,
    etree.XMLSyntaxError,
)


class PackError(ValueError):
    """A pack directory is unusable; the message names the file and the problem. `public` is
    what an API client sees: the message itself unless it names server paths, which only the
    log gets (CRL-114, the rule of CRL-75 and CRL-86)."""

    def __init__(self, message: str, *, public: str | None = None) -> None:
        super().__init__(message)
        self.public = message if public is None else public


@dataclass
class RawPack:
    meta: PackMeta
    rules: list[Rule]
    template: Template | None
    lexicon: Lexicon | None
    profiles: dict[str, Profile]
    path: Path | None


def _read_yaml(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PackError(f"{path.name}: invalid YAML: {' '.join(str(e).split())}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise PackError(f"{path.name}: cannot read: {e}") from e


def _model[M: BaseModel](path: Path, model: type[M], data: object) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "(top level)"
        raise PackError(f"{path.name}: {where}: {first['msg']}") from e


def find_pack_dir(name: str, packs_dir: Path | None) -> Path:
    for base in (packs_dir, BUILTIN_PACKS_DIR):
        if base is not None and (base / name / "pack.yaml").is_file():
            return base / name
    looked = ", ".join(str(b) for b in (packs_dir, BUILTIN_PACKS_DIR) if b is not None)
    raise PackError(
        f"pack '{name}' not found (looked in {looked})", public=f"pack '{name}' not found"
    )


def read_pack_dir(path: Path) -> RawPack:
    meta = _model(path / "pack.yaml", PackMeta, _read_yaml(path / "pack.yaml"))
    rules: list[Rule] = []
    rules_dir = path / "rules"
    for file in sorted(rules_dir.glob("*.yaml")) if rules_dir.is_dir() else []:
        rule = _model(file, Rule, _read_yaml(file))
        if rule.id != file.stem:
            raise PackError(f"{file.name}: rule id '{rule.id}' must match the file name")
        rules.append(rule)
    template = lexicon = None
    if (path / "template.yaml").is_file():
        template = _model(path / "template.yaml", Template, _read_yaml(path / "template.yaml"))
    if (path / "lexicon.yaml").is_file():
        lexicon = _model(path / "lexicon.yaml", Lexicon, _read_yaml(path / "lexicon.yaml"))
        for t in lexicon.likelihood:
            if t.low >= t.high:
                raise PackError(f"lexicon.yaml: likelihood '{t.term}': low must be below high")
    profiles: dict[str, Profile] = {}
    profiles_dir = path / "profiles"
    for file in sorted(profiles_dir.glob("*.yaml")) if profiles_dir.is_dir() else []:
        profile = _model(file, Profile, _read_yaml(file))
        profiles[profile.name] = profile
    return RawPack(meta, rules, template, lexicon, profiles, path)


class ProfileSummary(BaseModel):
    name: str
    draft: bool
    tone: str


class PackSummary(BaseModel):
    """One entry of `GET /api/packs` (spec §10.1): a pack directory as found, built-in packs
    included. `name` is the directory name, which is what `load_pack` takes."""

    name: str
    version: str
    extends: str | None
    description: str
    builtin: bool
    profiles: list[ProfileSummary]
    error: str | None = None  # the directory does not load as a pack; the message says why


def _summary(path: Path, builtin: bool) -> PackSummary:
    try:
        raw = read_pack_dir(path)
    except PackError as e:
        return PackSummary(
            name=path.name,
            version="",
            extends=None,
            description="",
            builtin=builtin,
            profiles=[],
            error=str(e),
        )
    return PackSummary(
        name=path.name,
        version=raw.meta.version,
        extends=raw.meta.extends,
        description=raw.meta.description,
        builtin=builtin,
        profiles=[
            ProfileSummary(name=p.name, draft=p.draft, tone=p.tone) for p in raw.profiles.values()
        ],
    )


def list_packs(packs_dir: Path | None) -> list[PackSummary]:
    """Every directory with a pack.yaml in `packs_dir` and the built-in directory, by name. A
    customer pack shadows a built-in one of the same name (as `find_pack_dir` resolves it). A
    directory that does not load is listed with its error, so an operator sees it instead of a
    missing entry."""
    found: dict[str, PackSummary] = {}
    for base, builtin in ((BUILTIN_PACKS_DIR, True), (packs_dir, False)):
        if base is None or not base.is_dir():
            continue
        for path in sorted(p for p in base.iterdir() if (p / "pack.yaml").is_file()):
            found[path.name] = _summary(path, builtin)
    return [found[name] for name in sorted(found)]


def pack_dirs_signature(packs_dir: Path | None) -> tuple[tuple[str, int, int], ...]:
    """Every file under the pack directories with its size and mtime (ns), sorted. Equal
    signatures mean the listing is unchanged; directory mtimes alone miss an edit inside rules/
    (R-M9-4). Symlinked directories are walked too, each real directory once, so a link cycle
    ends the walk (R-M10-3). Stats only: no file is opened."""
    out: list[tuple[str, int, int]] = []
    visited: set[str] = set()
    for base in (BUILTIN_PACKS_DIR, packs_dir):
        if base is None or not base.is_dir():
            continue
        for top, dirs, files in os.walk(base, followlinks=True):
            real = os.path.realpath(top)
            if real in visited:
                dirs[:] = []  # a cycle, or a second link to a directory already walked
                continue
            visited.add(real)
            for name in files:
                path = Path(top, name)
                try:
                    st = path.stat()
                except OSError:  # gone or unresolvable (dangling or looping link) since the walk
                    continue
                out.append((str(path), st.st_size, st.st_mtime_ns))
    return tuple(sorted(out))


def _chain(name: str, packs_dir: Path | None) -> list[RawPack]:
    """Base-first list of packs: the named pack's ancestors, then itself."""
    chain: list[RawPack] = []
    seen: list[str] = []
    current: str | None = name
    while current is not None:
        if current in seen:
            raise PackError(f"extends cycle: {' -> '.join([*seen, current])}")
        seen.append(current)
        pack = read_pack_dir(find_pack_dir(current, packs_dir))
        chain.insert(0, pack)
        current = pack.meta.extends
    return chain


def resolve(chain: list[RawPack], profile: Profile | None) -> ResolvedPack:
    rules: dict[str, tuple[Rule, str]] = {}
    template: Template | None = None
    lexicon: Lexicon | None = None
    for pack in chain:
        for r in pack.rules:
            if r.id in rules:
                raise PackError(
                    f"rule '{r.id}' defined in both '{rules[r.id][1]}' and '{pack.meta.name}'"
                )
            rules[r.id] = (r, pack.meta.name)
        template = pack.template or template
        lexicon = pack.lexicon or lexicon
    leaf = chain[-1]
    if template is None:
        raise PackError(f"pack '{leaf.meta.name}': no template.yaml in it or its ancestors")
    if lexicon is None:
        raise PackError(f"pack '{leaf.meta.name}': no lexicon.yaml in it or its ancestors")
    tone = ""
    fmt = ProfileFormat()
    if profile is not None:
        for rid in profile.rules.disable:
            if rid not in rules:
                raise PackError(f"profile '{profile.name}' disables unknown rule '{rid}'")
            del rules[rid]
        for ov in profile.rules.override:
            if ov.id not in rules:
                raise PackError(f"profile '{profile.name}' overrides unknown rule '{ov.id}'")
            base, origin = rules[ov.id]
            changes = {k: v for k, v in ov.model_dump().items() if k != "id" and v is not None}
            rules[ov.id] = (base.model_copy(update=changes), origin)
        for r in profile.rules.add:
            if r.id in rules:
                raise PackError(f"profile '{profile.name}' adds rule '{r.id}' that already exists")
            rules[r.id] = (r, profile.name)
        source_access = lexicon.source_access
        if profile.template is not None:
            switches = {"source_summary", "source_details"}
            changes = {
                k: v
                for k, v in profile.template.model_dump().items()
                if v is not None and k not in switches
            }
            if "key_judgments" in changes:
                changes["key_judgments"] = profile.template.key_judgments
            if profile.template.source_summary is False:  # CRL-96: the profile turns them off
                order = [s for s in template.section_order if s != SOURCE_SUMMARY]
                changes["section_order"] = order
            if profile.template.source_details is False:
                source_access = []
            template = template.model_copy(update=changes)
        lexicon = lexicon.model_copy(
            update={
                "handling_markings": [
                    *lexicon.handling_markings,
                    *profile.lexicon.handling_markings,
                ],
                "source_descriptors": [
                    *lexicon.source_descriptors,
                    *profile.lexicon.source_descriptors,
                ],
                "source_access": source_access,
            }
        )
        tone = profile.tone
        fmt = profile.format
    return ResolvedPack(
        name=leaf.meta.name,
        version=leaf.meta.version,
        profile=None if profile is None else profile.name,
        rules=[rules[k][0] for k in sorted(rules)],
        template=template,
        lexicon=lexicon,
        tone=tone,
        format=fmt,
    )


def load_pack(
    name: str,
    *,
    packs_dir: Path | None = None,
    profile: str | None = None,
    allow_draft: bool = False,
) -> ResolvedPack:
    chain = _chain(name, packs_dir)
    chosen: Profile | None = None
    owner: RawPack | None = None
    if profile is not None:
        for pack in reversed(chain):
            if profile in pack.profiles:
                chosen, owner = pack.profiles[profile], pack
                break
        if chosen is None:
            raise PackError(f"profile '{profile}' not found in pack '{name}' or its ancestors")
        if chosen.draft and not allow_draft:
            raise PackError(
                f"profile '{profile}' is a draft (draft: true); review it and remove the flag"
            )
    resolved = resolve(chain, chosen)
    if chosen is not None and owner is not None:
        resolved.docx_reference_path = _docx_reference_path(chosen, owner)
    return resolved


def resolve_profile(profile: Profile, *, packs_dir: Path | None = None) -> ResolvedPack:
    """Resolve a profile that is not (yet) in any pack directory against the pack it extends
    (`corelata profile extract` proves its draft loads before writing it)."""
    return resolve(_chain(profile.extends, packs_dir), profile)


def chain_profiles(name: str, packs_dir: Path | None = None) -> dict[str, str]:
    """Profile name -> the pack in `name`'s chain that defines it, the way `load_pack` finds them:
    the nearest pack wins. `corelata profile extract` warns when a new draft would shadow one."""
    owners: dict[str, str] = {}
    for pack in _chain(name, packs_dir):  # base first, so a descendant overwrites
        for profile_name in pack.profiles:
            owners[profile_name] = pack.meta.name
    return owners


def _docx_reference_path(profile: Profile, owner: RawPack) -> Path | None:
    """The profile's reference document, absolute, verified to exist and to open as a .docx
    (Review Focus 2), so a bad template fails at pack load, never after a run has finished."""
    ref = profile.format.docx_reference
    if ref is None:
        return None
    base = owner.path if owner.path is not None else Path.cwd()
    path = (ref if ref.is_absolute() else base / ref).resolve()
    if path.suffix.lower() != ".docx" or not path.is_file():
        raise PackError(
            f"profile '{profile.name}': docx_reference '{ref}' is not an existing .docx file"
        )
    try:
        docx.Document(str(path))
    except DOCX_OPEN_ERRORS as e:
        raise PackError(
            f"profile '{profile.name}': docx_reference '{ref}' is not a readable .docx: {e}"
        ) from e
    return path


def pack_hash(pack: ResolvedPack) -> str:
    """SHA-256 (first 16 hex chars) of a key-sorted compact JSON dump: independent of YAML key
    order and of anything excluded from the dump, so the same pack hashes alike everywhere."""
    data = pack.model_dump(mode="json")
    dump = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()[:16]


def validate_pack(name_or_path: str, packs_dir: Path | None = None) -> list[ConfigIssue]:
    """`corelata pack validate`: every problem as an issue; never raises for pack content."""
    issues: list[ConfigIssue] = []
    path = Path(name_or_path)
    try:
        if path.is_dir():
            raw = read_pack_dir(path)
            packs_dir = path.parent
        else:
            raw = read_pack_dir(find_pack_dir(name_or_path, packs_dir))
        load_pack(raw.meta.name, packs_dir=packs_dir)
    except PackError as e:
        return [ConfigIssue(level="error", message=str(e))]
    for pname, profile in raw.profiles.items():
        if profile.draft:
            issues.append(ConfigIssue(level="warning", message=f"profile '{pname}' is a draft"))
        try:
            load_pack(raw.meta.name, packs_dir=packs_dir, profile=pname, allow_draft=True)
        except PackError as e:
            message = str(e)
            if not message.startswith(f"profile '{pname}'"):  # most profile errors name it
                message = f"profile '{pname}': {message}"
            issues.append(ConfigIssue(level="error", message=message))
    return issues
