"""Repair frozen cost snapshots written before the cost-zero / IVA-zero guard
shipped (see `costeo_service.tiene_costo_propio` / `tiene_iva_conocido`).

WHY this needs a script rather than a plain UPDATE: `ml_order_item_costos`
is INSERT-only by design (`ON CONFLICT DO NOTHING`, see that model's module
docstring) so a re-ingestion never rewrites an already-frozen row. Before the
guard, `_resolve_cost` froze `producto.costo`/`producto.iva` verbatim even
when the ERP sync had written `0.0` for "no real value" (the sync's own
`convertir_a_numero(..., 0)` default, NEVER `None` -- see
`costeo_service.tiene_costo_propio`'s docstring). A `0` frozen there is not a
snapshot of a real cost or a real 21%-or-whatever IVA rate: it is corruption
that inflates the "Total Gauss" bottom line of every sale it touches, exactly
like a product that costs nothing or carries no tax. It has no more business
staying in an immutable table than a bit-flipped row would.

DELETING is the only way to correct an INSERT-only table on purpose: an
UPDATE would be indistinguishable, downstream, from every other row this
table's own docstring guarantees is never rewritten, and this script exists
specifically because that guarantee was violated by a bug, not by production
in disagreement with the code. `ON CONFLICT DO NOTHING` remains untouched --
this script is the ONE place allowed to delete from this table, and it does
so ONLY for rows matching the exact criterion below, never as a general
cleanup tool.

CRITERION -- the SAME one the live path (`costeo_service`) already applies,
translated to the FROZEN columns instead of `ProductoERP.costo`/`.iva`:
    - `costo_unitario_ars <= 0` (mirrors `tiene_costo_propio`)
    - `iva_pct <= 0` (mirrors `tiene_iva_conocido`)
A row matching either is deleted; the two reasons are counted separately
because a wrong cost and a wrong tax rate get fixed by re-resolving
different inputs, even though today the correction path (re-`congelar()`)
happens to run through the same code for both.

RE-FREEZING reuses `costeo_service.congelar()` UNCHANGED -- it already knows
how to sum a combo's components (`FUENTE_COMBO`) and already refuses to
write a hole as a zero. Re-running it over the WHOLE order (not just the
deleted item) is deliberate and safe: `congelar()`'s own `ya_congelados`
existence guard means every OTHER already-frozen item on that order is a
structural no-op, so this can never touch a row it did not just delete.

An item that still cannot be costed under the current rules is left WITHOUT
a row on purpose ("unknown is not zero" -- same discipline every other
corner of this module follows). A visible hole is the CORRECT outcome here,
not a failure of this script.

DOES THIS TRIGGER A METRICS RECALCULATION? Yes, automatically, with no extra
enqueue call needed: `ml_order_item_costos` carries Postgres
AFTER INSERT/AFTER DELETE row triggers
(`trg_order_metrics_item_costos_insert` / `_delete`,
`app/services/order_metrics/triggers.py`) that both call
`order_metrics_enqueue(...)` -- the DELETE below and the re-`congelar()`
INSERT each fire their own trigger, so `ml_order_metrics` gets recomputed
for every affected order without this script touching the queue table
itself.

SCOPE -- this script ONLY repairs rows written by the LIVE path
(`congelar()`'s own `FUENTE_PUBLICACION` / `FUENTE_SKU` / `FUENTE_COMBO`).
A row written by the BACKFILL path (`fuente` in `hist_publicacion`,
`hist_sku`, `hist_combo`) is EXCLUDED even when it matches the `<= 0`
criterion below: its `costo_origen` came from a DATED
`ItemCostListHistory` row, correct for the order's own date, and
re-`congelar()`-ing it would silently replace that correct historic value
with TODAY's `ProductoERP.costo`/exchange rate. A backfilled row with a
bad IVA needs a re-dated backfill run, never this script -- it is counted
under `examined_out_of_scope_backfill` and left completely untouched.

Likewise, a candidate row whose item is no longer on `MlOrderItemOps` (a
partial cancellation) is NEVER deleted, even though it matches the `<= 0`
criterion: the design says this snapshot deliberately OUTLIVES the item it
describes, and `congelar()` only has the items CURRENT on the order to
work from -- there is no way to ever recreate a deleted row like this one.
Preserving a zero is bad; losing the snapshot forever is worse and
irreversible. It is counted under `examined_out_of_scope_item_gone` and
left completely untouched, reported as a known, intocable case rather
than silently destroyed.

Run:
    python -m app.scripts.repair_costo_iva_cero_congelado --limit 5000            # reports only
    python -m app.scripts.repair_costo_iva_cero_congelado --limit 5000 --apply    # actually repairs
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv  # noqa: E402

env_path = backend_path / ".env"
load_dotenv(dotenv_path=env_path)

from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.ml_order_item_costo import MlOrderItemCosto  # noqa: E402
from app.models.ml_orders_ops import MlOrderItemOps  # noqa: E402
from app.services.ml_orders_ingestion.costeo_service import (  # noqa: E402
    FUENTE_COMBO,
    FUENTE_PUBLICACION,
    FUENTE_SKU,
    _productos_por_item,
    componentes_por_combo,
    congelar,
    tiene_costo_propio,
    tiene_iva_conocido,
)
from app.services.ml_orders_ingestion.mapper import OrderItemOpsDTO  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500

MOTIVO_COSTO_CERO = "costo_congelado_cero"
MOTIVO_IVA_CERO = "iva_congelado_cero"
MOTIVO_COSTO_Y_IVA_CERO = "costo_y_iva_congelados_cero"

# The ONLY `fuente` values this script is allowed to delete+re-`congelar()`
# -- exactly the constants `congelar()` itself stamps on the live path. A
# row with any other `fuente` (the `hist_*`/backfill family) is out of
# scope by construction -- see the module docstring.
FUENTES_EN_VIVO = frozenset({FUENTE_PUBLICACION, FUENTE_SKU, FUENTE_COMBO})

# Post-correction hole reasons, best-effort (a real second pass through
# `_resolve_cost` is private on purpose -- these are the same public
# predicates `congelar()` itself uses, read back to explain a hole this
# script observes rather than to duplicate its resolution logic).
HUECO_SIN_VINCULACION = "hueco_sin_vinculacion_erp"
HUECO_SIN_COSTO_NI_COMBO = "hueco_sin_costo_propio_ni_combo_costeable"
HUECO_IVA_DESCONOCIDO = "hueco_iva_desconocido"
HUECO_OTRO = "hueco_otro_ej_sin_tipo_de_cambio"


@dataclass
class RepairResult:
    examined: int = 0
    deleted: int = 0
    recongelados: int = 0
    huecos: int = 0
    # Candidates matching the `<= 0` criterion that this script deliberately
    # does NOT delete (defect 1, `hist_*` rows) or deletes but cannot
    # recreate (defect 3, item no longer on the order) -- see the module
    # docstring. Every candidate lands in EXACTLY one bucket, so:
    #   examined == recongelados + huecos + examined_out_of_scope_backfill
    #             + examined_out_of_scope_item_gone
    examined_out_of_scope_backfill: int = 0
    examined_out_of_scope_item_gone: int = 0
    motivos_borrado: Counter = field(default_factory=Counter)
    motivos_hueco: Counter = field(default_factory=Counter)


def _candidate_query(db: Session, limit: Optional[int]):
    """Every frozen row whose `costo_unitario_ars` or `iva_pct` is `<= 0` --
    the exact translation of `tiene_costo_propio`/`tiene_iva_conocido` onto
    the FROZEN columns, since this table has no `ProductoERP` reference to
    re-check directly. Includes out-of-scope (`hist_*`) rows too: they must
    still be EXAMINED and COUNTED, just never deleted -- see
    `examined_out_of_scope_backfill`."""
    query = (
        db.query(MlOrderItemCosto)
        .filter((MlOrderItemCosto.costo_unitario_ars <= 0) | (MlOrderItemCosto.iva_pct <= 0))
        .order_by(MlOrderItemCosto.order_id, MlOrderItemCosto.id)
    )
    if limit is not None:
        query = query.limit(limit)
    return query


def _motivo(row: MlOrderItemCosto) -> str:
    costo_cero = row.costo_unitario_ars is not None and row.costo_unitario_ars <= 0
    iva_cero = row.iva_pct is not None and row.iva_pct <= 0
    if costo_cero and iva_cero:
        return MOTIVO_COSTO_Y_IVA_CERO
    if costo_cero:
        return MOTIVO_COSTO_CERO
    return MOTIVO_IVA_CERO


def _item_dto_from_ops(row: MlOrderItemOps) -> OrderItemOpsDTO:
    return OrderItemOpsDTO(
        item_id=row.item_id,
        variation_id=row.variation_id,
        seller_sku=row.seller_sku,
        title=row.title,
        quantity=row.quantity,
        unit_price=row.unit_price,
        full_unit_price=row.full_unit_price,
        sale_fee=row.sale_fee,
        listing_type_id=row.listing_type_id,
    )


def _diagnose_hueco(
    db: Session,
    keys: Sequence[Tuple[int, str, Optional[int]]],
    items_by_key: Dict[Tuple[int, str, Optional[int]], MlOrderItemOps],
    result: RepairResult,
) -> None:
    """Best-effort explanation for every key that STILL has no frozen row
    after re-`congelar()` -- read-only diagnostics over the same public
    predicates `congelar()` itself relies on, never a second resolution
    path that could disagree with it."""
    ops_items = [items_by_key[key] for key in keys if key in items_by_key]
    dtos = [_item_dto_from_ops(row) for row in ops_items]
    productos_por_indice = _productos_por_item(db, dtos)

    erp_ids_sin_costo = {
        producto.item_id for producto, _ in productos_por_indice.values() if not tiene_costo_propio(producto)
    }
    combos = componentes_por_combo(db, erp_ids_sin_costo)

    for idx, dto in enumerate(dtos):
        result.huecos += 1
        resuelto = productos_por_indice.get(idx)
        if resuelto is None:
            result.motivos_hueco[HUECO_SIN_VINCULACION] += 1
            continue
        producto, _fuente = resuelto
        if not tiene_costo_propio(producto) and not combos.get(producto.item_id):
            result.motivos_hueco[HUECO_SIN_COSTO_NI_COMBO] += 1
            continue
        if not tiene_iva_conocido(producto):
            result.motivos_hueco[HUECO_IVA_DESCONOCIDO] += 1
            continue
        result.motivos_hueco[HUECO_OTRO] += 1


def run_repair(limit: Optional[int], dry_run: bool, batch_size: int = DEFAULT_BATCH_SIZE) -> RepairResult:
    result = RepairResult()
    db = SessionLocal()
    try:
        candidatos = _candidate_query(db, limit).all()
        result.examined = len(candidatos)
        if not candidatos:
            return result

        for row in candidatos:
            result.motivos_borrado[_motivo(row)] += 1

        # Defect 1: split out-of-scope (backfill) rows FIRST -- they are
        # counted but never deleted, never passed to `congelar()`.
        en_vivo = [row for row in candidatos if row.fuente in FUENTES_EN_VIVO]
        result.examined_out_of_scope_backfill = len(candidatos) - len(en_vivo)

        if dry_run:
            # Dry run reports ONLY what would be deleted -- the in-scope
            # (live-path) subset. It deliberately does NOT simulate the
            # re-`congelar()` outcome: that would mean duplicating
            # `_resolve_cost`'s private resolution logic just to predict its
            # answer without writing, which risks the exact "two paths that
            # can disagree" this whole module refuses elsewhere. Run with
            # `--apply` to see real recongelado/hueco counts.
            result.deleted = len(en_vivo)
            return result

        # Grouped by order so a single query per order finds which of ITS
        # candidate keys are still on the order and which are not (defect
        # 3), and so `congelar()` is called once per order but ONLY over
        # the keys THIS script actually deleted (defect 2) -- never the
        # order's whole item set.
        keys_by_order: Dict[int, List[Tuple[str, Optional[int]]]] = {}
        for row in en_vivo:
            keys_by_order.setdefault(row.order_id, []).append((row.item_id, row.variation_id))

        order_ids = sorted(keys_by_order)
        for start in range(0, len(order_ids), batch_size):
            batch_order_ids = order_ids[start : start + batch_size]

            all_keys: List[Tuple[int, str, Optional[int]]] = []
            for order_id in batch_order_ids:
                for item_id, variation_id in keys_by_order[order_id]:
                    all_keys.append((order_id, item_id, variation_id))

            ops_rows = db.query(MlOrderItemOps).filter(MlOrderItemOps.order_id.in_(batch_order_ids)).all()
            # Keyed by (order_id, item_id, variation_id) -- defect 4: a bare
            # (item_id, variation_id) key collides across orders sharing the
            # same MLA.
            items_by_key: Dict[Tuple[int, str, Optional[int]], MlOrderItemOps] = {
                (ops_row.order_id, ops_row.item_id, ops_row.variation_id): ops_row for ops_row in ops_rows
            }

            # Defect 3: a candidate key with no matching `MlOrderItemOps` row
            # means the item was removed from the order (a partial
            # cancellation) AFTER this frozen row was written. The design
            # says this snapshot deliberately OUTLIVES the item it
            # describes -- deleting it here would be an IRREVERSIBLE loss
            # with no way to ever re-`congelar()` it back, since `congelar()`
            # only has the items current on the order to work from. So this
            # row is NOT deleted at all: it is left exactly as it is,
            # counted and reported as untouchable, never silently destroyed.
            keys_to_recongelar: List[Tuple[int, str, Optional[int]]] = []
            keys_to_delete: List[Tuple[int, str, Optional[int]]] = []
            for key in all_keys:
                if key in items_by_key:
                    keys_to_recongelar.append(key)
                    keys_to_delete.append(key)
                else:
                    result.examined_out_of_scope_item_gone += 1

            deleted_count = 0
            for order_id, item_id, variation_id in keys_to_delete:
                deleted_count += (
                    db.query(MlOrderItemCosto)
                    .filter(
                        MlOrderItemCosto.order_id == order_id,
                        MlOrderItemCosto.item_id == item_id,
                        MlOrderItemCosto.variation_id.is_(variation_id)
                        if variation_id is None
                        else MlOrderItemCosto.variation_id == variation_id,
                        MlOrderItemCosto.fuente.in_(FUENTES_EN_VIVO),
                        # Belt and braces: the same "not a real cost" condition
                        # the SELECT above used, repeated HERE so the DELETE's
                        # own WHERE carries the safety property instead of
                        # trusting the key list it was handed. A row that does
                        # not match it cannot be destroyed by this statement
                        # even if the list were ever built wrong.
                        (MlOrderItemCosto.costo_unitario_ars <= 0) | (MlOrderItemCosto.iva_pct <= 0),
                    )
                    .delete(synchronize_session=False)
                )
            result.deleted += deleted_count

            # NO `db.commit()` HERE, deliberately. The DELETE and the
            # re-`congelar()` below are ONE transaction per batch: committing
            # the deletion first would mean that a crash, a lost connection or
            # any exception raised while re-freezing leaves rows deleted with
            # nothing to recreate them -- `congelar()` reads the CURRENT items,
            # so a second run would re-freeze them, but the operator would
            # never know a window existed where those sales had no cost at
            # all. Deleting a wrong value is recoverable; deleting it and
            # failing to write the right one is the exact data loss this
            # script exists to avoid.
            #
            # Group the keys to re-freeze back by order, and pass `congelar()`
            # ONLY those items' DTOs -- never the order's whole item set, so
            # an untouched hole on the same order can never get a fresh row
            # stamped by this script (defect 2).
            recongelar_keys_by_order: Dict[int, List[Tuple[str, Optional[int]]]] = {}
            for order_id, item_id, variation_id in keys_to_recongelar:
                recongelar_keys_by_order.setdefault(order_id, []).append((item_id, variation_id))

            for order_id, keys in recongelar_keys_by_order.items():
                dtos = [
                    _item_dto_from_ops(items_by_key[(order_id, item_id, variation_id)])
                    for item_id, variation_id in keys
                ]
                congelar(db, order_id=order_id, items=dtos)
            db.commit()

            # Which of the just-recongelado-attempted keys got a fresh row,
            # and which are now a visible hole. Only keys actually passed to
            # `congelar()` are considered -- the "item gone" keys were never
            # a candidate for recongelado in the first place.
            fresh_rows = (
                db.query(MlOrderItemCosto.order_id, MlOrderItemCosto.item_id, MlOrderItemCosto.variation_id)
                .filter(MlOrderItemCosto.order_id.in_(batch_order_ids))
                .all()
            )
            fresh_keys = {(r.order_id, r.item_id, r.variation_id) for r in fresh_rows}

            huecos: List[Tuple[int, str, Optional[int]]] = []
            for key in keys_to_recongelar:
                if key in fresh_keys:
                    result.recongelados += 1
                else:
                    huecos.append(key)

            if huecos:
                _diagnose_hueco(db, huecos, items_by_key, result)

        return result
    finally:
        db.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete frozen ml_order_item_costos rows whose cost or IVA was "
        "frozen as zero (an ERP hole, never a real value) and re-freeze those items "
        "with the current combo-aware, zero-guarded costeo_service logic."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after examining this many candidate rows. WITHOUT it the run covers every candidate.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Orders processed per commit batch (default {DEFAULT_BATCH_SIZE}).",
    )
    # Unlike its sibling `backfill_costo_congelado.py`, which only INSERTS,
    # this script DELETES. Its worst case is rows that are gone, not rows
    # that are extra, so the safe mode is the DEFAULT here and destruction
    # is what needs to be asked for explicitly.
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete and re-freeze. WITHOUT it the run only reports what WOULD change.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)

    result = run_repair(limit=args.limit, dry_run=not args.apply, batch_size=args.batch_size)

    logger.info(
        "repair_costo_iva_cero_congelado: complete (dry_run=%s, limit=%s) -- "
        "examined=%s deleted=%s recongelados=%s huecos=%s "
        "out_of_scope_backfill=%s out_of_scope_item_gone=%s "
        "motivos_borrado=%s motivos_hueco=%s",
        not args.apply,
        args.limit,
        result.examined,
        result.deleted,
        result.recongelados,
        result.huecos,
        result.examined_out_of_scope_backfill,
        result.examined_out_of_scope_item_gone,
        dict(result.motivos_borrado),
        dict(result.motivos_hueco),
    )


if __name__ == "__main__":
    main()
