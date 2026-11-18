"""`corelata pack diff` (spec §6.8): what changed between two resolved packs. Pure functions over
`ResolvedPack`; the CLI turns names, directories and run snapshots into packs first. Lists of
scalars diff as sets (added, removed), or as an `order` change when only the order differs; lists
of objects keyed by `id` or `term` diff per key."""

from typing import Any

from pydantic import BaseModel

from corelata.standards.schema import ResolvedPack, Rule


class FieldChange(BaseModel):
    field: str
    before: Any
    after: Any


class RuleChange(BaseModel):
    id: str
    changes: list[FieldChange]


class PackDiff(BaseModel):
    left: str  # how each side was named on the command line
    right: str
    identity: list[FieldChange]  # name, version, profile
    rules_added: list[str]
    rules_removed: list[str]
    rules_changed: list[RuleChange]
    template: list[FieldChange]
    lexicon: list[FieldChange]
    tone_changed: bool
    format: list[FieldChange]

    @property
    def empty(self) -> bool:
        return not (
            self.identity
            or self.rules_added
            or self.rules_removed
            or self.rules_changed
            or self.template
            or self.lexicon
            or self.tone_changed
            or self.format
        )


def _list_key(items: list[Any]) -> str | None:
    """The key that names every object in a list of dicts (`id`, then `term`), else None."""
    if not items or not all(isinstance(x, dict) for x in items):
        return None
    for key in ("id", "term"):
        if all(key in x for x in items):
            return key
    return None


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _diff_values(path: str, a: Any, b: Any, out: list[FieldChange]) -> None:
    if a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            _diff_values(_join(path, key), a.get(key), b.get(key), out)
        return
    if isinstance(a, list) and isinstance(b, list):
        key = _list_key(a + b)
        if key is not None:
            left = {x[key]: x for x in a}
            right = {x[key]: x for x in b}
            for k in sorted(set(left) | set(right)):
                _diff_values(f"{path}[{k}]", left.get(k), right.get(k), out)
            return
        removed = [x for x in a if x not in b]
        added = [x for x in b if x not in a]
        if removed:
            out.append(FieldChange(field=f"{path} removed", before=removed, after=None))
        if added:
            out.append(FieldChange(field=f"{path} added", before=None, after=added))
        if not removed and not added:  # same items, different order (order can be meaningful)
            out.append(FieldChange(field=f"{path} order", before=a, after=b))
        return
    out.append(FieldChange(field=path, before=a, after=b))


def _changes(a: BaseModel, b: BaseModel) -> list[FieldChange]:
    out: list[FieldChange] = []
    _diff_values("", a.model_dump(mode="json"), b.model_dump(mode="json"), out)
    return out


def diff_packs(
    left: ResolvedPack, right: ResolvedPack, *, left_name: str, right_name: str
) -> PackDiff:
    identity: list[FieldChange] = []
    for field in ("name", "version", "profile"):
        a, b = getattr(left, field), getattr(right, field)
        if a != b:
            identity.append(FieldChange(field=field, before=a, after=b))
    rules_a = {r.id: r for r in left.rules}
    rules_b = {r.id: r for r in right.rules}
    changed = []
    for rule_id in sorted(set(rules_a) & set(rules_b)):
        changes = _changes(rules_a[rule_id], rules_b[rule_id])
        if changes:
            changed.append(RuleChange(id=rule_id, changes=changes))
    return PackDiff(
        left=left_name,
        right=right_name,
        identity=identity,
        rules_added=sorted(set(rules_b) - set(rules_a)),
        rules_removed=sorted(set(rules_a) - set(rules_b)),
        rules_changed=changed,
        template=_changes(left.template, right.template),
        lexicon=_changes(left.lexicon, right.lexicon),
        tone_changed=left.tone != right.tone,
        format=_changes(left.format, right.format),
    )


def _change_line(c: FieldChange) -> str:
    """`field: before -> after`; a set change (`... added` / `... removed`) shows just its items."""
    if c.field.endswith(" added"):
        return f"{c.field}: {c.after}"
    if c.field.endswith(" removed"):
        return f"{c.field}: {c.before}"
    return f"{c.field}: {c.before} -> {c.after}"


def _rule_line(rule: Rule) -> str:
    return f"  {rule.id}  {rule.title} [{rule.severity.value}, {rule.checkability.value}]"


def format_diff(
    diff: PackDiff, *, left: ResolvedPack | None = None, right: ResolvedPack | None = None
) -> str:
    """The terminal rendering. `left`/`right` let added and removed rules show their title."""
    out = [f"pack diff: {diff.left} -> {diff.right}"]
    if diff.empty:
        return "\n".join([*out, "no differences"]) + "\n"
    for c in diff.identity:
        out.append(_change_line(c))
    out.append(f"rules added ({len(diff.rules_added)}):")
    for rule_id in diff.rules_added:
        out.append(_rule_line(right.rule(rule_id)) if right is not None else f"  {rule_id}")
    out.append(f"rules removed ({len(diff.rules_removed)}):")
    for rule_id in diff.rules_removed:
        out.append(_rule_line(left.rule(rule_id)) if left is not None else f"  {rule_id}")
    out.append(f"rules changed ({len(diff.rules_changed)}):")
    for rc in diff.rules_changed:
        out.append(f"  {rc.id}:")
        out += [f"    {_change_line(c)}" for c in rc.changes]
    for title, changes in (
        ("template", diff.template),
        ("lexicon", diff.lexicon),
        ("format", diff.format),
    ):
        if changes:
            out.append(f"{title}:")
            out += [f"  {_change_line(c)}" for c in changes]
    if diff.tone_changed:
        out.append("tone changed")
    return "\n".join(out) + "\n"
