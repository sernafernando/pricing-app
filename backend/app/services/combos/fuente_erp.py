"""ERP source of the combo bill of materials (combos-propios C1).

The ONLY ERP-aware piece of the combos module: it fetches every association
from the current ERP (`scriptItemAssociation` through the gbp-parser, the same
unfiltered call `app.scripts.sync_item_associations` makes, reusing its fetch
helper) and maps it to the neutral snapshot `{combo: {component: quantity}}`
that `app.services.combos.reconcile` understands. Replacing the ERP means
replacing this module; the table and the reconcile stay.

ERP fields: `item_id` is the combo, `item_id_1` the component and `iasso_qty`
the quantity. A row whose quantity is missing or not positive is not a
component and is skipped; a pair that appears twice holds the sum (the same
rules as the migration's initial fill).

Fail closed: the reconcile deletes by absence, so a snapshot that silently
dropped a row would delete a valid pair. A record that is not an object, a row
without its combo or component, a non-integer combo or component id, an
unreadable quantity, or rows from more than one ERP company (`comp_id`, a
missing one counting as its own: the app-owned table has no company) raise
`SnapshotIncompleto` and nothing is written. The fetch itself raises on a
connection error, a non-2xx status, a body that is not JSON or not a list, and
past its wall-clock bound.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from app.scripts.sync_item_associations import fetch_item_associations_from_erp

Snapshot = dict[int, dict[int, Decimal]]


class SnapshotIncompleto(Exception):
    """The ERP response cannot be trusted as the complete set of combos."""


def _cantidad(registro: Mapping[str, Any]) -> Decimal | None:
    value = registro.get("iasso_qty")
    if value is None:
        return None
    try:
        cantidad = Decimal(str(value))
    except (InvalidOperation, ValueError):
        cantidad = None
    if cantidad is None or not cantidad.is_finite():
        raise SnapshotIncompleto(f"unreadable iasso_qty {value!r} in itema_id={registro.get('itema_id')}")
    return cantidad


def _item_id(registro: Mapping[str, Any], campo: str) -> int:
    """An ERP item id: an int or a string of digits, nothing that `int()` would
    coerce silently (a bool, a float) or reject."""
    value = registro.get(campo)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise SnapshotIncompleto(f"non-integer {campo} {value!r} in itema_id={registro.get('itema_id')}")


def snapshot_desde_registros(registros: Iterable[Mapping[str, Any]]) -> Snapshot:
    """Map raw `scriptItemAssociation` records to the neutral snapshot."""
    snapshot: Snapshot = {}
    companias = set()
    for registro in registros:
        if not isinstance(registro, Mapping):
            raise SnapshotIncompleto(f"association record is not an object: {registro!r}")
        if registro.get("item_id") is None or registro.get("item_id_1") is None:
            raise SnapshotIncompleto(f"association without item_id/item_id_1: itema_id={registro.get('itema_id')}")
        combo, componente = _item_id(registro, "item_id"), _item_id(registro, "item_id_1")
        companias.add(registro.get("comp_id", 1))
        cantidad = _cantidad(registro)
        if cantidad is None or cantidad <= 0:
            continue
        componentes = snapshot.setdefault(combo, {})
        componentes[componente] = componentes.get(componente, Decimal(0)) + cantidad
    if len(companias) > 1:
        # repr-sorted: a missing (None) company and a numeric one cannot be compared.
        listado = ", ".join(sorted(repr(c) for c in companias))
        raise SnapshotIncompleto(f"associations from more than one ERP company: {listado}")
    return snapshot


def fetch_snapshot(timeout: float) -> Snapshot:
    """Fetch every association from the ERP (unfiltered) as a neutral snapshot,
    returning or raising within `timeout` seconds of wall-clock time.

    Half the budget bounds the whole response and half each wait for bytes, so
    a slow-dripping server cannot hold the caller past `timeout`. Strict: a
    response that is not a list raises instead of reading as "no combos"."""
    mitad = timeout / 2
    return snapshot_desde_registros(fetch_item_associations_from_erp(timeout=mitad, total_timeout=mitad, strict=True))
