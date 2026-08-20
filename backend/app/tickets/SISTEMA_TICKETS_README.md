# Sistema de Tickets Configurable

Sistema moldeable de gestión de tickets que permite diferentes configuraciones por sector/área de la empresa.

## 🎯 Características Principales

- **Multi-sector**: Pricing, Soporte, Ventas, o cualquier sector custom
- **Workflows configurables**: Estados y transiciones específicas por sector
- **Asignación flexible**: Round Robin, Carga Balanceada, Skill-Based, Manual
- **Event-driven**: Desacoplado mediante Event Bus para extensibilidad
- **Campos dinámicos**: JSONB para metadata custom según tipo de ticket
- **Historial completo**: Auditoría de todos los cambios
- **State machine**: Transiciones validadas con permisos y callbacks

---

## 📁 Estructura del Código

```
backend/app/tickets/
├── models/                     # Modelos SQLAlchemy
│   ├── sector.py              # Sectores (Pricing, Soporte, etc.)
│   ├── workflow.py            # Workflows, Estados, Transiciones
│   ├── tipo_ticket.py         # Tipos de tickets por sector
│   ├── ticket.py              # Modelo principal de tickets
│   ├── asignacion_ticket.py   # Historial de asignaciones
│   ├── historial_ticket.py    # Historial de cambios
│   └── comentario_ticket.py   # Comentarios en tickets
│
├── schemas/                    # Schemas Pydantic para validación
│   ├── sector_schemas.py      # DTOs de sectores
│   ├── workflow_schemas.py    # DTOs de workflows
│   └── ticket_schemas.py      # DTOs de tickets
│
├── services/                   # Lógica de negocio
│   ├── workflow_service.py    # State machine y transiciones
│   └── asignacion_service.py  # Lógica de asignación
│
├── strategies/                 # Patrón Strategy
│   └── asignacion/
│       ├── base.py            # Base abstracta
│       ├── round_robin.py     # Asignación rotativa
│       ├── carga_balanceada.py # Por carga de trabajo
│       └── skill_based.py     # Por competencias/skills
│
├── events/                     # Event bus y handlers
│   ├── event_bus.py           # Event bus simple en memoria
│   └── handlers/              # Event handlers (TODO)
│
└── api/endpoints/             # Endpoints REST
    ├── tickets.py             # CRUD tickets
    ├── sectores.py            # Gestión de sectores
    └── workflows.py           # Gestión de workflows
```

---

## 🗄️ Modelo de Datos

### Tablas Principales

1. **tickets_sectores**: Sectores del sistema
2. **tickets_workflows**: Flujos de trabajo
3. **tickets_estados**: Estados de los workflows
4. **tickets_transiciones**: Transiciones permitidas entre estados
5. **tickets_tipos**: Tipos de tickets por sector
6. **tickets**: Tabla principal de tickets
7. **tickets_asignaciones**: Historial de asignaciones
8. **tickets_historial**: Historial de cambios
9. **tickets_comentarios**: Comentarios

### Relaciones Clave

```
Sector
  ├─► Workflows (1:N)
  ├─► TipoTickets (1:N)
  └─► Tickets (1:N)

Workflow
  ├─► Estados (1:N)
  ├─► Transiciones (1:N)
  └─► TipoTickets (1:N)

Ticket
  ├─► Estado (N:1)
  ├─► TipoTicket (N:1)
  ├─► Asignaciones (1:N)
  ├─► Historial (1:N)
  └─► Comentarios (1:N)
```

---

## 🚀 Uso Básico

### 1. Ejecutar Migración

```bash
cd backend
alembic upgrade head
```

### 2. Crear Datos Iniciales

```python
# TODO: Script de seed data
# Crear sectores: Pricing, Soporte, Ventas
# Crear workflows con estados y transiciones
# Crear tipos de tickets
```

### 3. Registrar Routers en FastAPI

```python
# En backend/app/main.py
from app.tickets.api.endpoints import tickets, sectores, workflows

app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
app.include_router(sectores.router, prefix="/api/sectores", tags=["sectores"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
```

