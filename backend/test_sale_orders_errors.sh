#!/bin/bash
# Script para probar sync_sale_orders_all y ver los errores

cd /var/www/html/pricing-app/backend

echo "🔍 Probando sync con 1 día para ver errores..."
echo ""

source venv/bin/activate 2>/dev/null || true

python -m app.scripts.sync_sale_orders_all --days 1

echo ""
echo "📊 Verificando registros en DB..."
echo ""

python << 'PYEOF'
from app.core.database import SessionLocal
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_detail import SaleOrderDetail
from sqlalchemy import func
from datetime import datetime, timedelta

db = SessionLocal()

# Contar registros de hoy
today = datetime.now().date()
yesterday = today - timedelta(days=1)

headers_today = db.query(func.count(SaleOrderHeader.soh_id)).filter(
    func.date(SaleOrderHeader.soh_cd) >= yesterday
).scalar()

details_today = db.query(func.count(SaleOrderDetail.sod_id)).filter(
    SaleOrderDetail.soh_id.in_(
        db.query(SaleOrderHeader.soh_id).filter(
            func.date(SaleOrderHeader.soh_cd) >= yesterday
        )
    )
).scalar()

print(f"✅ Sale Order Headers de ayer/hoy: {headers_today}")
print(f"✅ Sale Order Details de ayer/hoy: {details_today}")

db.close()
PYEOF
