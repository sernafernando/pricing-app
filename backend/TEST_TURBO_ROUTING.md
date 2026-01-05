# 🧪 Testing Turbo Routing Backend

## ✅ Pre-requisitos

1. **Migración aplicada:**
   ```bash
   cd /mnt/kingston/sistema/dev/pricing-app/backend
   alembic upgrade head
   # O si usás venv:
   source venv/bin/activate && alembic upgrade head
   ```

2. **Permiso seeded en DB:**
   ```bash
   # Opción A: Si tenés acceso a psql directo
   psql -U tu_usuario -d pricing_db < seed_permiso_turbo.sql
   
   # Opción B: Copiar el SQL y ejecutarlo en pgAdmin o DBeaver
   # Ver contenido de: seed_permiso_turbo.sql
   ```

3. **Backend corriendo:**
   ```bash
   # Verificar que esté corriendo
   curl http://localhost:8000/health
   
   # Si no está corriendo, iniciarlo:
   uvicorn app.main:app --reload --port 8000
   ```

---

## 🚀 Opción 1: Testing con Python (RECOMENDADO)

### Instalación de requests (si no lo tenés)
```bash
pip install requests
```

### Ejecutar tests
```bash
cd /mnt/kingston/sistema/dev/pricing-app/backend
python test_turbo_simple.py
```

**Te va a pedir el token JWT:**
1. Ir a http://localhost:8000/api/docs
2. Expandir `POST /api/auth/login`
3. Click en "Try it out"
4. Ingresar tus credenciales
5. Copiar el `access_token` de la respuesta
6. Pegar en el script cuando te lo pida

**Output esperado:**
```
🚀 TESTING TURBO ROUTING API
   API URL: http://localhost:8000

============================================================
  📊 Estadísticas Generales
============================================================
Status: 200
{
  "total_envios_pendientes": 0,
  "total_envios_asignados": 0,
  "total_motoqueros_activos": 0,
  "total_zonas_activas": 0,
  "envios_por_motoquero": []
}

============================================================
  🏍️ Crear Motoquero
============================================================
Status: 201
{
  "id": 1,
  "nombre": "Carlos Test",
  "telefono": "+5491112345678",
  "activo": true,
  ...
}
```

---

## 🚀 Opción 2: Testing con Bash/curl

```bash
cd /mnt/kingston/sistema/dev/pricing-app/backend
./test_turbo_routing_api.sh
```

**Requisitos:**
- `curl` instalado
- `jq` instalado (para formatear JSON): `sudo apt install jq`

---

## 🚀 Opción 3: Testing con Swagger UI (Más fácil)

1. **Ir a la documentación interactiva:**
   ```
   http://localhost:8000/api/docs
   ```

2. **Autenticarse:**
   - Click en el botón "Authorize" (arriba a la derecha)
   - Hacer login con `POST /api/auth/login`
   - Copiar el `access_token`
   - Click en "Authorize" y pegar el token
   - Click en "Authorize" y luego "Close"

3. **Testear endpoints en orden:**

   **a) GET /api/turbo/estadisticas**
   - Expandir el endpoint
   - Click "Try it out"
   - Click "Execute"
   - Ver response

   **b) POST /api/turbo/motoqueros**
   - Expandir el endpoint
   - Click "Try it out"
   - Usar este JSON:
     ```json
     {
       "nombre": "Carlos Rodríguez",
       "telefono": "+5491198765432",
       "activo": true,
       "zona_preferida_id": null
     }
     ```
   - Click "Execute"
   - Copiar el `id` de la respuesta (ej: `1`)

   **c) GET /api/turbo/motoqueros**
   - Verificar que aparezca el motoquero creado

   **d) POST /api/turbo/zonas**
   - Usar este JSON:
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

   **e) GET /api/turbo/envios/pendientes**
   - Ver si hay envíos Turbo pendientes
   - Si no hay, es normal (no hay pedidos Turbo en el sistema)

   **f) POST /api/turbo/asignacion/manual** (solo si hay envíos)
   - Usar este JSON (reemplazar IDs):
     ```json
     {
       "mlshippingids": ["ID_DEL_ENVIO"],
       "motoquero_id": 1,
       "zona_id": 1,
       "asignado_por": "manual"
     }
     ```

   **g) GET /api/turbo/asignaciones/resumen**
   - Ver resumen de asignaciones por motoquero

