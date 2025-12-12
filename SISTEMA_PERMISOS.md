# Sistema de Permisos Híbrido - Pricing App

## Fecha de implementación: 2025-12-11

## Arquitectura

Sistema híbrido que combina:
- **Permisos base por rol**: Cada rol tiene un conjunto de permisos por defecto
- **Overrides por usuario**: Se pueden agregar o quitar permisos específicos a usuarios individuales

## Tablas de Base de Datos

### 1. `permisos` - Catálogo de permisos
```sql
CREATE TABLE permisos (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(100) UNIQUE NOT NULL,
    nombre VARCHAR(255) NOT NULL,
    descripcion TEXT,
    categoria VARCHAR(50) NOT NULL,
    orden INTEGER DEFAULT 0,
    es_critico BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 2. `roles_permisos_base` - Permisos por defecto de cada rol
```sql
CREATE TABLE roles_permisos_base (
    id SERIAL PRIMARY KEY,
    rol VARCHAR(50) NOT NULL,
    permiso_id INTEGER REFERENCES permisos(id) ON DELETE CASCADE NOT NULL,
    UNIQUE(rol, permiso_id)
);
```

### 3. `usuarios_permisos_override` - Overrides por usuario
```sql
CREATE TABLE usuarios_permisos_override (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE NOT NULL,
    permiso_id INTEGER REFERENCES permisos(id) ON DELETE CASCADE NOT NULL,
    concedido BOOLEAN NOT NULL,  -- TRUE = agregar, FALSE = quitar
    otorgado_por_id INTEGER REFERENCES usuarios(id),
    motivo TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(usuario_id, permiso_id)
);
```

## Categorías de Permisos

| Categoría | Prefijo | Descripción |
|-----------|---------|-------------|
| productos | `productos.*` | Gestión de productos y precios |
| ventas_ml | `ventas_ml.*` | Dashboard y operaciones MercadoLibre |
| ventas_fuera | `ventas_fuera.*` | Ventas por fuera de ML |
| ventas_tn | `ventas_tn.*` | Ventas Tienda Nube |
| reportes | `reportes.*` | Auditoría, notificaciones, calculadora |
| administracion | `admin.*` | Panel admin, usuarios, permisos |
| configuracion | `config.*` | Comisiones, constantes, tipo cambio |

## Permisos Disponibles

### Productos
- `productos.ver` - Ver productos
- `productos.editar_precios` - Editar precios
- `productos.editar_rebate` - Gestionar Rebate
- `productos.editar_web_transferencia` - Gestionar Web Transferencia
- `productos.editar_out_of_cards` - Marcar Out of Cards
- `productos.banear` - Banear productos (CRÍTICO)
- `productos.exportar` - Exportar productos
- `productos.ver_costos` - Ver costos
- `productos.ver_auditoria` - Ver auditoría de productos

### Ventas ML
- `ventas_ml.ver_dashboard` - Ver dashboard ML
- `ventas_ml.ver_operaciones` - Ver operaciones ML
- `ventas_ml.ver_rentabilidad` - Ver rentabilidad ML
- `ventas_ml.ver_todas_marcas` - Ver todas las marcas ML

### Ventas Fuera ML
- `ventas_fuera.ver_dashboard` - Ver dashboard Fuera ML
- `ventas_fuera.ver_operaciones` - Ver operaciones Fuera ML
- `ventas_fuera.ver_rentabilidad` - Ver rentabilidad Fuera ML
- `ventas_fuera.editar_overrides` - Editar datos de ventas Fuera ML
- `ventas_fuera.editar_costos` - Editar costos Fuera ML
- `ventas_fuera.ver_admin` - Acceso admin Fuera ML

### Ventas Tienda Nube
- `ventas_tn.ver_dashboard` - Ver dashboard Tienda Nube
- `ventas_tn.ver_operaciones` - Ver operaciones Tienda Nube
- `ventas_tn.ver_rentabilidad` - Ver rentabilidad Tienda Nube
- `ventas_tn.editar_overrides` - Editar datos de ventas TN
- `ventas_tn.ver_admin` - Acceso admin Tienda Nube

### Reportes
- `reportes.ver_auditoria` - Ver auditoría general
- `reportes.ver_notificaciones` - Ver notificaciones
- `reportes.ver_calculadora` - Usar calculadora
- `reportes.exportar` - Exportar reportes

### Administración
- `admin.ver_panel` - Ver panel de administración
- `admin.gestionar_usuarios` - Gestionar usuarios (CRÍTICO)
- `admin.gestionar_permisos` - Gestionar permisos (CRÍTICO)
- `admin.gestionar_pms` - Gestionar Product Managers
- `admin.sincronizar` - Ejecutar sincronizaciones
- `admin.limpieza_masiva` - Limpieza masiva de datos (CRÍTICO)
- `admin.gestionar_banlist` - Gestionar banlist
- `admin.gestionar_mla_banlist` - Gestionar MLA banlist

### Configuración
- `config.ver_comisiones` - Ver comisiones
- `config.editar_comisiones` - Editar comisiones (CRÍTICO)
- `config.ver_constantes` - Ver constantes de pricing
- `config.editar_constantes` - Editar constantes de pricing (CRÍTICO)
- `config.ver_tipo_cambio` - Ver tipo de cambio

## Permisos por Rol (Por Defecto)

### SUPERADMIN
Todos los permisos.

### ADMIN
Todos los permisos.

### GERENTE
- Todos los permisos de visualización
- Sin permisos de edición de precios ni administración

### PRICING
- Visualización y edición de productos/precios
- Visualización de dashboards de ventas (sin rentabilidad fuera ML)
- Sin acceso a administración

### VENTAS
- Solo visualización básica de productos y dashboards
- Calculadora y notificaciones
- Sin edición de nada

## Archivos del Sistema

### Backend
- `backend/app/models/permiso.py` - Modelos SQLAlchemy
- `backend/app/services/permisos_service.py` - Lógica de verificación
- `backend/app/api/endpoints/permisos.py` - Endpoints API
- `backend/alembic/versions/create_permisos_system.py` - Migración

### Frontend
- `frontend/src/contexts/PermisosContext.jsx` - Context provider
- `frontend/src/hooks/usePermisos.js` - Hook alternativo
- `frontend/src/components/ProtectedRoute.jsx` - Protección de rutas
- `frontend/src/components/PanelPermisos.jsx` - Panel de administración

## API Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/permisos/catalogo` | Catálogo completo de permisos |
| GET | `/api/permisos/mis-permisos` | Permisos del usuario actual |
| GET | `/api/permisos/usuario/{id}` | Permisos detallados de un usuario |
| GET | `/api/permisos/usuario/{id}/overrides` | Solo overrides de un usuario |
| POST | `/api/permisos/override` | Crear/actualizar override |
| DELETE | `/api/permisos/override/{usuario_id}/{permiso_codigo}` | Eliminar override |
| GET | `/api/permisos/verificar/{codigo}` | Verificar si tengo un permiso |
| POST | `/api/permisos/verificar-multiples` | Verificar múltiples permisos |
| GET | `/api/permisos/roles/{rol}/permisos` | Permisos base de un rol |

