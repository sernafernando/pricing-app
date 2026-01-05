#!/bin/bash

# Script para testear Turbo Routing con curl
# Usar tu token JWT

TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJmc2VybmEiLCJyb2wiOiJTVVBFUkFETUlOIiwiZXhwIjoxNzY3NzE5NjE5fQ.4ukvizog7HIAs0-F3NYqpxUpZ63tYV9a-czI2WNY05M"
API_URL="https://pricing.gaussonline.com.ar"

echo "===== TEST 1: Estadísticas ====="
curl -X GET "${API_URL}/api/turbo/estadisticas" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json"
echo -e "\n\n"

echo "===== TEST 2: Crear Motoquero ====="
curl -X POST "${API_URL}/api/turbo/motoqueros" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "nombre": "Carlos Test",
    "telefono": "+5491112345678",
    "activo": true,
    "zona_preferida_id": null
  }'
echo -e "\n\n"

echo "===== TEST 3: Listar Motoqueros ====="
curl -X GET "${API_URL}/api/turbo/motoqueros" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json"
echo -e "\n\n"

echo "===== TEST 4: Crear Zona ====="
curl -X POST "${API_URL}/api/turbo/zonas" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "nombre": "Palermo Test",
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
  }'
echo -e "\n\n"

echo "===== TEST 5: Listar Zonas ====="
curl -X GET "${API_URL}/api/turbo/zonas" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json"
echo -e "\n\n"

echo "===== TEST 6: Envíos Pendientes ====="
curl -X GET "${API_URL}/api/turbo/envios/pendientes?limit=3" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json"
echo -e "\n\n"