### 4. Crear un Ticket

```python
POST / api / tickets
{
    "titulo": "Cambio de precio producto X",
    "descripcion": "Necesito bajar el precio por competencia",
    "prioridad": "alta",
    "sector_id": 1,  # Pricing
    "tipo_ticket_id": 5,  # Cambio de Precio
    "metadata": {
        "item_id": 12345,
        "precio_actual": 1500.00,
        "precio_solicitado": 1350.00,
        "motivo": "Competencia bajó 10%",
        "urgencia": "alta",
    },
}
```

### 5. Transicionar Estado

```python
POST / api / tickets / 123 / transicion
{
    "nuevo_estado_id": 3,  # Aprobado
    "comentario": "Aprobado, precio dentro del rango aceptable",
    "metadata": {"aprobado_por": "Juan Perez"},
}
```

### 6. Asignar Ticket

```python
POST / api / tickets / 123 / asignar
{"usuario_id": 5, "motivo": "Especialista en esta marca"}
```

---

## ⚙️ Configuración por Sector

Cada sector tiene un JSONB de configuración que controla:

### Asignación

```json
{
  "asignacion": {
    "tipo": "round_robin",  // round_robin | basado_en_carga | basado_en_skills | manual
    "auto_assign": true,
    "solo_con_permiso": "tickets.pricing.asignar",
    "skill_field": "marca_id",  // Para skill-based
    "fallback": "basado_en_carga"
  }
}
```

### Notificaciones

```json
{
  "notificaciones": {
    "on_create": ["email", "in_app"],
    "on_assign": ["in_app"],
    "on_estado_changed": ["email"],
    "on_comentario": ["in_app"],
    "on_close": ["email"],
    "webhook_url": "https://hooks.slack.com/...",
    "destinatarios_default": [1, 2, 3]
  }
}
```

### SLA

```json
{
  "sla": {
    "respuesta_horas": 4,
    "resolucion_horas": 24,
    "escalamiento_auto_horas": 48
  }
}
```

---

## 🔄 Workflows y Transiciones

### Ejemplo: Sector Pricing

**Workflow "Cambio de Precio":**

```
Solicitado → En Revisión → Aprobado → Aplicado
                ↓
            Rechazado
```

**Transición: En Revisión → Aprobado**
- Requiere permiso: `tickets.pricing.aprobar`
- Solo asignado: `true`
- Validaciones:
  - `precio_solicitado` dentro de rango
- Acciones:
  - Notificar al creador
  - Crear auditoría

**Transición: Aprobado → Aplicado**
- Requiere permiso: `productos.editar_precios`
- Acciones:
  - Ejecutar callback: `apply_price_change`
  - Crear registro en auditoría de precios
  - Marcar ticket como cerrado

---

## 📊 Event Bus

### Eventos Disponibles

- `ticket.created`: Al crear un ticket
- `ticket.assigned`: Al asignar a un usuario
- `ticket.reassigned`: Al reasignar
- `ticket.estado_changed`: Al cambiar de estado
- `ticket.comentado`: Al agregar comentario
- `ticket.closed`: Al cerrar
- `ticket.escalado`: Al escalar

### Subscribirse a Eventos

```python
from app.tickets.events import EventBus


def on_ticket_created(ticket, usuario):
    print(f"Nuevo ticket #{ticket.id} creado por {usuario.nombre}")
    # Lógica custom (notificar, logging, etc.)


# Registrar handler
EventBus.subscribe("ticket.created", on_ticket_created)
```

### Publicar Eventos

```python
from app.tickets.events import EventBus

EventBus.publish("ticket.created", ticket=ticket_obj, usuario=user_obj)
```

---

## 🎯 Estrategias de Asignación

### Round Robin

Asigna tickets de forma rotativa entre usuarios disponibles.

```python
Configuración:
{
  "asignacion": {
    "tipo": "round_robin",
    "auto_assign": true,
    "solo_con_permiso": "tickets.soporte"
  }
}
```

### Basado en Carga

Asigna al usuario con menos tickets activos.

