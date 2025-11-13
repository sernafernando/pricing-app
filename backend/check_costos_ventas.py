"""
Script para comparar costos de productos en ventas ML
"""
from app.core.database import SessionLocal
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.producto import ProductoERP
from app.models.item_cost_list_history import ItemCostListHistory
from sqlalchemy import and_, desc
from datetime import datetime

db = SessionLocal()

# Buscar algunas ventas de NOTEBOOK con costo 0
print("\n=== Ventas de NOTEBOOK con costo 0 ===")
ventas_sin_costo = db.query(MLVentaMetrica).filter(
    and_(
        MLVentaMetrica.categoria == 'NOTEBOOK',
        MLVentaMetrica.costo_total_sin_iva == 0,
        MLVentaMetrica.fecha_venta >= '2025-11-01',
        MLVentaMetrica.fecha_venta <= '2025-11-12'
    )
).limit(5).all()

for venta in ventas_sin_costo:
    print(f"\nItem ID: {venta.item_id}")
    print(f"  Codigo: {venta.codigo}")
    print(f"  Descripcion: {venta.descripcion[:50]}")
    print(f"  Fecha venta: {venta.fecha_venta}")
    print(f"  Cantidad: {venta.cantidad}")
    print(f"  Monto total: ${venta.monto_total}")
    print(f"  Costo guardado: ${venta.costo_total_sin_iva}")

    # Verificar en productos_erp
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == venta.item_id).first()
    if producto:
        print(f"  Costo en productos_erp: {producto.costo} {producto.moneda_costo.value if producto.moneda_costo else 'N/A'}")
    else:
        print(f"  NO EXISTE en productos_erp")

    # Verificar en historial
    hist = db.query(ItemCostListHistory).filter(
        and_(
            ItemCostListHistory.item_id == venta.item_id,
            ItemCostListHistory.coslis_id == 1,
            ItemCostListHistory.iclh_cd <= venta.fecha_venta
        )
    ).order_by(desc(ItemCostListHistory.iclh_cd)).first()

    if hist:
        moneda = "USD" if hist.curr_id == 2 else "ARS"
        print(f"  Costo en historial: {hist.iclh_price} {moneda} (fecha: {hist.iclh_cd})")
    else:
        print(f"  NO HAY historial de costos")

# Ahora buscar ventas con costo muy alto
print("\n\n=== Ventas de NOTEBOOK con markup muy bajo ===")
ventas_markup_bajo = db.query(MLVentaMetrica).filter(
    and_(
        MLVentaMetrica.categoria == 'NOTEBOOK',
        MLVentaMetrica.markup_porcentaje < 5,
        MLVentaMetrica.markup_porcentaje > -50,
        MLVentaMetrica.fecha_venta >= '2025-11-01',
        MLVentaMetrica.fecha_venta <= '2025-11-12'
    )
).order_by(MLVentaMetrica.costo_total_sin_iva.desc()).limit(5).all()

for venta in ventas_markup_bajo:
    print(f"\nItem ID: {venta.item_id}")
    print(f"  Codigo: {venta.codigo}")
    print(f"  Descripcion: {venta.descripcion[:50]}")
    print(f"  Fecha venta: {venta.fecha_venta}")
    print(f"  Cantidad: {venta.cantidad}")
    print(f"  Monto total: ${venta.monto_total}")
    print(f"  Costo total sin IVA: ${venta.costo_total_sin_iva} {venta.moneda_costo}")
    print(f"  Ganancia: ${venta.ganancia}")
    print(f"  Markup: {venta.markup_porcentaje}%")

    # Si el costo está en USD, calcular cuánto debería ser
    if venta.moneda_costo == "USD" and venta.cotizacion_dolar:
        costo_usd = float(venta.costo_total_sin_iva) / float(venta.cotizacion_dolar) / venta.cantidad
        print(f"  Costo unitario USD estimado: ${costo_usd:.2f}")

db.close()
