"""Pure reconcile of the combo bill of materials (combos-propios C1).

Source-agnostic: a source adapter hands the DESIRED state as a snapshot
`{combo_item_id: {componente_item_id: cantidad}}` and this module diffs it
against the CURRENT stored rows (same shape) into inserts, quantity updates
and deletes. No database, no ERP.

Removal is by absence: sources have no deleted flag or timestamp, so a pair
missing from a full snapshot is deleted, and a combo missing from it loses all
its rows. A truncated or failed fetch would therefore wipe valid rows, so
deletions are skipped (inserts and updates still apply) when the snapshot is
empty or brings fewer than `PISO_SNAPSHOT_COMPLETO` of the stored combos. Only
stored combos count: combos new to the table do not make up for stored ones
the snapshot lost.

A source row whose quantity is missing, not a finite number, not positive at
the stored scale or beyond the stored precision is not a component: it is never
stored, and a stored pair the source now reports that way is deleted like an
absent one. One bad row never aborts the reconcile.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

logger = logging.getLogger(__name__)

# Minimum fraction of the stored combos a full snapshot must bring for its
# absences to be trusted as deletions. A healthy full fetch brings ~100%; this
# leaves wide margin without allowing a catastrophic wipe. Same value and
# reasoning as `RECONCILIACION_GLOBAL_PISO` in `sync_item_associations`.
PISO_SNAPSHOT_COMPLETO = 0.5

# `combo_componentes.cantidad` is Numeric(18, 4): 4 decimals, under 10**14.
_ESCALA = Decimal("0.0001")
_MAXIMO = Decimal(10) ** 14

Cantidad = Decimal | int | float | str | None
Componentes = dict[int, Decimal]
Bom = dict[int, Componentes]
Fila = tuple[int, int, Decimal]


@dataclass(frozen=True)
class Plan:
    """What to write so the stored rows match the desired snapshot."""

    inserts: tuple[Fila, ...] = ()
    updates: tuple[Fila, ...] = ()
    deletes: tuple[tuple[int, int], ...] = ()
    deletions_skipped: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.inserts or self.updates or self.deletes)


def _cantidad(value: Cantidad) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        cantidad = Decimal(str(value))
    except InvalidOperation:
        return None
    if not cantidad.is_finite() or cantidad <= 0 or cantidad >= _MAXIMO:
        return None
    cantidad = cantidad.quantize(_ESCALA, rounding=ROUND_HALF_UP)
    return cantidad if 0 < cantidad < _MAXIMO else None


def _componentes(componentes: Mapping[int, Cantidad]) -> Componentes:
    out: Componentes = {}
    for componente, value in componentes.items():
        cantidad = _cantidad(value)
        if cantidad is not None:
            out[componente] = cantidad
    return out


def normalize(snapshot: Mapping[int, Mapping[int, Cantidad]]) -> Bom:
    """Drop rows without a positive quantity, round to the stored scale and
    drop combos left without components."""
    out: Bom = {}
    for combo, componentes in snapshot.items():
        normalizados = _componentes(componentes)
        if normalizados:
            out[combo] = normalizados
    return out


def _diff(combo: int, desired: Componentes, current: Mapping[int, Decimal], *, delete: bool) -> tuple[list, list, list]:
    inserts, updates, deletes = [], [], []
    for componente, cantidad in sorted(desired.items()):
        stored = current.get(componente)
        if stored is None:
            inserts.append((combo, componente, cantidad))
        elif stored != cantidad:
            updates.append((combo, componente, cantidad))
    if delete:
        deletes = [(combo, componente) for componente in sorted(current) if componente not in desired]
    return inserts, updates, deletes


def plan_full(snapshot: Mapping[int, Mapping[int, Cantidad]], current: Mapping[int, Mapping[int, Decimal]]) -> Plan:
    """Reconcile a FULL snapshot (every combo the source knows) against all stored rows."""
    desired = normalize(snapshot)
    delete = True
    if not desired:
        if current:
            logger.warning(
                "combos reconcile: the snapshot brings no combos against %d stored -- deletions skipped "
                "(possible failed fetch)",
                len(current),
            )
            delete = False
    elif current and len(desired.keys() & current.keys()) < len(current) * PISO_SNAPSHOT_COMPLETO:
        logger.warning(
            "combos reconcile: the snapshot brings %d of %d stored combos, under the %.0f%% floor -- "
            "deletions skipped (possible truncated fetch)",
            len(desired.keys() & current.keys()),
            len(current),
            PISO_SNAPSHOT_COMPLETO * 100,
        )
        delete = False

    inserts, updates, deletes = [], [], []
    for combo in sorted(set(desired) | set(current)):
        i, u, d = _diff(combo, desired.get(combo, {}), current.get(combo, {}), delete=delete)
        inserts += i
        updates += u
        deletes += d
    return Plan(tuple(inserts), tuple(updates), tuple(deletes), deletions_skipped=not delete)


def plan_combo(combo_item_id: int, componentes: Mapping[int, Cantidad], current: Mapping[int, Decimal]) -> Plan:
    """Reconcile ONE combo: `componentes` is its complete desired composition,
    `current` its stored rows. An empty composition deletes nothing (it may be
    a failed fetch): removing a whole combo is only done by a full snapshot."""
    desired = _componentes(componentes)
    delete = bool(desired)
    if not delete and current:
        logger.warning(
            "combos reconcile: combo %s comes with no components -- deletions skipped (possible failed fetch)",
            combo_item_id,
        )
    inserts, updates, deletes = _diff(combo_item_id, desired, current, delete=delete)
    return Plan(tuple(inserts), tuple(updates), tuple(deletes), deletions_skipped=not delete and bool(current))
