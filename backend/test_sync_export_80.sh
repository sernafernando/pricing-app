#!/bin/bash
# Test script for sync export 80 endpoint

echo "==================================="
echo "TESTING SYNC EXPORT 80 ENDPOINT"
echo "==================================="
echo ""

echo "📡 Calling POST /api/pedidos-export/sincronizar-export-80..."
echo ""

curl -X POST "http://localhost:8002/api/pedidos-export/sincronizar-export-80" \
  -H "Content-Type: application/json" \
  -w "\n\nHTTP Status: %{http_code}\n" \
  2>/dev/null | jq '.'

echo ""
echo "==================================="
echo "VERIFICATION QUERIES"
echo "==================================="
echo ""

echo "1️⃣ Checking ws_internalid population for TN orders..."
psql $DATABASE_URL -c "
SELECT 
  soh_id, 
  user_id,
  ws_internalid, 
  tiendanube_number,
  export_id,
  export_activo
FROM tb_sale_order_header
WHERE user_id = 50021 
  AND export_id = 80 
  AND export_activo = true
ORDER BY soh_id DESC
LIMIT 10;
" 2>&1

echo ""
echo "2️⃣ Checking TN enrichment (tiendanube_number, shipping data)..."
psql $DATABASE_URL -c "
SELECT 
  soh_id,
  ws_internalid,
  tiendanube_number,
  tiendanube_shipping_city,
  tiendanube_shipping_province,
  LEFT(tiendanube_shipping_address, 50) as address_preview
FROM tb_sale_order_header
WHERE user_id = 50021 
  AND export_id = 80 
  AND tiendanube_number IS NOT NULL
LIMIT 5;
" 2>&1

echo ""
echo "3️⃣ Summary stats..."
psql $DATABASE_URL -c "
SELECT 
  COUNT(*) FILTER (WHERE ws_internalid IS NOT NULL) as con_ws_internalid,
  COUNT(*) FILTER (WHERE tiendanube_number IS NOT NULL) as con_tn_number_enriquecido,
  COUNT(*) as total_tn_export_80
FROM tb_sale_order_header
WHERE user_id = 50021 
  AND export_id = 80 
  AND export_activo = true;
" 2>&1

echo ""
echo "✅ Test completed!"
