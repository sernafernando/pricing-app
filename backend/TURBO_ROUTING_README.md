# 🏍️ Turbo Routing - Sistema de Asignación de Envíos

Sistema de routing para envíos Turbo de MercadoLibre con asignación manual/automática, zonas geográficas y optimización de rutas.

## 📋 Requisitos

- Python 3.8+
- PostgreSQL 12+
- FastAPI (ya instalado)
- SQLAlchemy (ya instalado)

### Dependencias adicionales (backend)

```bash
cd backend
pip install shapely geopy geoalchemy2 scikit-learn
```

### Dependencias frontend

```bash
cd frontend
npm install leaflet react-leaflet leaflet-draw @turf/turf
```

---

## 🚀 Instalación

### 1. Aplicar migración de base de datos

La migración crea 4 tablas nuevas:
- `motoqueros` - Repartidores
- `zonas_reparto` - Polígonos de zonas CABA
- `asignaciones_turbo` - Asignación de envíos
- `geocoding_cache` - Cache de direcciones geocodificadas

**Opción A: Con Alembic (recomendado en desarrollo)**
```bash
cd backend
# La migración ya está creada en: alembic/versions/20250105_turbo_routing_01.py
# Solo aplicarla:
alembic upgrade head
```

**Opción B: SQL directo (recomendado en producción)**
```bash
# Conectarse a PostgreSQL
psql -U pricing_user -d pricing_db

# Ejecutar migración manualmente
\i backend/alembic/versions/20250105_turbo_routing_01.py
# (copiar el contenido del método upgrade() y ejecutarlo)
```

### 2. Seedear permiso

```bash
psql -U pricing_user -d pricing_db < backend/seed_permiso_turbo.sql
```

Esto crea el permiso `ordenes.gestionar_turbo_routing` y lo asigna al rol **PRICING**.

### 3. Reiniciar backend

```bash
# En desarrollo
uvicorn app.main:app --reload

# En producción (con systemd/supervisor según tu setup)
sudo systemctl restart pricing-api
```

---

## 📚 API Endpoints

### Envíos Turbo

#### `GET /api/turbo/envios/pendientes`
Obtiene envíos Turbo pendientes de asignación.

**Query params:**
- `incluir_asignados` (bool): Incluir envíos ya asignados (default: false)
- `limit` (int): Límite de resultados (default: 200, max: 500)
- `offset` (int): Offset para paginación (default: 0)

**Response:**
```json
[
  {
    "mlshippingid": "123456789",
    "mlo_id": 987654,
    "direccion_completa": "Av. Corrientes 1234, CP 1043, CABA",
    "mlstreet_name": "Av. Corrientes",
    "mlstreet_number": "1234",
    "mlzip_code": "1043",
    "mlcity_name": "CABA",
    "mlstate_name": "Capital Federal",
    "mlreceiver_name": "Juan Pérez",
    "mlreceiver_phone": "+5491123456789",
    "mlestimated_delivery_limit": "2025-01-05T18:00:00-03:00",
    "mlstatus": "ready_to_ship",
    "asignado": false,
    "motoquero_id": null,
    "motoquero_nombre": null
  }
]
```

---

### Motoqueros

#### `GET /api/turbo/motoqueros`
Lista de motoqueros.

#### `POST /api/turbo/motoqueros`
Crear motoquero.

**Body:**
```json
{
  "nombre": "Carlos Rodríguez",
  "telefono": "+5491198765432",
  "activo": true,
  "zona_preferida_id": null
}
```

#### `PUT /api/turbo/motoqueros/{id}`
Actualizar motoquero.

#### `DELETE /api/turbo/motoqueros/{id}`
Desactivar motoquero (soft delete).

---

### Zonas de Reparto

#### `GET /api/turbo/zonas`
Lista de zonas.

#### `POST /api/turbo/zonas`
Crear zona con polígono GeoJSON.

**Body:**
```json
{
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
}
```

#### `DELETE /api/turbo/zonas/{id}`
Desactivar zona.

---

### Asignaciones

#### `POST /api/turbo/asignacion/manual`
Asignar envíos a un motoquero.

**Body:**
```json
{
  "mlshippingids": ["123456789", "987654321"],
  "motoquero_id": 1,
  "zona_id": 2,
  "asignado_por": "manual"
}
```

#### `GET /api/turbo/asignaciones/resumen`
Resumen de asignaciones por motoquero.

**Response:**
```json
[
  {
    "motoquero_id": 1,
    "nombre": "Carlos Rodríguez",
    "total_envios": 5,
    "pendientes": 3
  }
]
```

---

### Estadísticas

#### `GET /api/turbo/estadisticas`
Estadísticas generales del sistema.

