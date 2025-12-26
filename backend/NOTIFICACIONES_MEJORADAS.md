# Sistema de Notificaciones Mejorado

## 🎯 Mejoras Implementadas

### 1. Sistema de Severidad/Prioridad

Las notificaciones ahora tienen **4 niveles de severidad**:

- **INFO** 🟢 - Informativa, normal
- **WARNING** 🟡 - Advertencia, requiere atención
- **CRITICAL** 🟠 - Crítica, requiere acción inmediata
- **URGENT** 🔴 - Urgente, impacto alto en negocio

#### Cálculo Automático de Severidad

Para notificaciones de **markup**, la severidad se calcula automáticamente basándose en la diferencia porcentual respecto al objetivo:

- **>25% diferencia** → `URGENT` 🔴
- **15-25% diferencia** → `CRITICAL` 🟠
- **10-15% diferencia** → `WARNING` 🟡
- **<10% diferencia** → `INFO` 🟢

**Ejemplo:**
```python
# Markup objetivo: 30%
# Markup real: 12% → diferencia: -18% (60% menos)

# Resultado: URGENT 🔴
```

Los umbrales son **configurables**:
```python
from app.services.notificacion_service import NotificacionService

service = NotificacionService(db)
service.configurar_umbrales(
    warning=10.0,   # Default
    critical=15.0,  # Default  
    urgent=25.0     # Default
)
```

---

### 2. Sistema de Estados de Gestión

Las notificaciones tienen un **ciclo de vida** con 5 estados:

1. **PENDIENTE** - Creada, esperando revisión
2. **REVISADA** - Revisada por el usuario
3. **EN_GESTION** - Se está trabajando en resolverla
4. **DESCARTADA** - Descartada, **no volver a mostrar**
5. **RESUELTA** - Problema solucionado

#### Flujo de Gestión

```
PENDIENTE → REVISADA → EN_GESTION → RESUELTA
    ↓
DESCARTADA (no volver a avisar)
```

---

### 3. Nuevos Campos

#### En el Modelo

```python
class Notificacion:
    # Sistema de prioridad
    severidad: SeveridadNotificacion  # info, warning, critical, urgent
    estado: EstadoNotificacion        # pendiente, revisada, descartada, etc
    
    # Fechas de gestión
    fecha_revision: DateTime
    fecha_descarte: DateTime
    fecha_resolucion: DateTime
    
    # Notas del usuario
    notas_revision: Text
    
    # Properties calculados
    @property
    def diferencia_markup() -> float
    
    @property
    def diferencia_markup_porcentual() -> float
    
    @property
    def es_critica() -> bool
    
    @property
    def requiere_atencion() -> bool
```

---

### 4. Nuevos Endpoints API

#### Listar con Filtros Avanzados

```http
GET /api/notificaciones?solo_criticas=true&solo_pendientes=true
GET /api/notificaciones?severidad=critical
GET /api/notificaciones?estado=pendiente
```

**Query params:**
- `solo_no_leidas` - Solo no leídas
- `tipo` - Filtrar por tipo
- `severidad` - Filtrar por severidad (info, warning, critical, urgent)
- `estado` - Filtrar por estado
- `solo_criticas` - Solo critical + urgent
- `solo_pendientes` - Solo pendiente + en_gestion

**Ordenamiento:** Primero por severidad (urgent primero), luego por fecha.

#### Gestionar Estados

```http
# Cambiar estado genérico
PATCH /api/notificaciones/{id}/estado
Body: { "estado": "revisada", "notas": "Verificado, precio actualizado" }

# Atajos
PATCH /api/notificaciones/{id}/revisar
PATCH /api/notificaciones/{id}/descartar
PATCH /api/notificaciones/{id}/resolver

# Bulk operations
POST /api/notificaciones/bulk-descartar
Body: { "notificaciones_ids": [1, 2, 3], "notas": "Descartadas en bulk" }
```

#### Dashboard de Métricas

```http
GET /api/notificaciones/dashboard
```

**Respuesta:**
```json
{
  "total": 150,
  "por_estado": {
    "pendiente": 45,
    "revisada": 20,
    "descartada": 60,
    "en_gestion": 15,
    "resuelta": 10
  },
  "por_severidad": {
    "info": 30,
    "warning": 20,
    "critical": 8,
    "urgent": 2
  },
  "criticas_pendientes": 10,
  "no_leidas": 25,
  "requieren_atencion": 60
}
```

---

### 5. Servicio de Notificaciones

**`NotificacionService`** - Servicio para crear notificaciones con severidad automática.

```python
from app.services.notificacion_service import NotificacionService

service = NotificacionService(db)

# Crear notificación con severidad automática
notif = service.crear_notificacion(
    user_id=5,
    tipo="markup_bajo",
    mensaje="Markup bajo en venta ML",
    item_id=12345,
    markup_real=12.5,
    markup_objetivo=30.0,
    # ... otros campos
)

# severidad se calcula automáticamente:
# 12.5 vs 30.0 = -58% → URGENT 🔴
```

#### Métodos Disponibles

