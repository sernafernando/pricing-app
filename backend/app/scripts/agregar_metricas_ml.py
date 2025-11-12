"""
Script para agregar métricas de ventas ML
Lee de ml_orders_header, ml_orders_detail, ml_orders_shipping, commercial_transactions
Calcula markup, comisiones, costos y guarda en ml_ventas_metricas

Ejecutar:
    python -m app.scripts.agregar_metricas_ml --from-date 2025-11-01 --to-date 2025-11-12
"""
import asyncio
import argparse
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.mercadolibre_order_detail import MercadoLibreOrderDetail
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.commercial_transaction import CommercialTransaction
from app.models.producto import ProductoERP
from app.models.tipo_cambio import TipoCambio
from app.services.pricing_calculator import (
    obtener_constantes_pricing,
    obtener_grupo_subcategoria,
    obtener_comision_versionada,
    calcular_comision_ml_total
)


async def obtener_cotizacion_fecha(db: Session, fecha: date) -> float:
    """Obtiene la cotización del dólar para una fecha específica"""
    tc = db.query(TipoCambio).filter(
        TipoCambio.moneda == "USD",
        TipoCambio.fecha == fecha
    ).first()

    if tc:
        return float(tc.venta)

    # Si no hay para esa fecha, buscar la más reciente anterior
    tc = db.query(TipoCambio).filter(
        TipoCambio.moneda == "USD",
        TipoCambio.fecha <= fecha
    ).order_by(TipoCambio.fecha.desc()).first()

    return float(tc.venta) if tc else 1000.0


async def agregar_metricas_venta(
    db: Session,
    order_header: MercadoLibreOrderHeader,
    order_detail: MercadoLibreOrderDetail,
    constantes: dict
):
    """Procesa una venta individual y calcula todas las métricas"""
    try:
        # Verificar si ya existe
        existente = db.query(MLVentaMetrica).filter(
            MLVentaMetrica.id_operacion == order_detail.mlod_id
        ).first()

        if existente:
            return "existe"

        # Obtener información del shipping
        shipping = db.query(MercadoLibreOrderShipping).filter(
            MercadoLibreOrderShipping.mlo_id == order_header.mlo_id
        ).first()

        # Obtener información del producto
        producto = None
        if order_detail.item_id:
            producto = db.query(ProductoERP).filter(
                ProductoERP.item_id == order_detail.item_id
            ).first()

        # Obtener publicación ML
        publicacion_ml = None
        if order_detail.mlp_id:
            publicacion_ml = db.query(MercadoLibreItemPublicado).filter(
                MercadoLibreItemPublicado.mlp_id == order_detail.mlp_id
            ).first()

        # Obtener commercial_transaction
        commercial_tx = db.query(CommercialTransaction).filter(
            CommercialTransaction.mlo_id == order_header.mlo_id
        ).first()

        if not commercial_tx:
            return "sin_commercial_tx"

        # Calcular métricas
        fecha_venta = order_header.ml_date_created.date() if order_header.ml_date_created else date.today()
        cotizacion = await obtener_cotizacion_fecha(db, fecha_venta)

        cantidad = float(order_detail.mlo_quantity) if order_detail.mlo_quantity else 1.0
        monto_unitario = float(order_detail.mlo_unit_price) if order_detail.mlo_unit_price else 0.0
        monto_total = monto_unitario * cantidad

        costo_sin_iva_total = float(commercial_tx.cost) if commercial_tx.cost else 0.0
        moneda_costo = commercial_tx.currency or "ARS"

        if moneda_costo == "USD":
            costo_sin_iva_total_ars = costo_sin_iva_total * cotizacion
        else:
            costo_sin_iva_total_ars = costo_sin_iva_total

        # Grupo y comisión
        grupo_id = 1
        if producto and producto.subcategoria_id:
            grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)

        prli_id = publicacion_ml.prli_id if publicacion_ml else 4
        tipo_lista = publicacion_ml.mlp_listing_type_id if publicacion_ml and publicacion_ml.mlp_listing_type_id else "unknown"

        comision_pct = obtener_comision_versionada(db, grupo_id, prli_id, fecha_venta) or 15.0

        comision_ml_detalle = calcular_comision_ml_total(
            precio=monto_total,
            comision_base_pct=comision_pct,
            iva=21.0,
            constantes=constantes,
            db=db
        )

        comision_ml = comision_ml_detalle["comision_total"]

        # Costo de envío
        MONTOT3 = constantes.get("monto_tier3", 33000)

        if monto_total < MONTOT3 and publicacion_ml and publicacion_ml.mlp_price4FreeShipping:
            costo_envio_ml = float(publicacion_ml.mlp_price4FreeShipping)
        elif shipping and shipping.mlshippmentcost4seller:
            costo_envio_ml = float(shipping.mlshippmentcost4seller)
        else:
            costo_envio_ml = 0.0

        tipo_logistica = shipping.mllogistic_type if shipping and shipping.mllogistic_type else "unknown"

        # Cálculos finales
        monto_limpio = monto_total - comision_ml - costo_envio_ml
        costo_total = costo_sin_iva_total_ars + costo_envio_ml
        ganancia = monto_limpio - costo_sin_iva_total_ars
        markup_porcentaje = (ganancia / costo_sin_iva_total_ars * 100) if costo_sin_iva_total_ars > 0 else 0.0

        mla_id = publicacion_ml.mlp_publicationID if publicacion_ml else None

        # Crear métrica
        metrica = MLVentaMetrica(
            id_operacion=order_detail.mlod_id,
            ml_order_id=order_header.mlo_id,
            pack_id=int(order_header.ml_pack_id) if order_header.ml_pack_id and order_header.ml_pack_id.isdigit() else None,
            item_id=order_detail.item_id,
            codigo=producto.codigo if producto else None,
            descripcion=order_detail.mlo_title,
            marca=producto.marca if producto else None,
            categoria=producto.categoria if producto else None,
            subcategoria=producto.subcategoria if producto else None,
            fecha_venta=order_header.ml_date_created,
            fecha_calculo=date.today(),
            cantidad=int(cantidad),
            monto_unitario=Decimal(str(round(monto_unitario, 2))),
            monto_total=Decimal(str(round(monto_total, 2))),
            cotizacion_dolar=Decimal(str(round(cotizacion, 4))),
            costo_unitario_sin_iva=Decimal(str(round(costo_sin_iva_total / cantidad if cantidad > 0 else 0, 6))),
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
            mla_id=mla_id
        )

        db.add(metrica)
        return "insertado"

    except Exception as e:
        print(f"  ❌ Error procesando {order_detail.mlod_id}: {str(e)}")
        return "error"


