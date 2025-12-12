#!/bin/bash
# Script para sincronizar catalog status via API

# URL del backend
API_URL="http://localhost:8000"

# Token de autenticación (obtenerlo del localStorage o hacer login primero)
# Para obtener el token, primero hacé login:
# TOKEN=$(curl -s -X POST "$API_URL/api/auth/login" \
#   -H "Content-Type: application/json" \
#   -d '{"username":"tu_usuario","password":"tu_password"}' | jq -r '.access_token')

# O si ya tenés el token, ponerlo acá:
TOKEN="TU_TOKEN_AQUI"

# Sincronizar todos los items con catálogo
echo "Sincronizando catalog status..."
curl -X POST "$API_URL/api/ml-catalog/sync-catalog-status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"

echo ""
echo "Sincronización completada!"

# Para sincronizar un MLA específico:
# curl -X POST "$API_URL/api/ml-catalog/sync-catalog-status?mla_id=MLA123456789" \
#   -H "Authorization: Bearer $TOKEN"
