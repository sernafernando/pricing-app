# Feature: Pistoleado de Paquetes

## Resumen

Sistema de escaneo (pistoleado) de paquetes para el depósito. El operador escanea el QR de las etiquetas de envío con pistola de barras, el sistema registra quién lo escaneó, cuándo, y en qué caja se cargó. Incluye validaciones de duplicado y de logística asignada.

---

## Contexto — ¿Qué existe hoy?

### Modelos relevantes (ya creados)

| Modelo | Tabla | Campos clave |
|--------|-------|-------------|
| `EtiquetaEnvio` | `etiquetas_envio` | `shipping_id`, `logistica_id`, `fecha_envio`, **`pistoleado_at`** (null), **`pistoleado_caja`** (null) |
| `Operador` | `operadores` | `id`, `pin` (4 dígitos, unique), `nombre`, `activo` |
| `Logistica` | `logisticas` | `id`, `nombre`, `color`, `activa` |
| `OperadorActividad` | `operador_actividad` | `operador_id`, `tab_key`, `accion`, `detalle` (JSONB) |
| `MercadoLibreOrderShipping` | `tb_mercadolibre_orders_shipping` | `mlshippingid`, `mlstatus`, `mlreceiver_name`, `mlzip_code`, `mlcity_name` |

### Flujo actual (sin pistoleado)

1. Se suben etiquetas ZPL (zip/txt) o se escanean manualmente
2. Se extrae el `shipping_id` del QR JSON
3. Se enriquece con datos de ML (coordenadas, dirección)
4. Se asigna logística (individual o masivo)
5. **Acá empieza el pistoleado** — el paquete físico se carga en una caja

### Campos ya preparados en `etiquetas_envio`

```python
pistoleado_at = Column(DateTime(timezone=True), nullable=True)   # ← EXISTE, está null
pistoleado_caja = Column(String(50), nullable=True)              # ← EXISTE, está null
```

### Lo que FALTA agregar a `etiquetas_envio`

```python
pistoleado_operador_id = Column(Integer, ForeignKey("operadores.id"), nullable=True)
```

---

## Flujo de pistoleado

### Escenario normal

```
1. Operador se identifica con PIN (PinLock, ya implementado)
2. Selecciona la logística que está pistoleando (ej: "Andreani")
3. Ingresa o confirma el número de caja (ej: "CAJA-01")
4. Escanea QR de la etiqueta con la pistola → shipping_id
5. Sistema valida:
   a. ¿Existe la etiqueta? → Si no, error "Etiqueta no encontrada"
   b. ¿Ya fue pistoleada? → Si sí, error "Ya pistoleada por {operador} a las {hora} en {caja}"
   c. ¿La logística asignada coincide con la seleccionada? → Si no, warning/error
6. Si pasa validaciones:
   - Graba pistoleado_at = now()
   - Graba pistoleado_caja = caja seleccionada
   - Graba pistoleado_operador_id = operador actual
   - Registra actividad en operador_actividad
7. Feedback visual inmediato: ✓ verde + datos del envío
8. Foco vuelve al input de scan para el siguiente paquete
```

### Escenarios de error

| Error | Qué pasa | Acción |
|-------|----------|--------|
| Etiqueta no existe en el sistema | QR de un envío que no se cargó | Error rojo, mostrar shipping_id |
| Ya pistoleada | Duplicado, alguien ya la escaneó | Warning naranja, mostrar quién/cuándo/caja |
| Logística no coincide | La etiqueta es de Andreani pero están pistoleando OCA | Warning naranja, mostrar a cuál está asignada. **Decisión: ¿bloquear o permitir con confirmación?** |
| Etiqueta sin logística | No se asignó logística todavía | Warning naranja, se puede permitir pistoleado igual |
| Operador no identificado | PIN no ingresado o timeout | PinLock bloquea el UI |

---

## Backend

### Migración: agregar `pistoleado_operador_id`

```
Archivo: alembic/versions/YYYYMMDD_add_pistoleado_operador.py
Tabla: etiquetas_envio
Agregar: pistoleado_operador_id (Integer, FK operadores.id, nullable)
Agregar: Index idx_etiquetas_pistoleado_operador
```

### Endpoint: `POST /api/etiquetas-envio/pistolear`

```
Request body:
{
  "shipping_id": "12345678",
  "caja": "CAJA-01",
  "logistica_id": 3,          // La logística que el operador está pistoleando
  "operador_id": 5
}

Validaciones:
1. shipping_id existe en etiquetas_envio
2. pistoleado_at IS NULL (no fue pistoleada antes)
3. logistica_id de la etiqueta == logistica_id del request (o null)

Si ya fue pistoleada:
  → 409 Conflict {
      "detail": "Ya pistoleada",
      "pistoleado_por": "Juan",
      "pistoleado_at": "2026-02-18T14:30:00Z",
      "pistoleado_caja": "CAJA-02"
    }

Si logística no coincide:
  → 422 {
      "detail": "Logística no coincide",
      "etiqueta_logistica": "Andreani",
      "pistoleando_logistica": "OCA"
    }

Si OK:
  → 200 {
      "ok": true,
      "shipping_id": "12345678",
      "caja": "CAJA-01",
      "operador": "Juan",
      "receiver_name": "Carlos Pérez",        // del JOIN con ML shipping
      "ciudad": "CABA",
      "cordon": "CABA",
      "pistoleado_at": "2026-02-18T14:30:00Z"
    }

Side effects:
  - UPDATE etiquetas_envio SET pistoleado_at, pistoleado_caja, pistoleado_operador_id
  - INSERT operador_actividad (accion='pistoleado', detalle={shipping_id, caja})
```

### Endpoint: `GET /api/etiquetas-envio/pistoleado/stats`

