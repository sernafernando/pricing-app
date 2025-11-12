from app.core.database import SessionLocal
from app.models.ml_venta_metrica import MLVentaMetrica
from sqlalchemy import and_

db = SessionLocal()

result = db.query(
    MLVentaMetrica.item_id,
    MLVentaMetrica.codigo,
    MLVentaMetrica.descripcion,
    MLVentaMetrica.monto_total,
    MLVentaMetrica.costo_total_sin_iva,
    MLVentaMetrica.ganancia,
    MLVentaMetrica.markup_porcentaje,
    MLVentaMetrica.moneda_costo,
    MLVentaMetrica.cantidad
).filter(
    and_(
        MLVentaMetrica.categoria == 'NOTEBOOK',
        MLVentaMetrica.fecha_venta >= '2025-11-01',
        MLVentaMetrica.fecha_venta <= '2025-11-12'
    )
).order_by(MLVentaMetrica.monto_total.desc()).limit(10).all()

print('Top 10 NOTEBOOK por monto de venta:')
print('-' * 120)
for r in result:
    desc_corta = r.descripcion[:40] if r.descripcion else 'N/A'
    print(f'Item: {r.item_id} | Codigo: {r.codigo} | Cant: {r.cantidad}')
    print(f'  Descripcion: {desc_corta}')
    print(f'  Venta: ${r.monto_total} | Costo: ${r.costo_total_sin_iva} | Ganancia: ${r.ganancia}')
    print(f'  Markup: {r.markup_porcentaje}% | Moneda: {r.moneda_costo}')
    print('-' * 120)

db.close()
