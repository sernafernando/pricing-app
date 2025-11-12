from app.core.database import SessionLocal
from app.models.item_cost_list_history import ItemCostListHistory
from sqlalchemy import and_, desc

db = SessionLocal()

# Verificar item_id 3417 que tiene costo 0
item_id = 3417
print(f'\n=== Verificando costos para item_id: {item_id} ===')

# Buscar cualquier costo en historial
all_costs = db.query(ItemCostListHistory).filter(
    ItemCostListHistory.item_id == item_id
).order_by(desc(ItemCostListHistory.iclh_cd)).limit(10).all()

if all_costs:
    print(f'\nSe encontraron {len(all_costs)} registros de costo:')
    for cost in all_costs:
        print(f'  coslis_id: {cost.coslis_id} | iclh_cd: {cost.iclh_cd} | iclh_price: {cost.iclh_price} | curr_id: {cost.curr_id}')
else:
    print('❌ No se encontraron costos en item_cost_list_history')

# Verificar coslis_id = 1 específicamente
costs_list1 = db.query(ItemCostListHistory).filter(
    and_(
        ItemCostListHistory.item_id == item_id,
        ItemCostListHistory.coslis_id == 1
    )
).order_by(desc(ItemCostListHistory.iclh_cd)).limit(5).all()

print(f'\nCostos con coslis_id = 1:')
if costs_list1:
    for cost in costs_list1:
        print(f'  iclh_cd: {cost.iclh_cd} | iclh_price: {cost.iclh_price} | curr_id: {cost.curr_id}')
else:
    print('❌ No hay costos con coslis_id = 1')

# Probar con otro item que tiene costo 0
print('\n' + '='*80)
item_id = 3345
print(f'\n=== Verificando costos para item_id: {item_id} ===')

all_costs = db.query(ItemCostListHistory).filter(
    ItemCostListHistory.item_id == item_id
).order_by(desc(ItemCostListHistory.iclh_cd)).limit(10).all()

if all_costs:
    print(f'\nSe encontraron {len(all_costs)} registros de costo:')
    for cost in all_costs:
        print(f'  coslis_id: {cost.coslis_id} | iclh_cd: {cost.iclh_cd} | iclh_price: {cost.iclh_price} | curr_id: {cost.curr_id}')
else:
    print('❌ No se encontraron costos en item_cost_list_history')

db.close()
