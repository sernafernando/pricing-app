"""
Script for adding TP-Link sales metrics (store 2645, coslis_id=8).
Clone of agregar_metricas_ml.py with four targeted changes:
  1. Write target: TplinkVentaMetrica instead of MLVentaMetrica.
  2. Cost lookup uses coslis_id=8 (TPLINK_COSLIS_ID) at BOTH sites.
  3. Per-detail store guard: skip details where mlp_official_store_id != 2645.
  4. Populate mlp_official_store_id=2645 in BOTH insert and update blocks (GAP fix).

ML model/jobs are byte-for-byte unmodified.

Backfill invocation:
    python app/scripts/agregar_metricas_tplink.py --from-date 2026-01-01 --to-date <today>
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import asyncio
import argparse
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.tplink_venta_metrica import TplinkVentaMetrica
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.mercadolibre_order_detail import MercadoLibreOrderDetail
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.item_cost_list import ItemCostList
from app.models.producto import ProductoERP
from app.models.tipo_cambio import TipoCambio
from app.services.pricing_calculator import (
    obtener_constantes_pricing,
    obtener_grupo_subcategoria,
    obtener_comision_versionada,
    calcular_comision_ml_total,
)

# Module-level constants
TPLINK_STORE_ID: int = 2645
TPLINK_COSLIS_ID: int = 8

# Missing-cost tracking (module-level so tests can inspect state)
_missing_cost_count: int = 0
_missing_cost_sample: list = []
_MISSING_COST_SAMPLE_CAP = 20


async def obtener_cotizacion_fecha(db: Session, fecha: date) -> float:
    """Obtains the USD exchange rate for a specific date."""
    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD", TipoCambio.fecha == fecha).first()

    if tc:
        return float(tc.venta)

    tc = (
        db.query(TipoCambio)
        .filter(TipoCambio.moneda == "USD", TipoCambio.fecha <= fecha)
        .order_by(TipoCambio.fecha.desc())
        .first()
    )

    return float(tc.venta) if tc else 1000.0


def obtener_costo_item(
    db: Session, item_id: int, fecha_venta: datetime, cantidad: float, mlo_id: int
) -> tuple[float, str]:
    """
    Obtains item cost from ERP cost list 8 (TPLINK_COSLIS_ID).

    Priority:
    1. Cost history (item_cost_list_history, coslis_id=8) before or on sale date.
    2. Current cost from history (coslis_id=8, no date filter).
    3. Current cost list (tb_item_cost_list, coslis_id=8) — where list 8 actually
       lives until history accumulates.
    4. Product cost fallback (productos_erp.costo).

    NEVER falls back to coslis_id=1. Missing-cost counter incremented when
    no list-8 cost is found and costo=0 is returned.

    Returns:
        (costo_total_sin_iva, moneda)
    """
    global _missing_cost_count, _missing_cost_sample

    # 1. Cost history before or on sale date (coslis_id=8)
    cost_history = (
        db.query(ItemCostListHistory)
        .filter(
            and_(
                ItemCostListHistory.item_id == item_id,
                ItemCostListHistory.coslis_id == TPLINK_COSLIS_ID,
                ItemCostListHistory.iclh_cd <= fecha_venta,
            )
        )
        .order_by(desc(ItemCostListHistory.iclh_cd))
        .first()
    )

    if cost_history and cost_history.iclh_price and float(cost_history.iclh_price) > 0:
        costo_unitario = float(cost_history.iclh_price)
        costo_total = costo_unitario * cantidad
        moneda = "USD" if cost_history.curr_id == 2 else "ARS"
        return (costo_total, moneda)

    # 2. Fallback: current most-recent cost from history (coslis_id=8)
    cost_actual = (
        db.query(ItemCostListHistory)
        .filter(and_(ItemCostListHistory.item_id == item_id, ItemCostListHistory.coslis_id == TPLINK_COSLIS_ID))
        .order_by(desc(ItemCostListHistory.iclh_cd))
        .first()
    )

    if cost_actual and cost_actual.iclh_price and float(cost_actual.iclh_price) > 0:
        costo_unitario = float(cost_actual.iclh_price)
        costo_total = costo_unitario * cantidad
        moneda = "USD" if cost_actual.curr_id == 2 else "ARS"
        return (costo_total, moneda)

    # 3. Current cost list (tb_item_cost_list, coslis_id=8). List 8 lives in the
    #    CURRENT cost table, not (yet) in the history table — the history-only
    #    lookups above miss it. The live operaciones detail also reads both. Money
    #    is detected by curr_id (2=USD), the caller converts USD→ARS.
    cost_current = (
        db.query(ItemCostList)
        .filter(and_(ItemCostList.item_id == item_id, ItemCostList.coslis_id == TPLINK_COSLIS_ID))
        .first()
    )

    if cost_current and cost_current.coslis_price and float(cost_current.coslis_price) > 0:
        costo_unitario = float(cost_current.coslis_price)
        costo_total = costo_unitario * cantidad
        moneda = "USD" if cost_current.curr_id == 2 else "ARS"
        return (costo_total, moneda)

    # 4. Last fallback: product cost (productos_erp.costo)
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()

    if producto and producto.costo and float(producto.costo) > 0:
        costo_unitario = float(producto.costo)
        costo_total = costo_unitario * cantidad
        moneda = "USD" if producto.moneda_costo and producto.moneda_costo.value == "USD" else "ARS"
        return (costo_total, moneda)

    # No list-8 cost found — log and return 0
    _missing_cost_count += 1
    if len(_missing_cost_sample) < _MISSING_COST_SAMPLE_CAP:
        _missing_cost_sample.append(item_id)

    return (0.0, "ARS")


async def agregar_metricas_venta(
    db: Session,
    order_header: MercadoLibreOrderHeader,
    order_detail: MercadoLibreOrderDetail,
    constantes: dict,
    pack_item_counts: dict = None,
    order_item_counts: dict = None,
):
    """Processes a single TP-Link sale and calculates all metrics."""
    try:
        # Obtain ML publication to check store guard
        publicacion_ml = None
        if order_detail.mlp_id:
            publicacion_ml = (
                db.query(MercadoLibreItemPublicado)
                .filter(MercadoLibreItemPublicado.mlp_id == order_detail.mlp_id)
                .first()
            )

        # Store guard: skip non-2645 details
        if not publicacion_ml or publicacion_ml.mlp_official_store_id != TPLINK_STORE_ID:
            return "skipped"

        # Check if already exists
        existente = db.query(TplinkVentaMetrica).filter(TplinkVentaMetrica.id_operacion == order_detail.mlod_id).first()

        # Obtain shipping information
        shipping = (
            db.query(MercadoLibreOrderShipping).filter(MercadoLibreOrderShipping.mlo_id == order_header.mlo_id).first()
        )

        # Obtain product information
        producto = None
        if order_detail.item_id:
            producto = db.query(ProductoERP).filter(ProductoERP.item_id == order_detail.item_id).first()

        # Calculate metrics
        fecha_venta = order_header.ml_date_created if order_header.ml_date_created else datetime.now()
        cotizacion = await obtener_cotizacion_fecha(db, fecha_venta.date())

        cantidad = float(order_detail.mlo_quantity) if order_detail.mlo_quantity else 1.0
        monto_unitario = float(order_detail.mlo_unit_price) if order_detail.mlo_unit_price else 0.0
        monto_total = monto_unitario * cantidad

        # Obtain cost from list 8 (coslis_id=8)
        costo_sin_iva_total, moneda_costo = obtener_costo_item(
            db, order_detail.item_id, fecha_venta, cantidad, order_header.mlo_id
        )

        # Convert cost to ARS if in USD
        moneda_costo_original = moneda_costo
        if moneda_costo == "USD":
            costo_sin_iva_total_ars = costo_sin_iva_total * cotizacion
            moneda_costo = "ARS"
        else:
            costo_sin_iva_total_ars = costo_sin_iva_total

        # Group and commission
        grupo_id = 1
        if producto and producto.subcategoria_id:
            grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)

        prli_id = publicacion_ml.prli_id if publicacion_ml else 4
        tipo_lista = (
            publicacion_ml.mlp_listing_type_id if publicacion_ml and publicacion_ml.mlp_listing_type_id else "unknown"
        )

        comision_pct = obtener_comision_versionada(db, grupo_id, prli_id, fecha_venta.date()) or 15.0

        comision_ml_detalle = calcular_comision_ml_total(
            precio=monto_total, comision_base_pct=comision_pct, iva=21.0, constantes=constantes, db=db
        )

        comision_ml = comision_ml_detalle["comision_total"]

        MONTOT3 = constantes.get("monto_tier3", 33000)

        costo_envio_ml = 0.0
        if monto_total < MONTOT3 and publicacion_ml and publicacion_ml.mlp_price4FreeShipping:
            costo_envio_ml = float(publicacion_ml.mlp_price4FreeShipping)
        elif shipping and shipping.mlshippmentcost4seller:
            costo_envio_ml = float(shipping.mlshippmentcost4seller)

        tipo_logistica = shipping.mllogistic_type if shipping and shipping.mllogistic_type else "unknown"

        items_en_shipping = 1

        if order_header.ml_pack_id and order_header.ml_pack_id.strip():
            if pack_item_counts is not None:
                items_en_shipping = pack_item_counts.get(order_header.ml_pack_id, 1)
            else:
                items_en_shipping = (
                    db.query(func.count(MercadoLibreOrderDetail.mlod_id))
                    .join(MercadoLibreOrderHeader, MercadoLibreOrderDetail.mlo_id == MercadoLibreOrderHeader.mlo_id)
                    .filter(MercadoLibreOrderHeader.ml_pack_id == order_header.ml_pack_id)
                    .scalar()
                    or 1
                )
        elif shipping:
            if order_item_counts is not None:
                items_en_shipping = order_item_counts.get(order_header.mlo_id, 1)
            else:
                items_en_shipping = (
                    db.query(func.count(MercadoLibreOrderDetail.mlod_id))
                    .filter(MercadoLibreOrderDetail.mlo_id == order_header.mlo_id)
                    .scalar()
                    or 1
                )

        monto_total_sin_iva = monto_total / 1.21
        costo_envio_ml_sin_iva = costo_envio_ml / 1.21
        costo_envio_ml_prorrateado = (costo_envio_ml_sin_iva * cantidad) / items_en_shipping
        monto_limpio = monto_total_sin_iva - comision_ml - costo_envio_ml_prorrateado
        costo_total = costo_sin_iva_total_ars
        ganancia = monto_limpio - costo_sin_iva_total_ars
        markup_porcentaje = (ganancia / costo_sin_iva_total_ars * 100) if costo_sin_iva_total_ars > 0 else 0.0

        mla_id = publicacion_ml.mlp_publicationID if publicacion_ml else None

        if existente:
            # Update existing — populate mlp_official_store_id (GAP fix)
            existente.ml_order_id = order_header.mlo_id
            existente.pack_id = (
                int(order_header.ml_pack_id) if order_header.ml_pack_id and order_header.ml_pack_id.isdigit() else None
            )
            existente.item_id = order_detail.item_id
            existente.codigo = producto.codigo if producto else None
            existente.descripcion = order_detail.mlo_title
            existente.marca = producto.marca if producto else None
            existente.categoria = producto.categoria if producto else None
            existente.subcategoria = producto.subcategoria_id if producto else None
            existente.fecha_venta = fecha_venta
            existente.fecha_calculo = date.today()
            existente.cantidad = int(cantidad)
            existente.monto_unitario = Decimal(str(round(monto_unitario, 2)))
            existente.monto_total = Decimal(str(round(monto_total, 2)))
            existente.cotizacion_dolar = Decimal(str(round(cotizacion, 4)))
            existente.costo_unitario_sin_iva = Decimal(
                str(round(costo_sin_iva_total_ars / cantidad if cantidad > 0 else 0, 6))
            )
            existente.costo_total_sin_iva = Decimal(str(round(costo_sin_iva_total_ars, 2)))
            existente.moneda_costo = moneda_costo
            existente.tipo_lista = tipo_lista
            existente.porcentaje_comision_ml = Decimal(str(round(comision_pct, 2)))
            existente.comision_ml = Decimal(str(round(comision_ml, 2)))
            existente.costo_envio_ml = Decimal(str(round(costo_envio_ml, 2)))
            existente.tipo_logistica = tipo_logistica
            existente.monto_limpio = Decimal(str(round(monto_limpio, 2)))
            existente.costo_total = Decimal(str(round(costo_total, 2)))
            existente.ganancia = Decimal(str(round(ganancia, 2)))
            existente.markup_porcentaje = Decimal(str(round(markup_porcentaje, 2)))
            existente.prli_id = prli_id
            existente.mla_id = mla_id
            existente.mlp_official_store_id = TPLINK_STORE_ID  # GAP fix: populate store id on update
            return "actualizado"
        else:
            # Insert new — populate mlp_official_store_id (GAP fix)
            metrica = TplinkVentaMetrica(
                id_operacion=order_detail.mlod_id,
                ml_order_id=order_header.mlo_id,
                pack_id=int(order_header.ml_pack_id)
                if order_header.ml_pack_id and order_header.ml_pack_id.isdigit()
                else None,
                item_id=order_detail.item_id,
                codigo=producto.codigo if producto else None,
                descripcion=order_detail.mlo_title,
                marca=producto.marca if producto else None,
                categoria=producto.categoria if producto else None,
                subcategoria=producto.subcategoria_id if producto else None,
                fecha_venta=fecha_venta,
                fecha_calculo=date.today(),
                cantidad=int(cantidad),
                monto_unitario=Decimal(str(round(monto_unitario, 2))),
                monto_total=Decimal(str(round(monto_total, 2))),
                cotizacion_dolar=Decimal(str(round(cotizacion, 4))),
                costo_unitario_sin_iva=Decimal(
                    str(round(costo_sin_iva_total_ars / cantidad if cantidad > 0 else 0, 6))
                ),
                costo_total_sin_iva=Decimal(str(round(costo_sin_iva_total_ars, 2))),
                moneda_costo=moneda_costo,
                tipo_lista=tipo_lista,
                porcentaje_comision_ml=Decimal(str(round(comision_pct, 2))),
                comision_ml=Decimal(str(round(comision_ml, 2))),
                costo_envio_ml=Decimal(str(round(costo_envio_ml, 2))),
                tipo_logistica=tipo_logistica,
                monto_limpio=Decimal(str(round(monto_limpio, 2))),
                costo_total=Decimal(str(round(costo_total, 2))),
                ganancia=Decimal(str(round(ganancia, 2))),
                markup_porcentaje=Decimal(str(round(markup_porcentaje, 2))),
                prli_id=prli_id,
                mla_id=mla_id,
                mlp_official_store_id=TPLINK_STORE_ID,  # GAP fix: always populate store id
            )
            db.add(metrica)
            return "insertado"

    except Exception as e:
        print(f"  Error procesando {order_detail.mlod_id}: {str(e)}")
        import traceback

        traceback.print_exc()
        return "error"


async def agregar_metricas_rango(from_date: date, to_date: date, batch_size: int = 100) -> None:
    """Adds metrics for a date range (full/historical job)."""
    global _missing_cost_count, _missing_cost_sample

    # Reset missing-cost tracking at start of run
    _missing_cost_count = 0
    _missing_cost_sample = []

    db = SessionLocal()

    try:
        print(f"\n{'=' * 60}")
        print("AGREGACION DE METRICAS TP-LINK (store 2645, coslis_id=8)")
        print(f"{'=' * 60}")

        to_date_inclusive = to_date + timedelta(days=1)
        print(f"Rango: {from_date} a {to_date} (inclusive)")
        print(f"Query: {from_date} <= fecha < {to_date_inclusive}")
        print()

        constantes = obtener_constantes_pricing(db)
        print(f"Constantes: MONTOT3={constantes['monto_tier3']}")
        print()

        total_orders = (
            db.query(func.count(MercadoLibreOrderHeader.mlo_id))
            .filter(
                and_(
                    MercadoLibreOrderHeader.ml_date_created >= from_date,
                    MercadoLibreOrderHeader.ml_date_created < to_date_inclusive,
                )
            )
            .scalar()
        )

        print(f"Ordenes encontradas: {total_orders}")
        print()

        # Pre-calculate item counts per pack/order for optimization
        pack_counts_query = (
            db.query(MercadoLibreOrderHeader.ml_pack_id, func.count(MercadoLibreOrderDetail.mlod_id).label("count"))
            .join(MercadoLibreOrderDetail, MercadoLibreOrderHeader.mlo_id == MercadoLibreOrderDetail.mlo_id)
            .filter(
                and_(
                    MercadoLibreOrderHeader.ml_date_created >= from_date,
                    MercadoLibreOrderHeader.ml_date_created < to_date_inclusive,
                    MercadoLibreOrderHeader.ml_pack_id.isnot(None),
                    MercadoLibreOrderHeader.ml_pack_id != "",
                )
            )
            .group_by(MercadoLibreOrderHeader.ml_pack_id)
            .all()
        )

        pack_item_counts = {pack_id: count for pack_id, count in pack_counts_query}

        order_counts_query = (
            db.query(MercadoLibreOrderDetail.mlo_id, func.count(MercadoLibreOrderDetail.mlod_id).label("count"))
            .join(MercadoLibreOrderHeader, MercadoLibreOrderDetail.mlo_id == MercadoLibreOrderHeader.mlo_id)
            .filter(
                and_(
                    MercadoLibreOrderHeader.ml_date_created >= from_date,
                    MercadoLibreOrderHeader.ml_date_created < to_date_inclusive,
                )
            )
            .group_by(MercadoLibreOrderDetail.mlo_id)
            .all()
        )

        order_item_counts = {mlo_id: count for mlo_id, count in order_counts_query}

        total_insertados = 0
        total_actualizados = 0
        total_errores = 0
        total_skipped = 0
        orden_count = 0

        CHUNK_SIZE = 1000
        offset = 0

        while True:
            orders_chunk = (
                db.query(MercadoLibreOrderHeader)
                .filter(
                    and_(
                        MercadoLibreOrderHeader.ml_date_created >= from_date,
                        MercadoLibreOrderHeader.ml_date_created < to_date_inclusive,
                    )
                )
                .order_by(MercadoLibreOrderHeader.mlo_id)
                .limit(CHUNK_SIZE)
                .offset(offset)
                .all()
            )

            if not orders_chunk:
                break

            for order in orders_chunk:
                orden_count += 1
                details = db.query(MercadoLibreOrderDetail).filter(MercadoLibreOrderDetail.mlo_id == order.mlo_id).all()

                if not details:
                    continue

                for detail in details:
                    resultado = await agregar_metricas_venta(
                        db,
                        order,
                        detail,
                        constantes,
                        pack_item_counts=pack_item_counts,
                        order_item_counts=order_item_counts,
                    )

                    if resultado == "insertado":
                        total_insertados += 1
                    elif resultado == "actualizado":
                        total_actualizados += 1
                    elif resultado == "error":
                        total_errores += 1
                    elif resultado == "skipped":
                        total_skipped += 1

                try:
                    db.commit()
                except Exception as e:
                    print(f"  Error commit orden {order.mlo_id}: {str(e)}")
                    db.rollback()

                if (total_insertados + total_actualizados) % batch_size == 0 and (
                    total_insertados + total_actualizados
                ) > 0:
                    print(
                        f"  Procesados: {total_insertados + total_actualizados} | Nuevos: {total_insertados} | Actualizados: {total_actualizados}"
                    )

            offset += CHUNK_SIZE

        print()
        print(f"{'=' * 60}")
        print("COMPLETADO")
        print(f"{'=' * 60}")
        print(f"Insertados: {total_insertados}")
        print(f"Actualizados: {total_actualizados}")
        print(f"Skipped (non-2645 store): {total_skipped}")
        print(f"Errores: {total_errores}")

        # Missing-cost end-of-run summary
        if _missing_cost_count > 0:
            sample_str = ", ".join(str(i) for i in _missing_cost_sample[:10])
            print(
                f"\nAVISO: {_missing_cost_count} items sin costo lista 8 (coslis_id=8). "
                f"Muestra item_ids: [{sample_str}]"
            )
        else:
            print("\nTodos los items tienen costo en lista 8.")

    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Agregar metricas TP-Link (store 2645, coslis_id=8)")
    parser.add_argument("--from-date", required=True, help="Fecha inicio YYYY-MM-DD")
    parser.add_argument("--to-date", default=None, help="Fecha fin YYYY-MM-DD (default: hoy)")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    from_date = datetime.strptime(args.from_date, "%Y-%m-%d").date()
    to_date = datetime.strptime(args.to_date, "%Y-%m-%d").date() if args.to_date else date.today()

    asyncio.run(agregar_metricas_rango(from_date, to_date, args.batch_size))


if __name__ == "__main__":
    main()
