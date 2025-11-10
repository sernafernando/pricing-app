#!/bin/bash

# Script para ejecutar todas las sincronizaciones incrementales en orden
# Ejecutar desde el directorio backend

BACKEND_DIR="/var/www/html/pricing-app/backend"
LOG_DIR="/var/log/pricing-app"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

echo "============================================"
echo "🔄 Inicio sincronización completa: $TIMESTAMP"
echo "============================================"

cd $BACKEND_DIR || exit 1

# 1. Commercial Transactions
echo ""
echo "📊 [1/6] Sincronizando Commercial Transactions..."
python3 -m app.scripts.sync_commercial_transactions_incremental
if [ $? -eq 0 ]; then
    echo "✅ Commercial Transactions completado"
else
    echo "❌ Error en Commercial Transactions"
fi

# 2. Item Transactions
echo ""
echo "📦 [2/6] Sincronizando Item Transactions..."
python3 -m app.scripts.sync_item_transactions_incremental
if [ $? -eq 0 ]; then
    echo "✅ Item Transactions completado"
else
    echo "❌ Error en Item Transactions"
fi

# 3. Item Transaction Details
echo ""
echo "📋 [3/6] Sincronizando Item Transaction Details..."
python3 -m app.scripts.sync_item_transaction_details_incremental
if [ $? -eq 0 ]; then
    echo "✅ Item Transaction Details completado"
else
    echo "❌ Error en Item Transaction Details"
fi

# 4. ML Orders
echo ""
echo "🛒 [4/6] Sincronizando ML Orders..."
python3 -m app.scripts.sync_ml_orders_incremental
if [ $? -eq 0 ]; then
    echo "✅ ML Orders completado"
else
    echo "❌ Error en ML Orders"
fi

# 5. ML Orders Detail
echo ""
echo "📄 [5/6] Sincronizando ML Orders Detail..."
python3 -m app.scripts.sync_ml_orders_detail_incremental
if [ $? -eq 0 ]; then
    echo "✅ ML Orders Detail completado"
else
    echo "❌ Error en ML Orders Detail"
fi

# 6. ML Orders Shipping
echo ""
echo "🚚 [6/6] Sincronizando ML Orders Shipping..."
python3 -m app.scripts.sync_ml_orders_shipping_incremental
if [ $? -eq 0 ]; then
    echo "✅ ML Orders Shipping completado"
else
    echo "❌ Error en ML Orders Shipping"
fi

TIMESTAMP_END=$(date +"%Y-%m-%d %H:%M:%S")
echo ""
echo "============================================"
echo "✨ Sincronización completa finalizada: $TIMESTAMP_END"
echo "============================================"
