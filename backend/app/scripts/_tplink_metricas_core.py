"""
Shared per-order aggregation core for TP-Link sales metrics (store 2645, coslis_id=8).

Design v2 (design token: sdd/tplink-metricas-dual-key-dedup/design, decision D1):
Both the backfill job and the incremental job import this module so that the
key contract (`id_operacion=mlo_id`, `ml_order_id=str(ml_id)`, `mla_id=str(mlp_id)`)
and the aggregation logic can never drift between the two jobs.

Two responsibilities live here:

1. `build_aggregation_sql()` — the per-detail projection CTE. Unlike the older
   `DISTINCT ON (tmlod.mlo_id)` query, this returns ALL detail rows per order
   (no collapsing in SQL) so the Python fold below can SUM across an order's
   details. Date window uses half-open bounds on `tmloh.mlo_cd`
   (`>= :from_ts AND < :to_ts`) — see design D3.

2. `fold_order_rows()` — the Python SUM-fold. Groups per-detail rows by
   `mlo_id`, runs `calcular_metricas_ml` PER DETAIL with order shipping
   EXCLUDED, sums the per-detail metrics, and applies the order's shipping
   cost EXACTLY ONCE (subtracted once from the summed ganancia/monto_limpio).
   This avoids the double-subtraction hazard called out in design D1.

`count_per_pack()` counts DISTINCT ORDERS per pack (post-fold semantics),
not raw detail rows — a multi-detail order must not inflate the pack-offset
count.

Slice 2 of 3 (SDD change tplink-metricas-dual-key-dedup) adds two more
shared responsibilities so both jobs' insert/update mapping can never drift:

3. `build_upsert_payload()` — maps a folded per-order dict (from
   `fold_order_rows()`) to the exact `TplinkVentaMetrica` column payload
   (types, rounding, `fecha_calculo`).

4. `upsert_metrica()` — queries by `id_operacion` (mlo_id) and either
   updates the existing row or inserts a new one. Callers own commit /
   rollback / batching cadence.

Both TP-Link job scripts (`agregar_metricas_tplink.py`,
`agregar_metricas_tplink_incremental.py`) are thin wrappers around this
module: they only own the date-window computation and the DB session /
commit cadence.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause

from app.utils.ml_metrics_calculator import calcular_metricas_ml

# Module-level constants — kept identical to the existing jobs.
TPLINK_STORE_ID: int = 2645
# Exported for slice-2 callers (job wiring) to bind as `:coslis_id` in
# build_aggregation_sql()'s params — not dead code, just not consumed
# within this module itself.
TPLINK_COSLIS_ID: int = 8

# Standard Argentine VAT multiplier, used to strip IVA from the order-level
# shipping cost (`seller_shipping_cost` comes from ML with IVA included).
# Mirrors the same assumption already baked into calcular_metricas_ml's own
# shipping branch (ml_metrics_calculator.py) — kept as one named constant
# here so both call sites can be audited together if the rate ever changes.
DEFAULT_IVA_MULTIPLIER: float = 1.21


def build_aggregation_sql() -> TextClause:
    """
    Builds the shared per-detail aggregating CTE (SQLAlchemy `text()` clause).

    Bind parameters: `:from_ts`, `:to_ts`, `:coslis_id`, `:store_id`.

    Differences from the legacy per-job queries:
      - `DISTINCT ON (tmlod.mlo_id)` REMOVED: returns ALL details per order so
        the Python fold can SUM them (design D1).
      - Inner `ORDER BY tmlod.mlo_id, tmlod.mlod_id` added for a deterministic
        representative-detail pick (descriptive fields, mla_id).
      - Date window uses half-open bounds on `tmloh.mlo_cd`
        (`>= :from_ts AND < :to_ts`), not `BETWEEN` (design D3).
    """
    return text("""
    WITH sales_data AS (
        SELECT
            tmlod.mlo_id as id_operacion,
            tmlod.item_id,
            tmloh.mlo_cd as fecha_venta,
            COALESCE(tb.brand_desc, pe.marca) as marca,
            COALESCE(tc.cat_desc, pe.categoria) as categoria,
            COALESCE(tsc.subcat_desc, (SELECT s.subcat_desc FROM tb_subcategory s WHERE s.subcat_id = pe.subcategoria_id LIMIT 1)) as subcategoria,
            COALESCE(ti.item_code, pe.codigo) as codigo,
            COALESCE(UPPER(ti.item_desc), UPPER(pe.descripcion)) as descripcion,
            tmlod.mlo_quantity as cantidad,
            tmlod.mlo_unit_price as monto_unitario,
            tmlod.mlo_unit_price * tmlod.mlo_quantity as monto_total,

            COALESCE(
                (
                    SELECT CASE
                        WHEN iclh.curr_id = 2 THEN
                            iclh.iclh_price * COALESCE(
                                (SELECT tc.venta FROM tipo_cambio tc WHERE tc.moneda = 'USD' AND tc.fecha <= tmloh.mlo_cd::date ORDER BY tc.fecha DESC LIMIT 1),
                                (SELECT ceh.ceh_exchange FROM tb_cur_exch_history ceh WHERE ceh.ceh_cd <= tmloh.mlo_cd ORDER BY ceh.ceh_cd DESC LIMIT 1)
                            )
                        ELSE
                            iclh.iclh_price
                    END
                    FROM tb_item_cost_list_history iclh
                    WHERE iclh.item_id = tmlod.item_id
                      AND iclh.iclh_cd <= tmloh.mlo_cd
                      AND iclh.coslis_id = :coslis_id
                      AND iclh.iclh_price > 0
                    ORDER BY iclh.iclh_id DESC
                    LIMIT 1
                ),
                (
                    SELECT CASE
                        WHEN ticl.curr_id = 2 THEN
                            ticl.coslis_price * COALESCE(
                                (SELECT tc.venta FROM tipo_cambio tc WHERE tc.moneda = 'USD' AND tc.fecha <= tmloh.mlo_cd::date ORDER BY tc.fecha DESC LIMIT 1),
                                (SELECT ceh.ceh_exchange FROM tb_cur_exch_history ceh WHERE ceh.ceh_cd <= tmloh.mlo_cd ORDER BY ceh.ceh_cd DESC LIMIT 1)
                            )
                        ELSE
                            ticl.coslis_price
                    END
                    FROM tb_item_cost_list ticl
                    WHERE ticl.item_id = tmlod.item_id
                      AND ticl.coslis_id = :coslis_id
                ),
                0
            ) as costo_sin_iva,

            pe.iva as iva,

            COALESCE(tmlos.ml_logistic_type, tmlos.mllogistic_type) as tipo_logistica,
            tmloh.ml_id,
            tmloh.ml_pack_id as pack_id,
            pe.envio as envio_producto,
            COALESCE(tmlos.mlshippmentcost4seller, 0) as seller_shipping_cost,

            COALESCE(
                (SELECT SUM(od2.mlo_unit_price * od2.mlo_quantity)
                 FROM tb_mercadolibre_orders_detail od2
                 JOIN tb_mercadolibre_orders_header oh2 ON oh2.mlo_id = od2.mlo_id
                 WHERE oh2.mlshippingid = tmloh.mlshippingid
                ), tmlod.mlo_unit_price * tmlod.mlo_quantity
            ) as shipment_total,

            COALESCE(
                (
                    SELECT
                        cb.comision_base + COALESCE(
                            (
                                SELECT cac.adicional
                                FROM comisiones_adicionales_cuota cac
                                WHERE cac.version_id = cv.id
                                  AND cac.cuotas = CASE
                                      WHEN COALESCE(tmloh.prli_id, tsoh.prli_id, CASE WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop ELSE tmlip.prli_id END) IN (17, 18) THEN 3
                                      WHEN COALESCE(tmloh.prli_id, tsoh.prli_id, CASE WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop ELSE tmlip.prli_id END) IN (14, 19) THEN 6
                                      WHEN COALESCE(tmloh.prli_id, tsoh.prli_id, CASE WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop ELSE tmlip.prli_id END) IN (13, 20) THEN 9
                                      WHEN COALESCE(tmloh.prli_id, tsoh.prli_id, CASE WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop ELSE tmlip.prli_id END) IN (23, 21) THEN 12
                                      ELSE NULL
                                  END
                                LIMIT 1
                            ),
                            0
                        )
                    FROM subcategorias_grupos sg
                    JOIN comisiones_base cb ON cb.grupo_id = sg.grupo_id
                    JOIN comisiones_versiones cv ON cv.id = cb.version_id
                    WHERE sg.subcat_id = COALESCE(tsc.subcat_id, pe.subcategoria_id)
                      AND tmloh.mlo_cd::date BETWEEN cv.fecha_desde AND COALESCE(cv.fecha_hasta, '9999-12-31'::date)
                      AND cv.activo = TRUE
                    LIMIT 1
                ),
                12.0
            ) as comision_base_porcentaje,

            COALESCE(tsc.subcat_id, pe.subcategoria_id) as subcat_id,

            COALESCE(
                tsoh.prli_id,
                CASE
                    WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop
                    ELSE tmlip.prli_id
                END
            ) as pricelist_id,

            tmlod.mlp_id as mlp_id,
            tmlip.mlp_official_store_id as mlp_official_store_id,
            tmlod.mlod_id as mlod_id

        FROM tb_mercadolibre_orders_detail tmlod

        LEFT JOIN tb_mercadolibre_orders_header tmloh
            ON tmloh.comp_id = tmlod.comp_id
            AND tmloh.mlo_id = tmlod.mlo_id

        LEFT JOIN tb_sale_order_header tsoh
            ON tsoh.comp_id = tmlod.comp_id
            AND tsoh.mlo_id = tmlod.mlo_id

        LEFT JOIN tb_item ti
            ON ti.comp_id = tmlod.comp_id
            AND ti.item_id = tmlod.item_id

        LEFT JOIN productos_erp pe
            ON pe.item_id = tmlod.item_id

        LEFT JOIN tb_mercadolibre_items_publicados tmlip
            ON tmlip.comp_id = tmlod.comp_id
            AND tmlip.mlp_id = tmlod.mlp_id

        LEFT JOIN tb_mercadolibre_orders_shipping tmlos
            ON tmlos.comp_id = tmlod.comp_id
            AND tmlos.mlo_id = tmlod.mlo_id

        LEFT JOIN tb_category tc
            ON tc.comp_id = tmlod.comp_id
            AND tc.cat_id = ti.cat_id

        LEFT JOIN tb_subcategory tsc
            ON tsc.comp_id = tmlod.comp_id
            AND tsc.cat_id = ti.cat_id
            AND tsc.subcat_id = ti.subcat_id

        LEFT JOIN tb_brand tb
            ON tb.comp_id = tmlod.comp_id
            AND tb.brand_id = ti.brand_id

        LEFT JOIN tb_item_cost_list ticl
            ON ticl.comp_id = tmlod.comp_id
            AND ticl.item_id = tmlod.item_id
            AND ticl.coslis_id = :coslis_id

        WHERE tmlod.item_id NOT IN (460, 3042)
          AND tmloh.mlo_cd >= :from_ts
          AND tmloh.mlo_cd < :to_ts
          AND tmloh.mlo_status <> 'cancelled'
          AND tmlip.mlp_official_store_id = :store_id
    )
    SELECT * FROM sales_data
    ORDER BY id_operacion, mlod_id
    """)


def count_per_pack(rows: Iterable[Any]) -> dict[Any, int]:
    """
    Counts DISTINCT ORDERS per `pack_id`, not raw detail rows.

    A multi-detail order sharing a `pack_id` must count as ONE order in the
    pack-offset calculation, not once per detail line (design D1 hazard).
    """
    orders_by_pack: dict[Any, set[Any]] = defaultdict(set)
    for row in rows:
        pack_id = getattr(row, "pack_id", None)
        if pack_id:
            orders_by_pack[pack_id].add(row.id_operacion)

    return {pack_id: len(order_ids) for pack_id, order_ids in orders_by_pack.items()}


def _calcular_metricas_detalle_sin_envio(
    row: Any, count_per_pack_value: int, db_session: Any = None
) -> dict[str, float]:
    """
    Runs `calcular_metricas_ml` for a SINGLE detail row with order shipping
    EXCLUDED (`seller_shipping_cost=None`, `shipment_total=None`). Shipping is
    applied once per order by the caller (`fold_order_rows`), never per detail.
    """
    comision_porcentaje = None
    if db_session and row.subcat_id and row.pricelist_id:
        from app.services.pricing_calculator import obtener_comision_versionada, obtener_grupo_subcategoria

        grupo_id = obtener_grupo_subcategoria(db_session, row.subcat_id)
        if grupo_id:
            fecha_venta = row.fecha_venta.date() if hasattr(row.fecha_venta, "date") else row.fecha_venta
            comision_porcentaje = obtener_comision_versionada(db_session, grupo_id, row.pricelist_id, fecha_venta)

    if comision_porcentaje is None:
        comision_porcentaje = float(row.comision_base_porcentaje or 12.0)

    costo_envio_producto = float(row.envio_producto) if getattr(row, "envio_producto", None) else None

    return calcular_metricas_ml(
        monto_unitario=float(row.monto_unitario or 0),
        cantidad=float(row.cantidad or 1),
        iva_porcentaje=float(row.iva or 0),
        costo_unitario_sin_iva=float(row.costo_sin_iva or 0),
        costo_envio_ml=costo_envio_producto,
        count_per_pack=count_per_pack_value,
        subcat_id=row.subcat_id,
        pricelist_id=row.pricelist_id,
        fecha_venta=row.fecha_venta,
        comision_base_porcentaje=comision_porcentaje,
        db_session=db_session,
        ml_logistic_type=row.tipo_logistica,
        # Shipping EXCLUDED here on purpose — applied once per order below.
        seller_shipping_cost=None,
        shipment_total=None,
    )


def _pick_representative_detail(details: list[Any]) -> Any:
    """
    Deterministically picks the representative detail for an order's
    descriptive fields (`mla_id`, `codigo`, `descripcion`, etc.) by MINIMUM
    `mlod_id` — never by unenforced caller/list ordering (R3-006). The SQL
    query already orders rows by `(id_operacion, mlod_id)`, but this fold
    function must not silently depend on that contract holding for every
    caller (e.g. a future caller re-ordering rows before folding).
    """
    with_mlod_id = [d for d in details if getattr(d, "mlod_id", None) is not None]
    if with_mlod_id:
        return min(with_mlod_id, key=lambda d: d.mlod_id)
    return details[0]


def _costo_envio_once_per_order(details: list[Any], order_monto_total: float) -> float:
    """
    Computes the order's shipping cost (sin IVA) EXACTLY ONCE, PRORATED to
    this order's share of the shipment (R3-001 fix).

    `shipment_total` is a per-order-correlated field whose underlying SQL
    subquery sums `monto_unitario * cantidad` over ALL details sharing the
    same `mlshippingid` — which can span MULTIPLE orders (e.g. an ML "pack"
    shipped together), not just multiple details of a single order. Charging
    the full `seller_shipping_cost` to every order sharing that shipment
    overcounts shipping system-wide. Instead, prorate:

        order_shipping = shipment_shipping_sin_iva * (order_monto / shipment_monto)

    This mirrors `calcular_metricas_ml`'s own per-item proration formula
    (`ml_metrics_calculator.py`), but evaluated ONCE per order using the
    order's OWN total monto (summed across its own details) as the numerator,
    instead of once per detail.
    """
    representative = _pick_representative_detail(details)
    seller_shipping_cost = getattr(representative, "seller_shipping_cost", None)
    shipment_total = getattr(representative, "shipment_total", None)

    if not seller_shipping_cost or float(seller_shipping_cost) <= 0:
        return 0.0

    shipment_shipping_sin_iva = float(seller_shipping_cost) / DEFAULT_IVA_MULTIPLIER

    monto_pack = float(shipment_total) if shipment_total and float(shipment_total) > 0 else order_monto_total
    if monto_pack <= 0:
        return 0.0

    proporcion = order_monto_total / monto_pack
    return shipment_shipping_sin_iva * proporcion


def fold_order_rows(rows: Iterable[Any], db_session: Any = None) -> dict[Any, dict[str, Any]]:
    """
    Groups per-detail rows by `id_operacion` (mlo_id) and folds each group
    into ONE row with SUMMED monto_total, cantidad, costo, comision, ganancia,
    with the order's shipping cost and offset_flex applied EXACTLY ONCE
    (design D1).

    Returns a dict keyed by `id_operacion` (mlo_id) -> folded dict with keys:
      id_operacion, ml_order_id, mla_id, pack_id, item_id, codigo, descripcion,
      marca, categoria, subcategoria, fecha_venta, cantidad, monto_unitario,
      monto_total, costo_unitario_sin_iva, costo_total_sin_iva, comision_ml,
      costo_envio_ml, tipo_logistica, monto_limpio, ganancia,
      markup_porcentaje, offset_flex, mlp_official_store_id.

    `rows` is materialized into a list IMMEDIATELY (R2-001): it is iterated
    more than once internally (grouping, then `count_per_pack`), so a
    one-shot generator/cursor passed by the caller must not be silently
    exhausted before the second pass.

    Determinism: summation is order-independent (no DISTINCT-ON arbitrary
    pick); the representative detail for descriptive fields is picked by
    minimum `mlod_id` (`_pick_representative_detail`), not by caller
    iteration order (R3-006).
    """
    rows = list(rows)

    grouped: dict[Any, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[row.id_operacion].append(row)

    pack_counts = count_per_pack(rows)

    folded: dict[Any, dict[str, Any]] = {}

    for order_id, details in grouped.items():
        first = _pick_representative_detail(details)
        pack_id = getattr(first, "pack_id", None)
        count_per_pack_value = pack_counts.get(pack_id, 1) if pack_id else 1

        sum_cantidad = 0.0
        sum_monto_total = 0.0
        sum_costo_total_sin_iva = 0.0
        sum_comision_ml = 0.0
        sum_monto_limpio_sin_envio = 0.0
        # offset_flex is a FIXED per-shipment amount (ml_metrics_calculator.py),
        # not a per-detail one — applied ONCE per order (R3-002 fix), taking
        # the first qualifying detail's value rather than summing across all
        # qualifying details.
        offset_flex_once = 0.0

        for detail in details:
            metricas = _calcular_metricas_detalle_sin_envio(detail, count_per_pack_value, db_session)
            sum_cantidad += float(detail.cantidad or 0)
            sum_monto_total += float(detail.monto_total or 0)
            sum_costo_total_sin_iva += metricas["costo_total_sin_iva"]
            sum_comision_ml += metricas["comision_ml"]
            sum_monto_limpio_sin_envio += metricas["monto_limpio"]
            if offset_flex_once == 0.0 and metricas["offset_flex"]:
                offset_flex_once = metricas["offset_flex"]

        costo_envio_ml = _costo_envio_once_per_order(details, sum_monto_total)

        # Shipping subtracted ONCE from the summed monto_limpio/ganancia.
        monto_limpio = sum_monto_limpio_sin_envio - costo_envio_ml
        ganancia = monto_limpio - sum_costo_total_sin_iva

        markup_porcentaje = 0.0
        if sum_costo_total_sin_iva > 0:
            markup_porcentaje = ((monto_limpio / sum_costo_total_sin_iva) - 1) * 100
            markup_porcentaje = max(min(markup_porcentaje, 99999999.99), -99999999.99)

        folded[order_id] = {
            "id_operacion": order_id,
            "ml_order_id": str(first.ml_id) if first.ml_id else None,
            # mla_id intentionally unifies on mlp_id (the INTERNAL publication
            # PK), matching the incremental job's contract (design D1) and
            # DIVERGING on purpose from the old backfill's external
            # mlp_publicationID — a reviewed decision, not an oversight (R2-002).
            "mla_id": str(first.mlp_id) if getattr(first, "mlp_id", None) else None,
            "pack_id": pack_id,
            "item_id": first.item_id,
            "codigo": first.codigo,
            "descripcion": first.descripcion,
            "marca": first.marca,
            "categoria": first.categoria,
            "subcategoria": first.subcategoria,
            "fecha_venta": first.fecha_venta,
            "cantidad": sum_cantidad,
            "monto_unitario": first.monto_unitario,
            "monto_total": sum_monto_total,
            "costo_unitario_sin_iva": first.costo_sin_iva,
            "costo_total_sin_iva": sum_costo_total_sin_iva,
            "comision_ml": sum_comision_ml,
            "costo_envio_ml": costo_envio_ml,
            "tipo_logistica": first.tipo_logistica,
            "monto_limpio": monto_limpio,
            "ganancia": ganancia,
            "markup_porcentaje": markup_porcentaje,
            "offset_flex": offset_flex_once,
            "mlp_official_store_id": TPLINK_STORE_ID,
        }

    return folded


def _dec(value: Any, digits: int = 2) -> Decimal:
    """Rounds `value` to `digits` decimals and returns a `Decimal`, defaulting
    to `Decimal("0")` for `None`/falsy-zero inputs (matches the legacy jobs'
    `Decimal(str(round(x, n)))` pattern)."""
    if value is None:
        return Decimal("0")
    return Decimal(str(round(float(value), digits)))


def build_upsert_payload(folded: dict[str, Any]) -> dict[str, Any]:
    """
    Maps ONE folded per-order dict (as returned by `fold_order_rows()`) to
    the exact `TplinkVentaMetrica` column payload — shared by both jobs so
    field mapping/rounding/types can never drift between backfill and
    incremental (design D1/D4: "cross-job upsert dedupes naturally").
    """
    return {
        "id_operacion": folded["id_operacion"],
        "ml_order_id": folded["ml_order_id"],
        "pack_id": folded["pack_id"],
        "item_id": folded["item_id"],
        "codigo": folded["codigo"],
        "descripcion": folded["descripcion"],
        "marca": folded["marca"],
        "categoria": folded["categoria"],
        "subcategoria": folded["subcategoria"],
        "fecha_venta": folded["fecha_venta"],
        "fecha_calculo": date.today(),
        "cantidad": int(folded["cantidad"]) if folded["cantidad"] is not None else 0,
        "monto_unitario": _dec(folded["monto_unitario"]),
        "monto_total": _dec(folded["monto_total"]),
        "costo_unitario_sin_iva": _dec(folded["costo_unitario_sin_iva"], digits=6),
        "costo_total_sin_iva": _dec(folded["costo_total_sin_iva"]),
        "comision_ml": _dec(folded["comision_ml"]),
        "costo_envio_ml": _dec(folded["costo_envio_ml"]),
        "tipo_logistica": folded["tipo_logistica"],
        "monto_limpio": _dec(folded["monto_limpio"]),
        "ganancia": _dec(folded["ganancia"]),
        "markup_porcentaje": _dec(folded["markup_porcentaje"]),
        "mla_id": folded["mla_id"],
        "mlp_official_store_id": folded["mlp_official_store_id"],
        "offset_flex": _dec(folded["offset_flex"]),
    }


def upsert_metrica(db_session: Any, payload: dict[str, Any]) -> str:
    """
    Upserts ONE `TplinkVentaMetrica` row keyed by `id_operacion` (mlo_id).

    Shared by both jobs so insert/update field-assignment logic can never
    drift. The caller owns `commit()`/`rollback()`/batching cadence — this
    function only queries, mutates, or constructs the ORM object; it never
    commits.

    Returns "actualizado" if an existing row was updated, "insertado" if a
    new row was added.
    """
    from app.models.tplink_venta_metrica import TplinkVentaMetrica

    existente = (
        db_session.query(TplinkVentaMetrica).filter(TplinkVentaMetrica.id_operacion == payload["id_operacion"]).first()
    )
    if existente:
        for key, value in payload.items():
            if key != "id_operacion":
                setattr(existente, key, value)
        return "actualizado"

    db_session.add(TplinkVentaMetrica(**payload))
    return "insertado"