```
Query params: ?fecha=2026-02-18&logistica_id=3

Response:
{
  "total_etiquetas": 150,       // total para esa fecha+logística
  "pistoleadas": 87,
  "pendientes": 63,
  "porcentaje": 58.0,
  "por_caja": {
    "CAJA-01": 45,
    "CAJA-02": 42
  },
  "por_operador": {
    "Juan": 50,
    "Pedro": 37
  }
}
```

### Endpoint: `DELETE /api/etiquetas-envio/pistolear/{shipping_id}` (deshacer)

```
Permite revertir un pistoleado por error.
Pone pistoleado_at, pistoleado_caja, pistoleado_operador_id en NULL.
Registra actividad 'despistoleado' con detalle del estado anterior.
Requiere auth + operador activo.
```

---

## Frontend

### Ubicación

Nueva tab **"Pistoleado"** dentro de `PedidosPreparacion` (al lado de Envíos Flex).

```
Preparación | Pedidos Pendientes | Códigos Postales | Envíos Flex | [Pistoleado]
```

### Componente: `TabPistoleado.jsx`

**Protegido con PinLock** (mismo sistema que Envíos Flex).

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  [Select logística: Andreani ▼]    [Caja: CAJA-01    ]  │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  🔫 Escanear QR:  [________________________]    │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─ Feedback ──────────────────────────────────────┐    │
│  │  ✓ 12345678 — Carlos Pérez — CABA — CAJA-01    │    │
│  │  ✓ 12345679 — María López — Cordon 1 — CAJA-01 │    │
│  │  ✗ 12345680 — Ya pistoleada por Juan (14:30)    │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─ Estadísticas ──────────────────────────────────┐    │
│  │  Pistoleadas: 87/150 (58%)   ████████░░░░░░     │    │
│  │  Caja actual: CAJA-01 (45)                       │    │
│  │  Mi progreso: 37 pistoleadas                     │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Comportamiento del input de scan

- **Autofocus permanente** — el foco siempre vuelve al input después de cada scan
- El scanner de pistola envía el contenido del QR + Enter
- El QR contiene un JSON con `shipping_id` (mismo parser que ya existe en TabEnviosFlex)
- Al recibir Enter → llama al endpoint `POST /pistolear`
- Feedback inmediato inline (lista tipo log, últimos N escaneos)
- Los éxitos se muestran en verde, errores en rojo, warnings en naranja
- Sonido opcional: beep de éxito / beep distinto para error (si se quiere)

### Flujo del UI

1. **Seleccionar logística** — obligatorio antes de empezar a pistolear. Dropdown con las logísticas activas.
2. **Ingresar caja** — texto libre o dropdown de cajas predefinidas. Se mantiene entre escaneos.
3. **Escanear** — cada scan dispara el POST, muestra feedback, y limpia el input.
4. **Stats en vivo** — se actualizan después de cada pistoleado exitoso (o con polling cada N segundos).

---

## Decisiones tomadas

### 1. Logística no coincide: **BLOQUEAR**

Si la etiqueta es de Andreani y están pistoleando OCA → 422 rechazado. El operador tiene que cambiar de logística o reasignar la etiqueta primero.

### 2. Cajas: **QR de comando (modo)**

Se escanea un QR de texto plano ("CAJA 1", "SUELTOS 1", etc.) para cambiar el modo. Todo lo que se pistolee después va a esa caja hasta el próximo cambio. Los contenedores son: CAJA 1-8, SUELTOS 1-2, EXTRA, POR FUERA.

### 3. Deshacer: **ANULAR vía QR de comando**

El operador escanea el QR "ANULAR" → se revierte el último pistoleado de su sesión. Se registra actividad "despistoleado" con estado anterior para auditoría.

### 4. Fecha de envío: **SÍ, se guarda**

Se registra `fecha_envio` en el JSONB de `detalle` de `operador_actividad` al momento de pistolear. Costo cero, valor alto.

### 5. Notificación 100%: **TTS + toast**

- En CADA pistoleado exitoso, TTS dice el número acumulado ("uno", "dos", "tres"...)
- Al completar 100% de una logística, TTS dice "{logística} completo, {N} de {N}"
- Comando BACKUP = repite el total actual por TTS (para cuando el operador perdió la cuenta)

### Fase 2 (pendiente)

- QR de logística: para cambiar de logística escaneando en vez de usar dropdown

---

## Registro en tabRegistry

```javascript
// En PedidosPreparacion.jsx, agregar al registrarPagina:
{ tabKey: 'pistoleado', label: 'Pistoleado' }
```

---

## Archivos a crear/modificar

### Backend — crear
- `alembic/versions/YYYYMMDD_add_pistoleado_operador.py` — migración
- Endpoints en `etiquetas_envio.py` (agregar al router existente)

### Backend — modificar
- `app/models/etiqueta_envio.py` — agregar `pistoleado_operador_id` + FK + relationship

### Frontend — crear
- `frontend/src/components/TabPistoleado.jsx` — componente principal
- `frontend/src/components/TabPistoleado.module.css` — estilos

### Frontend — modificar
- `frontend/src/pages/PedidosPreparacion.jsx` — agregar tab + PinLock wrap
- Tab registry en PedidosPreparacion ya se actualiza automáticamente

---

## Orden de implementación sugerido

1. Migración: agregar `pistoleado_operador_id` a `etiquetas_envio`
2. Endpoint `POST /pistolear` con validaciones
3. Endpoint `GET /pistoleado/stats`
4. Frontend `TabPistoleado.jsx` con scan + feedback
5. Integrar en PedidosPreparacion como tab nueva con PinLock
6. Endpoint `DELETE /pistolear/{shipping_id}` (deshacer)
7. Polish: sonidos, stats en vivo, notificación 100%