```python
Configuración:
{
  "asignacion": {
    "tipo": "basado_en_carga",
    "auto_assign": true
  }
}
```

### Basado en Skills

Asigna según habilidades o asignaciones específicas (ej: PM por marca).

```python
Configuración:
{
  "asignacion": {
    "tipo": "basado_en_skills",
    "skill_field": "marca_id",  // Lee de ticket.metadata
    "fallback": "basado_en_carga"
  }
}

Ejemplo metadata:
{
  "marca_id": 5  // Se busca en tabla MarcaPM el PM asignado
}
```

### Manual

No auto-asigna, requiere asignación manual.

```python
Configuración:
{
  "asignacion": {
    "tipo": "manual",
    "auto_assign": false
  }
}
```

---

## 🔐 Permisos (TODO)

Sistema de permisos integrado con el existente:

- `tickets.crear`: Crear tickets
- `tickets.ver`: Ver tickets
- `tickets.editar`: Editar tickets
- `tickets.asignar`: Asignar tickets
- `tickets.{sector}.aprobar`: Aprobar en sector específico
- `tickets.{sector}.cerrar`: Cerrar en sector específico
- `sectores.admin`: Administrar sectores y workflows

---

## 📝 TODOs Pendientes

1. **Integración con sistema de permisos existente**
   - Validar permisos en transiciones
   - Filtrar usuarios disponibles por permisos

2. **Sistema de notificaciones**
   - Email
   - In-app notifications
   - Webhooks/Slack

3. **Callbacks custom**
   - Registro de callbacks por nombre
   - Ejecución segura de callbacks
   - Ejemplos: `apply_price_change`, `validate_price_in_range`

4. **Sistema de escalamiento jerárquico**
   - Definir jerarquías (supervisor, gerente)
   - Auto-escalamiento por SLA

5. **Seed data script**
   - Sectores iniciales (Pricing, Soporte, Ventas)
   - Workflows con estados y transiciones
   - Tipos de tickets

6. **Frontend**
   - Componente lista de tickets
   - Componente detalle de ticket
   - Panel de configuración de sectores/workflows

7. **Testing**
   - Unit tests de servicios
   - Integration tests de endpoints
   - Tests de estrategias de asignación

---

## 🏗️ Arquitectura y Decisiones de Diseño

### Por qué Modelo Híbrido (Columnas + JSONB)?

- ✅ **Performance**: Campos frecuentes (título, estado, sector) en columnas indexadas
- ✅ **Flexibilidad**: Campos custom por tipo de ticket en JSONB
- ✅ **No migraciones**: Agregar campos custom sin alterar schema
- ✅ **Queries eficientes**: Filtrar por campos core es rápido

### Por qué Event Bus en lugar de acoplamiento directo?

- ✅ **Desacoplamiento**: Servicios no dependen unos de otros
- ✅ **Extensibilidad**: Agregar features (notificaciones, analytics) sin tocar código existente
- ✅ **Testing**: Mockear eventos es trivial
- ✅ **Asíncrono**: Fácil migrar a celery/redis si se necesita

### Por qué Strategy Pattern para asignación?

- ✅ **Open/Closed**: Agregar nuevas estrategias sin modificar código existente
- ✅ **Configurabilidad**: Cambiar estrategia sin código, solo config
- ✅ **Testeable**: Cada estrategia se testea independientemente

### Por qué State Machine para workflows?

- ✅ **Validación**: Transiciones inválidas son imposibles
- ✅ **Auditoría**: Todos los cambios registrados
- ✅ **Configurabilidad**: Workflows sin hardcodear estados
- ✅ **Permisos granulares**: Control fino de quién puede hacer qué

---

## 📚 Recursos y Referencias

- [Patrón Strategy](https://refactoring.guru/design-patterns/strategy)
- [State Machine Pattern](https://refactoring.guru/design-patterns/state)
- [Event-Driven Architecture](https://martinfowler.com/articles/201701-event-driven.html)
- [PostgreSQL JSONB](https://www.postgresql.org/docs/current/datatype-json.html)

---

**Made with 🔥 by Gentleman Programming**
