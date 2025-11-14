"""
Script para agregar métricas de ventas ML
Lee de ml_orders + item_transactions (costo real) o item_cost_list_history (fallback)
Calcula markup, comisiones, costos y guarda en ml_ventas_metricas

Ejecutar:
    python app/scripts/agregar_metricas_ml.py --fecha-desde 2025-11-01 --fecha-hasta 2025-11-12
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
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.mercadolibre_order_detail import MercadoLibreOrderDetail
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.item_cost_list_history import ItemCostListHistory
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


def obtener_costo_item(
    db: Session,
    item_id: int,
    fecha_venta: datetime,
    cantidad: float,
    mlo_id: int
) -> tuple[float, str]:
    """
    Obtiene el costo sin IVA del item al momento de la venta.

    Prioridad:
    1. Historial de costos (item_cost_list_history) antes de la fecha de venta
    2. Costo actual del historial (sin filtro de fecha)
    3. Costo actual del producto (productos_erp.costo)

    Returns:
        (costo_total_sin_iva, moneda)
    """

    # 1. Obtener de historial de costos antes de la fecha de venta
    cost_history = db.query(ItemCostListHistory).filter(
        and_(
            ItemCostListHistory.item_id == item_id,
            ItemCostListHistory.coslis_id == 1,  # Lista de costos principal
            ItemCostListHistory.iclh_cd <= fecha_venta
        )
    ).order_by(desc(ItemCostListHistory.iclh_cd)).first()

    if cost_history and cost_history.iclh_price and float(cost_history.iclh_price) > 0:
        costo_unitario = float(cost_history.iclh_price)
        costo_total = costo_unitario * cantidad
        # Mapeo de curr_id: 1=ARS, 2=USD (según estándar ERP)
        moneda = "USD" if cost_history.curr_id == 2 else "ARS"
        return (costo_total, moneda)

    # 2. Fallback: costo actual más reciente del historial
    cost_actual = db.query(ItemCostListHistory).filter(
        and_(
            ItemCostListHistory.item_id == item_id,
            ItemCostListHistory.coslis_id == 1
        )
    ).order_by(desc(ItemCostListHistory.iclh_cd)).first()

    if cost_actual and cost_actual.iclh_price and float(cost_actual.iclh_price) > 0:
        costo_unitario = float(cost_actual.iclh_price)
        costo_total = costo_unitario * cantidad
        moneda = "USD" if cost_actual.curr_id == 2 else "ARS"
        return (costo_total, moneda)

    # 3. Último fallback: costo actual del producto
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()

    if producto and producto.costo and float(producto.costo) > 0:
        costo_unitario = float(producto.costo)
        costo_total = costo_unitario * cantidad
        moneda = "USD" if producto.moneda_costo and producto.moneda_costo.value == "USD" else "ARS"
        return (costo_total, moneda)

    # Si no hay datos, retornar 0
    return (0.0, "ARS")


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

        # Calcular métricas
        fecha_venta = order_header.ml_date_created if order_header.ml_date_created else datetime.now()
        cotizacion = await obtener_cotizacion_fecha(db, fecha_venta.date())

        cantidad = float(order_detail.mlo_quantity) if order_detail.mlo_quantity else 1.0
        monto_unitario = float(order_detail.mlo_unit_price) if order_detail.mlo_unit_price else 0.0
        monto_total = monto_unitario * cantidad

        # Obtener costo (prioridad: item_transaction > cost_history)
        costo_sin_iva_total, moneda_costo = obtener_costo_item(
            db,
            order_detail.item_id,
            fecha_venta,
            cantidad,
            order_header.mlo_id
        )

        # Convertir costo a ARS si está en USD
        # Guardar moneda original para referencia
        moneda_costo_original = moneda_costo
        if moneda_costo == "USD":
            costo_sin_iva_total_ars = costo_sin_iva_total * cotizacion
            # Después de pesificar, la moneda es ARS
            moneda_costo = "ARS"
        else:
            costo_sin_iva_total_ars = costo_sin_iva_total

        # Grupo y comisión
        grupo_id = 1
        if producto and producto.subcategoria_id:
            grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)

        prli_id = publicacion_ml.prli_id if publicacion_ml else 4
        tipo_lista = publicacion_ml.mlp_listing_type_id if publicacion_ml and publicacion_ml.mlp_listing_type_id else "unknown"

        comision_pct = obtener_comision_versionada(db, grupo_id, prli_id, fecha_venta.date()) or 15.0

        comision_ml_detalle = calcular_comision_ml_total(
            precio=monto_total,
            comision_base_pct=comision_pct,
            iva=21.0,
            constantes=constantes,
            db=db
        )

        comision_ml = comision_ml_detalle["comision_total"]

        # Costo de envío: para productos < 33k usar mlp_price4FreeShipping
        MONTOT3 = constantes.get("monto_tier3", 33000)

        costo_envio_ml = 0.0
        if monto_total < MONTOT3 and publicacion_ml and publicacion_ml.mlp_price4FreeShipping:
            costo_envio_ml = float(publicacion_ml.mlp_price4FreeShipping)
        elif shipping and shipping.mlshippmentcost4seller:
            costo_envio_ml = float(shipping.mlshippmentcost4seller)

        tipo_logistica = shipping.mllogistic_type if shipping and shipping.mllogistic_type else "unknown"

        # Prorratear envío entre items del mismo pack
        # Si hay ml_pack_id, contar items en el pack; sino, contar items en la orden
        items_en_shipping = 1  # Default
        if order_header.ml_pack_id and order_header.ml_pack_id.strip():
            # Contar todos los items en todas las órdenes del mismo pack
            items_en_shipping = db.query(func.count(MercadoLibreOrderDetail.mlod_id)).join(
                MercadoLibreOrderHeader,
                MercadoLibreOrderDetail.mlo_id == MercadoLibreOrderHeader.mlo_id
            ).filter(
                MercadoLibreOrderHeader.ml_pack_id == order_header.ml_pack_id
            ).scalar() or 1
        elif shipping:
            # Si no hay pack, contar items de la orden
            items_en_shipping = db.query(func.count(MercadoLibreOrderDetail.mlod_id)).filter(
                MercadoLibreOrderDetail.mlo_id == order_header.mlo_id
            ).scalar() or 1

        # Cálculos finales
        # Nota: calcular_comision_ml_total YA retorna comisiones sin IVA
        # (divide internamente por 1.21), así que NO dividimos comision_ml otra vez
        monto_total_sin_iva = monto_total / 1.21
        costo_envio_ml_sin_iva = costo_envio_ml / 1.21

        # Envío prorrateado: (costo_envio * cantidad del item) / items en el pack
        costo_envio_ml_prorrateado = (costo_envio_ml_sin_iva * cantidad) / items_en_shipping

        # Limpio = lo que queda después de restar comisiones y envío ML prorrateado (todo sin IVA)
        monto_limpio = monto_total_sin_iva - comision_ml - costo_envio_ml_prorrateado

        # Costo total = solo costo del producto (igual que Streamlit)
        # El envío ya se restó del limpio, no lo sumamos acá
        costo_total = costo_sin_iva_total_ars

        # Ganancia = limpio - costo del producto (el envío ya se restó en limpio)
        ganancia = monto_limpio - costo_sin_iva_total_ars

        # Markup = ganancia sobre costo del producto
        markup_porcentaje = (ganancia / costo_sin_iva_total_ars * 100) if costo_sin_iva_total_ars > 0 else 0.0

        mla_id = publicacion_ml.mlp_publicationID if publicacion_ml else None

        # Crear o actualizar métrica
        if existente:
            # Actualizar existente
            existente.ml_order_id = order_header.mlo_id
            existente.pack_id = int(order_header.ml_pack_id) if order_header.ml_pack_id and order_header.ml_pack_id.isdigit() else None
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
            existente.costo_unitario_sin_iva = Decimal(str(round(costo_sin_iva_total_ars / cantidad if cantidad > 0 else 0, 6)))
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
            return "actualizado"
        else:
            # Crear nuevo
            metrica = MLVentaMetrica(
                id_operacion=order_detail.mlod_id,
                ml_order_id=order_header.mlo_id,
                pack_id=int(order_header.ml_pack_id) if order_header.ml_pack_id and order_header.ml_pack_id.isdigit() else None,
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
                costo_unitario_sin_iva=Decimal(str(round(costo_sin_iva_total_ars / cantidad if cantidad > 0 else 0, 6))),
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
        import traceback
        traceback.print_exc()
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
        total_actualizados = 0
        total_errores = 0

        orden_count = 0
        for order in orders:
            orden_count += 1
            details = db.query(MercadoLibreOrderDetail).filter(
                MercadoLibreOrderDetail.mlo_id == order.mlo_id
            ).all()

            if not details:
                if orden_count <= 5:  # Solo mostrar las primeras 5
                    print(f"  ⚠️  Orden {order.mlo_id} sin detalles")
                continue

            for detail in details:
                resultado = await agregar_metricas_venta(db, order, detail, constantes)

                if resultado == "insertado":
                    total_insertados += 1
                elif resultado == "actualizado":
                    total_actualizados += 1
                elif resultado == "error":
                    total_errores += 1

            try:
                db.commit()
            except Exception as e:
                print(f"  ❌ Error commit orden {order.mlo_id}: {str(e)}")
                db.rollback()

            if (total_insertados + total_actualizados) % batch_size == 0 and (total_insertados + total_actualizados) > 0:
                print(f"  Procesados: {total_insertados + total_actualizados} | Nuevos: {total_insertados} | Actualizados: {total_actualizados}")

        print()
        print(f"{'='*60}")
        print(f"✅ COMPLETADO")
        print(f"{'='*60}")
        print(f"Insertados: {total_insertados}")
        print(f"Actualizados: {total_actualizados}")
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