---

## 🔍 Verificar en la Base de Datos

```sql
-- Verificar tablas creadas
\dt motoqueros
\dt zonas_reparto
\dt asignaciones_turbo
\dt geocoding_cache

-- Ver motoqueros
SELECT * FROM motoqueros;

-- Ver zonas
SELECT id, nombre, color, activa FROM zonas_reparto;

-- Ver asignaciones
SELECT id, mlshippingid, motoquero_id, estado FROM asignaciones_turbo;

-- Verificar permiso
SELECT * FROM permisos WHERE codigo = 'ordenes.gestionar_turbo_routing';

-- Ver qué roles tienen el permiso
SELECT p.codigo, p.nombre, r.rol
FROM permisos p
LEFT JOIN roles_permisos_base r ON r.permiso_id = p.id
WHERE p.codigo = 'ordenes.gestionar_turbo_routing';
```

---

## ❌ Troubleshooting

### Error 403: "Sin permiso para gestionar Turbo Routing"

**Causa:** Tu usuario no tiene el permiso asignado.

**Solución:**
```sql
-- Ver tu usuario y rol
SELECT id, username, rol FROM usuarios WHERE username = 'TU_USERNAME';

-- Si tu rol es PRICING, debería tener el permiso automáticamente
-- Si es otro rol, agregar override:
INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido, motivo)
SELECT 
    (SELECT id FROM usuarios WHERE username = 'TU_USERNAME'),
    (SELECT id FROM permisos WHERE codigo = 'ordenes.gestionar_turbo_routing'),
    true,
    'Testing Turbo Routing'
ON CONFLICT (usuario_id, permiso_id) DO NOTHING;
```

### Error 404: "Not Found"

**Causa:** El router no está registrado en `main.py`.

**Solución:** Verificar que existe esta línea en `backend/app/main.py`:
```python
app.include_router(turbo_routing.router, prefix="/api", tags=["turbo-routing"])
```

Si no existe, agregarla y reiniciar el backend.

### Error 500: "Internal Server Error"

**Causa:** Las tablas no existen en la DB.

**Solución:**
```bash
# Verificar migración
alembic current

# Si no está aplicada:
alembic upgrade head

# Verificar en psql que las tablas existen:
psql -d pricing_db -c "\dt motoqueros"
```

---

## ✅ Checklist de Testing Exitoso

- [ ] `GET /api/turbo/estadisticas` → Status 200, retorna stats
- [ ] `POST /api/turbo/motoqueros` → Status 201, crea motoquero
- [ ] `GET /api/turbo/motoqueros` → Status 200, lista motoqueros
- [ ] `POST /api/turbo/zonas` → Status 201, crea zona
- [ ] `GET /api/turbo/zonas` → Status 200, lista zonas
- [ ] `GET /api/turbo/envios/pendientes` → Status 200 (puede ser array vacío si no hay pedidos Turbo)
- [ ] `POST /api/turbo/asignacion/manual` → Status 200 (si hay envíos)
- [ ] `GET /api/turbo/asignaciones/resumen` → Status 200

---

## 📖 Siguiente Paso

Una vez que el backend esté testeado y funcionando, seguimos con:
1. **Frontend**: Instalar dependencias de mapas
2. **Página TurboRouting.jsx**: Estructura base
3. **Tabla de envíos**: Con Tesla design system
4. **Formulario de asignación**: Sin mapa inicialmente

**¿Todo OK con el backend o hay algún error?**