```python
# Calcular severidad manualmente
severidad = service.calcular_severidad(
    tipo="markup_bajo",
    markup_real=15.0,
    markup_objetivo=30.0
)

# Verificar si existe notificación similar (evitar spam)
existe = service.existe_notificacion_similar(
    user_id=5,
    tipo="markup_bajo",
    item_id=12345,
    tolerancia_horas=24
)

# Configurar umbrales personalizados
service.configurar_umbrales(
    warning=12.0,
    critical=18.0,
    urgent=30.0
)
```

---

## 🚀 Migración

### Ejecutar Migración

```bash
alembic upgrade head
```

La migración:
- ✅ Crea los ENUMs de severidad y estado
- ✅ Agrega las nuevas columnas
- ✅ Crea índices para performance
- ✅ **Calcula severidad automáticamente** para notificaciones existentes basándose en markup

**Lógica de migración automática:**
```sql
-- Si markup difiere >15%, marcar como critical
UPDATE notificaciones
SET severidad = 'critical'
WHERE ABS((markup_real - markup_objetivo) / markup_objetivo * 100) > 15

-- Si markup difiere 10-15%, marcar como warning
UPDATE notificaciones
SET severidad = 'warning'
WHERE ABS((markup_real - markup_objetivo) / markup_objetivo * 100) BETWEEN 10 AND 15
```

---

## 📊 Uso en Frontend

### Listar Notificaciones Críticas Pendientes

```javascript
const response = await fetch('/api/notificaciones?solo_criticas=true&solo_pendientes=true');
const notificaciones = await response.json();

// Mostrar con indicador visual según severidad
notificaciones.forEach(notif => {
  const icono = {
    'urgent': '🔴',
    'critical': '🟠',
    'warning': '🟡',
    'info': '🟢'
  }[notif.severidad];
  
  console.log(`${icono} ${notif.mensaje}`);
});
```

### Descartar Notificación

```javascript
await fetch(`/api/notificaciones/${notifId}/descartar`, {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    notas: 'Verificado - precio actualizado manualmente'
  })
});

// Ahora esta notificación NO aparecerá en el filtro de pendientes
```

### Dashboard de Métricas

```javascript
const dashboard = await fetch('/api/notificaciones/dashboard').then(r => r.json());

// Mostrar badge con críticas pendientes
document.querySelector('.badge-criticas').textContent = dashboard.criticas_pendientes;

// Mostrar gráfico de estados
renderChart(dashboard.por_estado);
```

---

## 🎨 Sugerencias de UI

### Indicadores Visuales

```css
/* Colores por severidad */
.notif-urgent { 
  background: #fee2e2; 
  border-left: 4px solid #dc2626; 
}

.notif-critical { 
  background: #fed7aa; 
  border-left: 4px solid #ea580c; 
}

.notif-warning { 
  background: #fef3c7; 
  border-left: 4px solid #f59e0b; 
}

.notif-info { 
  background: #f0f9ff; 
  border-left: 4px solid #0284c7; 
}
```

### Acciones Rápidas

```jsx
<NotificacionCard notif={notif}>
  <div className="actions">
    <button onClick={() => revisar(notif.id)}>✓ Revisar</button>
    <button onClick={() => descartar(notif.id)}>✕ Descartar</button>
    <button onClick={() => resolver(notif.id)}>✓ Resolver</button>
  </div>
</NotificacionCard>
```

### Filtros

```jsx
<Filters>
  <Toggle label="Solo críticas" onChange={setCriticas} />
  <Toggle label="Solo pendientes" onChange={setPendientes} />
  <Select 
    label="Severidad" 
    options={['info', 'warning', 'critical', 'urgent']} 
  />
  <Select 
    label="Estado" 
    options={['pendiente', 'revisada', 'descartada', 'en_gestion', 'resuelta']} 
  />
</Filters>
```

---

## 🔧 Integración con Código Existente

### Actualizar Código que Crea Notificaciones

**ANTES:**
```python
notif = Notificacion(
    user_id=user_id,
    tipo="markup_bajo",
    mensaje="...",
    markup_real=markup_real,
    markup_objetivo=markup_objetivo
)
db.add(notif)
db.commit()
```

**AHORA (recomendado):**
```python
from app.services.notificacion_service import NotificacionService

service = NotificacionService(db)
notif = service.crear_notificacion(
    user_id=user_id,
    tipo="markup_bajo",
    mensaje="...",
    markup_real=markup_real,
    markup_objetivo=markup_objetivo
)
# severidad se calcula automáticamente
```

---

## 📈 Beneficios

✅ **Priorización clara** - Sabés qué atacar primero (urgentes y críticas)  
✅ **Menos ruido** - Descartá las que no importan y no vuelven a aparecer  
✅ **Métricas visuales** - Dashboard muestra qué requiere atención  
✅ **Gestión de flujo** - Estados claros del ciclo de vida  
✅ **Automático** - Severidad se calcula sola basándose en umbrales de negocio  
✅ **Configurable** - Umbrales ajustables según necesidad  
✅ **Performance** - Índices en severidad y estado para queries rápidas  

---

## 🔮 Próximas Mejoras

- [ ] Configuración de umbrales por usuario/rol
- [ ] Notificaciones push (WebSockets)
- [ ] Agrupación inteligente por severidad
- [ ] SLA tracking (tiempo en cada estado)
- [ ] Reportes de resolución
- [ ] Templates de notas según tipo
- [ ] Integración con sistema de tickets

---

**Made with 🔥 by Gentleman Programming**