## Uso en Frontend

### Verificar permiso en componente
```jsx
import { usePermisos } from '../contexts/PermisosContext';

function MiComponente() {
  const { tienePermiso, loading } = usePermisos();

  if (loading) return <Loading />;

  if (!tienePermiso('productos.editar_precios')) {
    return <SinAcceso />;
  }

  return <ContenidoProtegido />;
}
```

### Proteger ruta
```jsx
<Route path="/admin" element={
  <ProtectedRoute permiso="admin.ver_panel">
    <Admin />
  </ProtectedRoute>
} />
```

### Verificar múltiples permisos
```jsx
const { tieneAlgunPermiso, tieneTodosPermisos } = usePermisos();

// Al menos uno
if (tieneAlgunPermiso(['ventas_ml.ver_dashboard', 'ventas_fuera.ver_dashboard'])) {
  // mostrar algo
}

// Todos
if (tieneTodosPermisos(['productos.ver', 'productos.editar_precios'])) {
  // mostrar botón editar
}
```

## Uso en Backend

### Verificar permiso en endpoint
```python
from app.services.permisos_service import verificar_permiso

@router.get("/algo")
async def mi_endpoint(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if not verificar_permiso(db, current_user, 'productos.editar_precios'):
        raise HTTPException(status_code=403, detail="Sin permiso")

    # continuar...
```

## SQL para Crear Tablas Manualmente

Si la migración falla, ejecutar en psql:

```sql
-- Ver archivo completo en la respuesta anterior del chat
-- o en backend/alembic/versions/create_permisos_system.py
```

## Notas Importantes

1. **SUPERADMIN siempre tiene todos los permisos** - Hardcodeado en el servicio
2. **Los overrides tienen prioridad sobre el rol base**
3. **Un override con `concedido=false` quita un permiso que el rol tiene**
4. **Un override con `concedido=true` agrega un permiso que el rol no tiene**
5. **Al eliminar un override, el usuario vuelve al permiso base del rol**

## Troubleshooting

### Las tablas no se crearon
1. Verificar con `\dt permisos` en psql
2. Si no existe, crear manualmente con el SQL de arriba
3. Marcar migración como aplicada: `alembic stamp create_permisos_system`

### Error "No module named 'app.core.auth'"
El import correcto es:
```python
from app.api.deps import get_current_user
```

### Ciclos en migraciones de Alembic
Ver el orden correcto de `down_revision` en cada archivo de migración.
La cadena debe ser lineal sin ciclos.