**Response:**
```json
{
  "total_envios_pendientes": 15,
  "total_envios_asignados": 10,
  "total_motoqueros_activos": 3,
  "total_zonas_activas": 4,
  "envios_por_motoquero": [
    {"motoquero": "Carlos Rodríguez", "total": 5},
    {"motoquero": "María López", "total": 3},
    {"motoquero": "Pedro González", "total": 2}
  ]
}
```

---

## 🔐 Permisos

**Permiso requerido:** `ordenes.gestionar_turbo_routing`

**Roles con acceso:**
- SUPERADMIN ✅ (todos los permisos)
- ADMIN ✅ (todos los permisos)
- PRICING ✅ (asignado por default)
- GERENTE ❌ (no tiene acceso)
- VENTAS ❌ (no tiene acceso)

---

## 📦 Modelos

### Motoquero
```python
class Motoquero(Base):
    id: int
    nombre: str (max 100)
    telefono: str (max 20) | None
    activo: bool
    zona_preferida_id: int | None
    created_at: datetime
    updated_at: datetime
```

### ZonaReparto
```python
class ZonaReparto(Base):
    id: int
    nombre: str (max 100)
    poligono: JSONB  # GeoJSON Polygon
    color: str (hex, ej: #FF5733)
    activa: bool
    creado_por: int | None
    created_at: datetime
    updated_at: datetime
```

### AsignacionTurbo
```python
class AsignacionTurbo(Base):
    id: int
    mlshippingid: str (FK a tb_mercadolibre_orders_shipping)
    motoquero_id: int (FK)
    zona_id: int | None (FK)
    direccion: str (max 500)
    latitud: Decimal(10, 8) | None
    longitud: Decimal(11, 8) | None
    orden_ruta: int | None
    estado: str  # 'pendiente', 'en_camino', 'entregado', 'cancelado'
    asignado_por: str | None  # 'manual' o 'automatico'
    asignado_at: datetime
    entregado_at: datetime | None
    notas: Text | None
```

### GeocodingCache
```python
class GeocodingCache(Base):
    direccion_hash: str (MD5, 32 chars) [PK]
    direccion_normalizada: str (max 500)
    latitud: Decimal(10, 8)
    longitud: Decimal(11, 8)
    provider: str (max 20) | None
    created_at: datetime
```

---

## 🛠️ Próximos pasos (Roadmap)

### Fase 1: MVP ✅ (COMPLETADA)
- [x] Migración de tablas
- [x] Modelos SQLAlchemy
- [x] Endpoints básicos (CRUD motoqueros, zonas, asignaciones)
- [x] Sistema de permisos

### Fase 2: Frontend básico (EN PROGRESO)
- [ ] Página TurboRouting.jsx
- [ ] Tabla de envíos pendientes
- [ ] Formulario de asignación manual
- [ ] Panel de motoqueros

### Fase 3: Mapa (PENDIENTE)
- [ ] Integrar Leaflet
- [ ] Mostrar pines de envíos
- [ ] Geocoding con cache
- [ ] Editor de zonas con Leaflet.draw

### Fase 4: Asignación automática (PENDIENTE)
- [ ] Algoritmo K-Means para generar zonas
- [ ] Point-in-polygon matching
- [ ] Asignación automática por zonas

### Fase 5: Optimización de rutas (PENDIENTE)
- [ ] Integrar OSRM
- [ ] Calcular ruta óptima por motoquero
- [ ] Exportar a Google Maps

---

## 🐛 Troubleshooting

### Error: "Tabla motoqueros no existe"
La migración no se aplicó. Ejecutar:
```bash
cd backend
alembic upgrade head
```

### Error: "Sin permiso para gestionar Turbo Routing"
Ejecutar el seed:
```bash
psql -U pricing_user -d pricing_db < backend/seed_permiso_turbo.sql
```

Luego verificar en la DB:
```sql
SELECT * FROM permisos WHERE codigo = 'ordenes.gestionar_turbo_routing';
```

### Error: "Module turbo_routing not found"
El router no está registrado en `main.py`. Verificar que la línea existe:
```python
app.include_router(turbo_routing.router, prefix="/api", tags=["turbo-routing"])
```

---

## 📖 Referencias

- **Leaflet**: https://leafletjs.com/
- **Leaflet.draw**: https://github.com/Leaflet/Leaflet.draw
- **OSRM**: http://project-osrm.org/
- **Nominatim**: https://nominatim.org/
- **Shapely** (geometría): https://shapely.readthedocs.io/

---

## 👤 Autor

Sistema desarrollado para Gauss Online - Pricing App
Fecha de implementación: 2025-01-05
