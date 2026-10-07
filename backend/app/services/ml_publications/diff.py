"""Path-level diff engine over ML payloads (pure, no I/O).

Path syntax: dotted object keys (`shipping.logistic_type`), `[key]` for a
keyed-array element (`attributes[BRAND].value_name`), `[=value]` for a member of
a scalar set (`tags[=cart_eligible]`). The characters `. [ ] \\` inside a key are
escaped with a backslash. The root array of a payload has the empty path, so its
elements read `[C-123].status`.

Each `Change` carries an operation: `add` has no old value, `remove` has no new
value (both use the `MISSING` sentinel), `replace` covers every value change
including an explicit JSON null on either side, so "absent" and "null" stay
distinguishable.

Two kinds of arrays are compared element by element: arrays whose elements all
have a unique key (default `id`, or the per-resource override in
`ARRAY_KEYS_BY_RESOURCE`) and arrays of scalars (compared as sets). Any other
array is reported whole at the array path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from app.services.ml_publications.canonical import (
    ArrayKeys,
    canonical,
    child_path,
    key_fields_for,
    keyed_elements,
    resolve_array_keys,
    scalar_sort_key,
)


class _Missing:
    """Sentinel for "no value" (absent key), distinct from JSON null."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False

    def __deepcopy__(self, memo):
        return self

    def __copy__(self):
        return self


MISSING: Any = _Missing()

# Per-resource natural keys for arrays whose elements have no `id` (design D7).
# Wired as data now; the parsers that use them arrive with their resources.
ARRAY_KEYS_BY_RESOURCE: dict[str, ArrayKeys] = {
    # Seller promotions: `id`, falling back to `type` (PRICE_DISCOUNT carries no id).
    "promotions": {"": ("id", "type")},
    # Visits time window: one element per day.
    "visits": {"results": ("date",)},
}


def array_keys_for(resource_type: str) -> ArrayKeys:
    return ARRAY_KEYS_BY_RESOURCE.get(resource_type, {})


# Paths whose changes are noise without business meaning, keyed by
# (resource_type, path glob; `*` matches any run of characters). EVERY entry needs a
# written justification with evidence from captures or measured churn. Empty by
# default: anything not listed is recorded (spec "Volatile and excluded field policy").
EXCLUDED_NOISE: dict[tuple[str, str], str] = {
    ("sale_price", "reference_date"): (
        "`reference_date` of `GET /items/{id}/sale_price` is the time ML answered, not data about the item: "
        "in all four captures of 2026-10-06 (sale_price_20261006.json) it equals the response `Date` header "
        "to the second (13:24:08, 13:24:27, 13:23:59, 13:24:01), so it differs on every fetch while the price "
        "is unchanged and would write one change-log row per fetch. The raw body is still stored with it."
    ),
}


@dataclass(frozen=True)
class Change:
    path: str
    op: Literal["add", "remove", "replace"]
    old: Any = MISSING
    new: Any = MISSING

    def as_dict(self) -> dict:
        """JSON form stored in the change log: `{"p", "op", "old"?, "new"?}`."""
        entry: dict[str, Any] = {"p": self.path, "op": self.op}
        if self.old is not MISSING:
            entry["old"] = self.old
        if self.new is not MISSING:
            entry["new"] = self.new
        return entry


_ESCAPED = ("\\", ".", "[", "]")


def escape_key(key: Any) -> str:
    text = str(key)
    for char in _ESCAPED:
        text = text.replace(char, "\\" + char)
    return text


def member_label(value: Any) -> str:
    """Path label of a scalar-set member: strings as is, other types JSON-encoded behind `~`.

    Keeps `None`, `1` and the strings "None", "1" on distinct paths.
    """
    if isinstance(value, str):
        label = escape_key(value)
        return "\\" + label if label.startswith("~") else label
    return "~" + escape_key(json.dumps(value, ensure_ascii=False))


def _same_scalar(a: Any, b: Any) -> bool:
    # JSON text equality, so 1 vs 1.0 vs true are different (consistent with the hash).
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def diff(old: Any, new: Any, spec: Any = None) -> list[Change]:
    """Changes needed to go from `old` to `new`; `[]` when canonically identical."""
    changes: list[Change] = []
    _diff(old, new, "", "", resolve_array_keys(spec), changes)
    return changes


