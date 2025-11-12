from app.core.database import SessionLocal
from app.models.producto import ProductoERP

db = SessionLocal()

# Item 3287 (198154111069-1TWH)
item_id = 3287
print(f'\n=== Verificando producto item_id: {item_id} ===')

producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()

if producto:
    print(f'Codigo: {producto.codigo}')
    print(f'Descripcion: {producto.descripcion}')
    print(f'Costo: {producto.costo}')
    print(f'Moneda: {producto.moneda}')
    print(f'Activo: {producto.activo}')
else:
    print('❌ No se encontró el producto')

# Item 3417
print('\n' + '='*80)
item_id = 3417
print(f'\n=== Verificando producto item_id: {item_id} ===')

producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()

if producto:
    print(f'Codigo: {producto.codigo}')
    print(f'Descripcion: {producto.descripcion}')
    print(f'Costo: {producto.costo}')
    print(f'Moneda: {producto.moneda}')
    print(f'Activo: {producto.activo}')
else:
    print('❌ No se encontró el producto')

db.close()