async def agregar_metricas_rango(from_date: date, to_date: date, batch_size: int = 100):
    """Agrega métricas para un rango de fechas"""
    db = SessionLocal()

    try:
        print(f"\n{'='*60}")
        print(f"AGREGACIÓN DE MÉTRICAS ML")
        print(f"{'='*60}")
        print(f"Rango: {from_date} a {to_date}")
        print()

        constantes = obtener_constantes_pricing(db)
        print(f"Constantes: MONTOT3={constantes['monto_tier3']}")
        print()

        to_date_plus_one = to_date + timedelta(days=1)
        orders = db.query(MercadoLibreOrderHeader).filter(
            and_(
                MercadoLibreOrderHeader.ml_date_created >= from_date,
                MercadoLibreOrderHeader.ml_date_created < to_date_plus_one
            )
        ).all()

        print(f"📦 Órdenes encontradas: {len(orders)}")
        print()

        total_insertados = 0
        total_existentes = 0
        total_errores = 0
        total_sin_commercial = 0

        for order in orders:
            details = db.query(MercadoLibreOrderDetail).filter(
                MercadoLibreOrderDetail.mlo_id == order.mlo_id
            ).all()

            for detail in details:
                resultado = await agregar_metricas_venta(db, order, detail, constantes)

                if resultado == "insertado":
                    total_insertados += 1
                elif resultado == "existe":
                    total_existentes += 1
                elif resultado == "sin_commercial_tx":
                    total_sin_commercial += 1
                else:
                    total_errores += 1

            try:
                db.commit()
            except Exception as e:
                print(f"  ❌ Error commit orden {order.mlo_id}: {str(e)}")
                db.rollback()

            if (total_insertados + total_existentes) % batch_size == 0:
                print(f"  Procesados: {total_insertados + total_existentes} | Nuevos: {total_insertados}")

        print()
        print(f"{'='*60}")
        print(f"✅ COMPLETADO")
        print(f"{'='*60}")
        print(f"Insertados: {total_insertados}")
        print(f"Existentes: {total_existentes}")
        print(f"Sin CommTx: {total_sin_commercial}")
        print(f"Errores: {total_errores}")

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-date', required=True)
    parser.add_argument('--to-date', required=True)
    parser.add_argument('--batch-size', type=int, default=100)
    args = parser.parse_args()

    from_date = datetime.strptime(args.from_date, '%Y-%m-%d').date()
    to_date = datetime.strptime(args.to_date, '%Y-%m-%d').date()

    asyncio.run(agregar_metricas_rango(from_date, to_date, args.batch_size))


if __name__ == "__main__":
    main()
