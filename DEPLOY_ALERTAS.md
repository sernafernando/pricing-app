# Deployment: Sistema de Alertas

Este documento explica cómo deployar el sistema de alertas en el servidor de producción.

---

## 📋 Checklist Pre-Deploy

Antes de deployar, asegurate que estos archivos estén en el repo:

### Backend
- `backend/app/models/alerta.py` - Modelos SQLAlchemy
- `backend/app/schemas/alerta.py` - Schemas Pydantic
- `backend/app/services/alertas_service.py` - Lógica de negocio
- `backend/app/routers/alertas.py` - Router API
- `backend/alembic/versions/20260202_sistema_alertas_completo.py` - Migración
- `backend/app/models/permiso.py` - Actualizado con categoría ALERTAS
- `backend/app/main.py` - Router de alertas registrado

### Frontend
- `frontend/src/pages/GestionAlertas.jsx` - Página de gestión
- `frontend/src/pages/GestionAlertas.module.css` - Estilos
- `frontend/src/components/ModalAlertaForm.jsx` - Modal crear/editar
- `frontend/src/components/ModalAlertaForm.module.css` - Estilos
- `frontend/src/components/AppLayout.jsx` - Fetch alertas activas
- `frontend/src/components/AlertBanner.jsx` - Actualizado con onDismiss
- `frontend/src/components/Sidebar.jsx` - Link a gestión de alertas
- `frontend/src/App.jsx` - Ruta /gestion/alertas

---

## 🚀 Pasos de Deployment

### 1. Pull del código en el servidor

```bash
cd /var/www/html/pricing-app
git pull origin main  # o la rama que uses
```

### 2. Backend - Ejecutar migración de Alembic

```bash
cd backend
source venv/bin/activate
alembic upgrade head
```

Esto va a:
- Crear el enum `alertavariant` (info, warning, success, error)
- Crear 4 tablas: `alertas`, `alertas_usuarios_destinatarios`, `alertas_usuarios_estado`, `configuracion_alertas`
- Agregar el valor 'alertas' al enum `categoriapermiso`
- Insertar 2 permisos: `alertas.gestionar` y `alertas.configurar`
- Insertar configuración por defecto (max_alertas_visibles = 1)

### 3. Backend - Reiniciar el servicio

```bash
sudo systemctl restart pricing-api  # o el nombre de tu servicio
```

### 4. Frontend - Build y deploy

```bash
cd ../frontend
npm install  # si hay nuevas dependencias (en este caso no)
npm run build
```

Si usás nginx/apache, el build ya va a quedar en `dist/`.

### 5. Verificar que funcionó

#### Verificar migración
```bash
cd backend
source venv/bin/activate
alembic current
```

Debería mostrar: `20260202_alertas_v2 (head)`

#### Verificar permisos en DB
```sql
SELECT * FROM permisos WHERE codigo LIKE 'alertas.%';
```

Debería devolver 2 filas:
- `alertas.gestionar`
- `alertas.configurar`

#### Verificar tablas
```sql
\dt alertas*
```

Debería mostrar:
- `alertas`
- `alertas_usuarios_destinatarios`
- `alertas_usuarios_estado`

#### Verificar configuración
```sql
SELECT * FROM configuracion_alertas;
```

Debería devolver 1 fila con `id=1` y `max_alertas_visibles=1`.

---

## 🔐 Asignar Permisos a Usuarios

Por defecto, **SUPERADMIN** y **ADMIN** tienen los permisos de alertas.

Si querés dárselos a un usuario específico:

```sql
-- Obtener ID del permiso
SELECT id FROM permisos WHERE codigo = 'alertas.gestionar';  -- Ej: 101

-- Obtener ID del usuario
SELECT id FROM usuarios WHERE email = 'usuario@example.com';  -- Ej: 5

-- Agregar permiso al usuario
INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido)
VALUES (5, 101, true);
```

---

## ✅ Testing Post-Deploy

### 1. Crear una alerta de prueba

- Loguearte con SUPERADMIN o ADMIN
- Ir a `/gestion/alertas`
- Click en "+ Nueva Alerta"
- Completar:
  - **Título**: "Alerta de prueba"
  - **Mensaje**: "Esta es una prueba del sistema de alertas"
  - **Variant**: warning
  - **Roles destinatarios**: Seleccionar "* Todos los usuarios"
  - **Activo**: ✓ (marcar como activo)
  - **Prioridad**: 10
- Click "Crear"

### 2. Verificar que aparece

- Refresh la página
- Debería aparecer un banner naranja arriba del contenido con el mensaje
- Al hacer click en la ✕ debería cerrarse
- Si refrescás la página, NO debería aparecer de vuelta (porque la cerraste)

### 3. Limpiar

- Volver a `/gestion/alertas`
- Click en "✗ Inactiva" para desactivar la alerta
- O eliminarla con el botón ✕

---

## 🐛 Troubleshooting

### Error: "Can't locate revision 0b899b78ef87"

El `down_revision` en la migración no coincide con el head actual del servidor.

**Solución**:
```bash
# Ver cuál es el head actual
alembic current

# Editar el archivo de migración
nano backend/alembic/versions/20260202_sistema_alertas_completo.py

# Cambiar la línea:
# down_revision: Union[str, None] = '0b899b78ef87'
# Por el revision_id que te mostró alembic current

# Guardar y correr upgrade de nuevo
alembic upgrade head
```

### Error: "relation 'alertas' already exists"

Las tablas ya existen (probablemente las creaste manualmente).

**Solución 1 - Marcar migración como aplicada**:
```bash
alembic stamp 20260202_alertas_v2
```

**Solución 2 - Eliminar tablas y recrear**:
```sql
DROP TABLE IF EXISTS alertas_usuarios_estado CASCADE;
DROP TABLE IF EXISTS alertas_usuarios_destinatarios CASCADE;
DROP TABLE IF EXISTS alertas CASCADE;
DROP TABLE IF EXISTS configuracion_alertas CASCADE;
DROP TYPE IF EXISTS alertavariant;
```
Después correr `alembic upgrade head` de nuevo.

### Error: "column categoria is of type categoriapermiso but expression is of type character varying"

El enum `categoriapermiso` no tiene el valor 'alertas'.

**Solución**:
```sql
ALTER TYPE categoriapermiso ADD VALUE IF NOT EXISTS 'alertas';
```

---

## 📝 Notas Adicionales

- Las alertas cerradas por un usuario quedan trackeadas en `alertas_usuarios_estado`
- Si una alerta tiene `persistent=true`, se muestra SIEMPRE aunque el usuario la cierre
- El límite de alertas visibles se puede cambiar desde el endpoint `/api/alertas/configuracion/global` (requiere permiso `alertas.configurar`)
- Los usuarios específicos se pueden asignar además de los roles en el modal de creación

---

**¿Alguna duda? Revisá los logs del backend y el console del navegador.**