def _diff(old: Any, new: Any, path: str, schema: str, array_keys: ArrayKeys, out: list[Change]) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            sub_path = child_path(path, escape_key(key))
            sub_schema = child_path(schema, key)
            if key not in new:
                out.append(Change(sub_path, "remove", old=old[key]))
            elif key not in old:
                out.append(Change(sub_path, "add", new=new[key]))
            else:
                _diff(old[key], new[key], sub_path, sub_schema, array_keys, out)
        return
    if isinstance(old, list) and isinstance(new, list):
        _diff_arrays(old, new, path, schema, array_keys, out)
        return
    if isinstance(old, (dict, list)) or isinstance(new, (dict, list)):
        out.append(Change(path, "replace", old, new))
        return
    if not _same_scalar(old, new):
        out.append(Change(path, "replace", old, new))


def _diff_arrays(old: list, new: list, path: str, schema: str, array_keys: ArrayKeys, out: list[Change]) -> None:
    fields = key_fields_for(array_keys, schema)
    old_keyed = {} if not old else keyed_elements(old, fields)
    new_keyed = {} if not new else keyed_elements(new, fields)
    if old_keyed is not None and new_keyed is not None:
        for key in sorted(set(old_keyed) | set(new_keyed)):
            element_path = f"{path}[{escape_key(key)}]"
            if key not in new_keyed:
                out.append(Change(element_path, "remove", old=old_keyed[key]))
            elif key not in old_keyed:
                out.append(Change(element_path, "add", new=new_keyed[key]))
            else:
                _diff(old_keyed[key], new_keyed[key], element_path, schema, array_keys, out)
        return

    if _is_scalar_set(old) and _is_scalar_set(new):
        old_members = {scalar_sort_key(v): v for v in old}
        new_members = {scalar_sort_key(v): v for v in new}
        for member_key in sorted(set(old_members) | set(new_members)):
            if member_key in old_members and member_key in new_members:
                continue
            value = old_members.get(member_key, new_members.get(member_key))
            member_path = f"{path}[={member_label(value)}]"
            if member_key in old_members:
                out.append(Change(member_path, "remove", old=value))
            else:
                out.append(Change(member_path, "add", new=value))
        return

    # No usable keys: report the whole array when its canonical content differs.
    if canonical(old, array_keys, schema) != canonical(new, array_keys, schema):
        out.append(Change(path, "replace", old, new))


def _is_scalar_set(items: Sequence) -> bool:
    return all(not isinstance(v, (dict, list)) for v in items)


def assert_justified(noise: Mapping[tuple[str, str], str]) -> None:
    """Raise when any excluded-noise entry lacks a non-blank justification."""
    for (resource_type, glob), justification in noise.items():
        if not isinstance(justification, str) or not justification.strip():
            raise ValueError(f"EXCLUDED_NOISE entry ({resource_type!r}, {glob!r}) has no justification")


def _glob_matches(glob: str, path: str) -> bool:
    pattern = "".join(".*" if part == "*" else re.escape(part) for part in re.split(r"(\*)", glob))
    # The path itself or any descendant (`.child` or `[element]`).
    return re.fullmatch(pattern + r"(?:[.\[].*)?", path) is not None


def split_excluded(
    changes: Sequence[Change], resource_type: str, noise: Mapping[tuple[str, str], str] | None = None
) -> tuple[list[Change], list[Change]]:
    """Split `changes` into (reportable, excluded-noise) for one resource type."""
    active = EXCLUDED_NOISE if noise is None else noise
    assert_justified(active)
    globs = [glob for (rtype, glob) in active if rtype == resource_type]
    reportable: list[Change] = []
    excluded: list[Change] = []
    for change in changes:
        (excluded if any(_glob_matches(g, change.path) for g in globs) else reportable).append(change)
    return reportable, excluded


def paths_of(changes: Sequence[Change]) -> list[str]:
    return [c.path for c in changes]


__all__ = [
    "ARRAY_KEYS_BY_RESOURCE",
    "EXCLUDED_NOISE",
    "MISSING",
    "Change",
    "assert_justified",
    "split_excluded",
    "array_keys_for",
    "diff",
    "escape_key",
    "paths_of",
]
