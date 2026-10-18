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
without its combo or component, a combo or component id that is not a
positive integer, an unreadable quantity, or rows from more than one ERP
company (`comp_id`; an absent key is an unknown company of its own, so it
never merges with company 1 or a null: the app-owned table has no company) raise
`SnapshotIncompleto` and nothing is written. The fetch itself raises on a
connection error, a non-2xx status, a body that is not JSON or not a list, and
past its wall-clock bound.
"""

from __future__ import annotations

import re
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


_ID_ASCII = re.compile(r"[0-9]+")

# Stands for a record with no `comp_id` key: an unknown company of its own,
# never assumed to be company 1 nor equal to an explicit null.
_SIN_COMPANIA = "<comp_id absent>"


def _item_id(registro: Mapping[str, Any], campo: str) -> int:
    """An ERP item id: a positive int, or a string of ASCII digits only (no
    sign, spaces or non-ASCII digits). Nothing `int()` would coerce silently (a
    bool, a float) and no zero or negative id."""
    value = registro.get(campo)
    if isinstance(value, int) and not isinstance(value, bool):
        item_id = value
    elif isinstance(value, str) and _ID_ASCII.fullmatch(value):
        item_id = int(value)
    else:
        item_id = 0
    if item_id > 0:
        return item_id
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
        companias.add(registro.get("comp_id", _SIN_COMPANIA))
        cantidad = _cantidad(registro)
        if cantidad is None or cantidad <= 0:
            continue
        componentes = snapshot.setdefault(combo, {})
        componentes[componente] = componentes.get(componente, Decimal(0)) + cantidad
    if len(companias) > 1:
        # repr-sorted: an absent, a null and a numeric company cannot be compared.
        listado = ", ".join(sorted(repr(c) for c in companias))
        raise SnapshotIncompleto(f"associations from more than one ERP company: {listado}")
    return snapshot


def fetch_snapshot(timeout: float) -> Snapshot:
    """Fetch every association from the ERP (unfiltered) as a neutral snapshot,
    returning or raising within `timeout` seconds of wall-clock time.

    The whole budget is the helper's total bound, which holds whatever the
    network does (DNS, connect, a server dripping bytes). Strict: a response
    that is not a list raises instead of reading as "no combos"."""
    return snapshot_desde_registros(
        fetch_item_associations_from_erp(timeout=timeout, total_timeout=timeout, strict=True)
    )
