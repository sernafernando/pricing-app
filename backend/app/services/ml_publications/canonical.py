"""Canonical form and hash of ML payloads (pure, no I/O).

The canonical form makes the comparison independent of presentation order:

- object keys are sorted;
- arrays of objects that all carry a non-null, unique key (default `id`, or the
  per-resource override) are sorted by that key;
- arrays of scalars are compared as sets (sorted, de-duplicated);
- any other array keeps its order.

`array_keys` maps the path of an array to the key fields tried in order for each
element (first non-null wins). The path of the root array is `""`; nested arrays
use dotted object paths (`results`, `shipping.methods`). Arrays not listed use
`DEFAULT_KEY_FIELDS`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional, Sequence

DEFAULT_KEY_FIELDS: tuple[str, ...] = ("id",)

ArrayKeys = Mapping[str, Sequence[str]]


def resolve_array_keys(spec: Any) -> ArrayKeys:
    """Accept an `array_keys` mapping or any object exposing `.array_keys`."""
    if spec is None:
        return {}
    if isinstance(spec, Mapping):
        return spec
    return getattr(spec, "array_keys", {}) or {}


def child_path(parent: str, key: str) -> str:
    return key if not parent else f"{parent}.{key}"


def key_fields_for(array_keys: ArrayKeys, path: str) -> Sequence[str]:
    return array_keys.get(path, DEFAULT_KEY_FIELDS)


def element_key(element: Any, fields: Sequence[str]) -> Optional[str]:
    """Key of one array element, or None when no key field is present and non-null.

    The key is the string form of the value, so the ids `1` and `"1"` collide; the
    caller then sees a duplicate key and keeps the array unsorted (order-sensitive),
    which is the safe side: no normalization, never a false "no change".
    """
    if not isinstance(element, dict):
        return None
    for field in fields:
        value = element.get(field)
        if value is not None and not isinstance(value, (dict, list)):
            return str(value)
    return None


def keyed_elements(items: list, fields: Sequence[str]) -> Optional[dict[str, Any]]:
    """Map key -> element when EVERY element has a unique key, else None."""
    if not items:
        return None
    keyed: dict[str, Any] = {}
    for element in items:
        key = element_key(element, fields)
        if key is None or key in keyed:
            return None
        keyed[key] = element
    return keyed


def is_scalar_array(items: list) -> bool:
    return bool(items) and all(not isinstance(v, (dict, list)) for v in items)


def scalar_sort_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def canonical(doc: Any, spec: Any = None, _path: str = "") -> Any:
    """Return the canonical form of `doc` (a new structure; `doc` is untouched)."""
    array_keys = resolve_array_keys(spec)
    if isinstance(doc, dict):
        return {k: canonical(doc[k], array_keys, child_path(_path, k)) for k in sorted(doc)}
    if isinstance(doc, list):
        keyed = keyed_elements(doc, key_fields_for(array_keys, _path))
        if keyed is not None:
            return [canonical(keyed[k], array_keys, _path) for k in sorted(keyed)]
        if is_scalar_array(doc):
            unique = {scalar_sort_key(v): v for v in doc}
            return [unique[k] for k in sorted(unique)]
        return [canonical(v, array_keys, _path) for v in doc]
    return doc


def canonical_hash(doc: Any, spec: Any = None) -> bytes:
    """sha256 of the canonical JSON of `doc` (exact integers, no whitespace)."""
    text = json.dumps(canonical(doc, spec), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).digest()
