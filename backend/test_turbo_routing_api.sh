#!/bin/bash

# Script para testear los endpoints de Turbo Routing
# Ejecutar: chmod +x test_turbo_routing_api.sh && ./test_turbo_routing_api.sh

# Colores para output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuración
API_URL="${API_URL:-http://localhost:8000}"
TOKEN="${TOKEN:-}"

# Si no hay token, pedirlo
if [ -z "$TOKEN" ]; then
    echo -e "${YELLOW}No se encontró TOKEN en variable de entorno.${NC}"
    echo "Para obtener el token:"
    echo "1. Ir a ${API_URL}/api/docs"
    echo "2. Hacer login con POST /api/auth/login"
    echo "3. Copiar el token"
    echo ""
    read -p "Ingresá tu token JWT: " TOKEN
fi

# Headers
HEADERS="Authorization: Bearer $TOKEN"

echo -e "${GREEN}=================================================${NC}"
echo -e "${GREEN}  TEST: Turbo Routing API${NC}"
echo -e "${GREEN}=================================================${NC}"
echo ""

# Test 1: Verificar que el endpoint existe
echo -e "${YELLOW}[1/9] Verificando que el backend responde...${NC}"
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" "${API_URL}/health"
echo ""

# Test 2: Estadísticas generales
echo -e "${YELLOW}[2/9] GET /api/turbo/estadisticas${NC}"
curl -s -X GET "${API_URL}/api/turbo/estadisticas" \
  -H "$HEADERS" \
  -H "Content-Type: application/json" | jq '.'
echo ""
echo ""

# Test 3: Crear un motoquero
echo -e "${YELLOW}[3/9] POST /api/turbo/motoqueros (Crear motoquero)${NC}"
MOTOQUERO_RESPONSE=$(curl -s -X POST "${API_URL}/api/turbo/motoqueros" \
  -H "$HEADERS" \
  -H "Content-Type: application/json" \
  -d '{
    "nombre": "Carlos Rodríguez",
    "telefono": "+5491198765432",
    "activo": true,
    "zona_preferida_id": null
  }')
echo "$MOTOQUERO_RESPONSE" | jq '.'
MOTOQUERO_ID=$(echo "$MOTOQUERO_RESPONSE" | jq -r '.id')
echo -e "${GREEN}✓ Motoquero creado con ID: $MOTOQUERO_ID${NC}"
echo ""
echo ""

# Test 4: Listar motoqueros
echo -e "${YELLOW}[4/9] GET /api/turbo/motoqueros${NC}"
curl -s -X GET "${API_URL}/api/turbo/motoqueros" \
  -H "$HEADERS" | jq '.'
echo ""
echo ""

# Test 5: Crear una zona
echo -e "${YELLOW}[5/9] POST /api/turbo/zonas (Crear zona Palermo)${NC}"
ZONA_RESPONSE=$(curl -s -X POST "${API_URL}/api/turbo/zonas" \
  -H "$HEADERS" \
  -H "Content-Type: application/json" \
  -d '{
    "nombre": "Palermo",
    "poligono": {
      "type": "Polygon",
      "coordinates": [
        [
          [-58.4173, -34.5816],
          [-58.4173, -34.6016],
          [-58.3973, -34.6016],
          [-58.3973, -34.5816],
          [-58.4173, -34.5816]
        ]
      ]
    },
    "color": "#FF5733",
    "activa": true
  }')
echo "$ZONA_RESPONSE" | jq '.'
ZONA_ID=$(echo "$ZONA_RESPONSE" | jq -r '.id')
echo -e "${GREEN}✓ Zona creada con ID: $ZONA_ID${NC}"
echo ""
echo ""

# Test 6: Listar zonas
echo -e "${YELLOW}[6/9] GET /api/turbo/zonas${NC}"
curl -s -X GET "${API_URL}/api/turbo/zonas" \
  -H "$HEADERS" | jq '.'
echo ""
echo ""

# Test 7: Obtener envíos Turbo pendientes
echo -e "${YELLOW}[7/9] GET /api/turbo/envios/pendientes${NC}"
ENVIOS_RESPONSE=$(curl -s -X GET "${API_URL}/api/turbo/envios/pendientes?limit=5" \
  -H "$HEADERS")
echo "$ENVIOS_RESPONSE" | jq '.'
FIRST_SHIPPING_ID=$(echo "$ENVIOS_RESPONSE" | jq -r '.[0].mlshippingid // empty')
echo ""

if [ -n "$FIRST_SHIPPING_ID" ]; then
    echo -e "${GREEN}✓ Encontrados envíos Turbo. Primer mlshippingid: $FIRST_SHIPPING_ID${NC}"
    
    # Test 8: Asignar envío a motoquero
    echo ""
    echo -e "${YELLOW}[8/9] POST /api/turbo/asignacion/manual (Asignar envío)${NC}"
    curl -s -X POST "${API_URL}/api/turbo/asignacion/manual" \
      -H "$HEADERS" \
      -H "Content-Type: application/json" \
      -d "{
        \"mlshippingids\": [\"$FIRST_SHIPPING_ID\"],
        \"motoquero_id\": $MOTOQUERO_ID,
        \"zona_id\": $ZONA_ID,
        \"asignado_por\": \"manual\"
      }" | jq '.'
    echo ""
    echo -e "${GREEN}✓ Envío asignado correctamente${NC}"
else
    echo -e "${RED}✗ No se encontraron envíos Turbo pendientes para testear asignación${NC}"
    echo -e "${YELLOW}  Esto es normal si no hay pedidos Turbo en el sistema.${NC}"
fi
echo ""
echo ""

# Test 9: Resumen de asignaciones
echo -e "${YELLOW}[9/9] GET /api/turbo/asignaciones/resumen${NC}"
curl -s -X GET "${API_URL}/api/turbo/asignaciones/resumen" \
  -H "$HEADERS" | jq '.'
echo ""
echo ""

# Resumen final
echo -e "${GREEN}=================================================${NC}"
echo -e "${GREEN}  TESTS COMPLETADOS${NC}"
echo -e "${GREEN}=================================================${NC}"
echo ""
echo -e "Recursos creados:"
echo -e "  - Motoquero ID: ${GREEN}$MOTOQUERO_ID${NC}"
echo -e "  - Zona ID: ${GREEN}$ZONA_ID${NC}"
if [ -n "$FIRST_SHIPPING_ID" ]; then
    echo -e "  - Asignación creada para: ${GREEN}$FIRST_SHIPPING_ID${NC}"
fi
echo ""
echo -e "${YELLOW}Para ver la documentación interactiva:${NC}"
echo -e "  ${API_URL}/api/docs#tag/turbo-routing"
echo ""
echo -e "${YELLOW}Para limpiar los datos de testing:${NC}"
echo -e "  DELETE ${API_URL}/api/turbo/motoqueros/$MOTOQUERO_ID"
echo -e "  DELETE ${API_URL}/api/turbo/zonas/$ZONA_ID"
echo ""
