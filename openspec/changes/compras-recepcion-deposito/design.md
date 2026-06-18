# Design — Recepción de Mercadería por Depósito (compras-recepcion-deposito)

**Persistence:** hybrid. Engram topic_key `sdd/compras-recepcion-deposito/design`.
**Depends on:** `compras-vincular-orden-compra-erp` Slice 1 (merged). Builds the `pedido_compra_ingresos` table that was sketched as Slice 2 (AD3/AD4) of that change but **never implemented** — confirmed via repo scan (no `pedido_compra_ingresos` model/migration/table exists). R-DUP is RESOLVED: no duplication, this change owns the table.

This document is the architectural HOW. It does NOT define tasks. All LOCKED decisions from the proposal/spec are taken as given.

---

## 1. Architecture overview

Two slices, stacked-to-main, backend before frontend.

```
                 ┌──────────────────────────────────────────────┐
  Frontend       │ AdministracionCompras.jsx (TABS array)         │
  (Slice B)      │   └─ tab "deposito" → TabRecepcionDeposito.jsx │
                 │        ├─ acordeón por pedido pagado            │
                 │        ├─ tabla ítems (tilde + input)  ── CON OC│
                 │        ├─ cartelito "falta vincular OC" ─ SIN OC│
                 │        └─ ModalCargarRetiro.jsx (requiere_envio)│
                 └───────────────┬──────────────────────────────┘
                                 │ axios (services/api.js)
                 ┌───────────────▼──────────────────────────────┐
  Backend        │ routers/administracion_compras.py (Batch K)    │
  (Slice A)      │   require_permiso("deposito.recibir_mercaderia")│
                 │   GET  /pedidos/{id}/recepcion/saldos           │
                 │   POST /pedidos/{id}/recepcion/ingresos         │
                 │   POST /pedidos/{id}/recepcion/confirmar-pedido │
                 │   GET  /pedidos/{id}/recepcion/eventos          │
                 │   (reuso) POST .../generar-etiqueta-envio       │
                 └───────────────┬──────────────────────────────┘
                                 │
                 ┌───────────────▼──────────────────────────────┐
  Service        │ services/recepcion_service.py (NEW)            │
                 │   computar_saldos · registrar_ingresos ·       │
                 │   confirmar_pedido_sin_oc · recalcular_estado  │
                 │ services/oc_ingresos_service.py (EXTEND JOIN)  │
                 └───────────────┬──────────────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────────┐
        ▼                        ▼                             ▼
  pedido_compra_ingresos    pedidos_compra              compras_eventos
  (NEW, owned escritura)    (estado: +2 valores)        (+2 tipos)
        │
        ▼ snapshot/saldo lee live (read-only)
  tb_purchase_order_detail · tb_storage · productos_erp
```

**Pattern:** thin router (validate + permission + commit), service holds state machine + saldo math + event emission. Mirror tables (`tb_*`, `productos_erp`) are **strictly read-only** — recepción NEVER writes ERP stock (AD8 inherited).

---

## 2. Data model — `pedido_compra_ingresos` (NEW table, append-only)

DDL (PostgreSQL). Created in Slice A migration. Mirrors the AD3/AD4 sketch from the prior design, grano `pod_id`, snapshot of OC line identity.

```sql
CREATE TABLE pedido_compra_ingresos (
    id                BIGSERIAL    PRIMARY KEY,
    pedido_id         BIGINT       NOT NULL
                                   REFERENCES pedidos_compra(id) ON DELETE RESTRICT,
    -- Snapshot de identidad de la línea OC (FK lógica, sin constraint físico — espeja ct_transaction_id/oc_*).
    oc_comp_id        INTEGER      NULL,
    oc_bra_id         INTEGER      NULL,
    oc_poh_id         BIGINT       NULL,
    pod_id            BIGINT       NULL,     -- línea OC; NULL solo para registro especial SIN-OC (§6)
    item_id           INTEGER      NULL,     -- snapshot, puede ser ítem fantasma
    stor_id           INTEGER      NULL,     -- depósito destino (snapshot)
    cantidad_recibida NUMERIC(18,6) NOT NULL,
    fecha_ingreso     DATE         NOT NULL DEFAULT CURRENT_DATE,
    usuario_id        INTEGER      NOT NULL
                                   REFERENCES usuarios(id) ON DELETE RESTRICT,
    observaciones     TEXT         NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_pci_cantidad_positiva CHECK (cantidad_recibida > 0)
);

CREATE INDEX ix_pci_pedido    ON pedido_compra_ingresos (pedido_id);
CREATE INDEX ix_pci_pod       ON pedido_compra_ingresos (pod_id) WHERE pod_id IS NOT NULL;
CREATE INDEX ix_pci_oc_linea  ON pedido_compra_ingresos (oc_comp_id, oc_bra_id, oc_poh_id, pod_id);
```

**SQLAlchemy model:** `backend/app/models/pedido_compra_ingresos.py` → class `PedidoCompraIngreso`. Explicit column types (project rule). `cantidad_recibida = Column(Numeric(18, 6), nullable=False)`. Relationship `usuario` (read-only). Append-only: no PUT/DELETE endpoints, service never updates/deletes rows (mirrors `CompraEvento` discipline).

**Why append-only + grano pod_id:** receipts are accumulative tandas (recibo 3 hoy, 5 mañana). Each tanda inserts one row per line. The saldo is always derived, never stored — single source of truth, no drift. `ON DELETE RESTRICT` on `pedido_id`/`usuario_id` preserves the físical-arrival audit trail even if a pedido is later corrected (matches AD5 inherited: desvincular OC must NOT delete ingresos).

---

## 3. State machine (estado en `pedidos_compra`)

Extend the existing `CheckConstraint` pattern (Opción A from explore — string + CHECK, no Python Enum). Migration does drop+add of `ck_pedidos_compra_estado`.

```
                       ┌──────────────────────────────┐
                       ▼                              │ (más tandas, saldo sigue > 0)
   pagado ──recepción──► con_faltantes ──recepción────┘
     │   (∃ saldo > 0)        │
     │                        └──recepción (todos los saldos → 0)──► recibido (TERMINAL)
     └───────recepción (todos los saldos = 0)────────────────────► recibido (TERMINAL)
```

| From | Trigger | To | Condición |
|------|---------|----|-----------|
| `pagado` | POST ingresos / confirmar-pedido | `recibido` | tras la tanda, ∀ línea saldo = 0 (o confirmar `completo=true`) |
| `pagado` | POST ingresos | `con_faltantes` | tras la tanda, ∃ línea saldo > 0 |
| `con_faltantes` | POST ingresos | `con_faltantes` | sigue quedando saldo > 0 (NO terminal) |
| `con_faltantes` | POST ingresos | `recibido` | la tanda cierra todos los saldos → 0 |
| `recibido` | POST ingresos / confirmar | — | **bloqueado 409** (terminal) |

**New CheckConstraint:**
```sql
ALTER TABLE pedidos_compra DROP CONSTRAINT ck_pedidos_compra_estado;
ALTER TABLE pedidos_compra ADD CONSTRAINT ck_pedidos_compra_estado
  CHECK (estado IN ('borrador','pendiente_aprobacion','aprobado','rechazado',
                    'cancelado','pagado_parcial','pagado','recibido','con_faltantes'));
```
Same change must be applied to the `CheckConstraint(...)` literal in `models/pedido_compra.py` L144-148 so model and DB agree.

**Where validated:** `recepcion_service.recalcular_estado(session, pedido)` — runs AFTER inserting the tanda rows, recomputes all saldos, sets `pedido.estado`. Transition guard at entry of `registrar_ingresos`: if `pedido.estado == 'recibido'` → 409. If `pedido.estado not in {'pagado','con_faltantes'}` → 409 (only pagado/con_faltantes accept receipts). `recepcion_parcial` is NOT created — `con_faltantes` plays that role (D1 resolved).

**Re-recepción from `con_faltantes`:** naturally supported — the state guard allows `con_faltantes` as an entry state, saldo math is cumulative, so a second tanda just adds rows and recomputes.

---

## 4. Permiso nuevo `deposito.recibir_mercaderia` — mecanismo exacto

The real catalog lives in table `permisos` (cols `codigo, nombre, descripcion, categoria, orden, es_critico, created_at`) and role mapping in **`roles_permisos_base`** (NOTE: real table name is `roles_permisos_base`, not the `rol_permiso_base` shown in the generic SKILL example). Seeding is done **inside an Alembic migration with raw `op.execute` INSERTs**, exactly like `20260326_permisos_administracion.py`.

**Seed migration (part of Slice A migration, or a dedicated one chained after it):**
```python
PERMISO = (
    "deposito.recibir_mercaderia",
    "Recibir mercadería",
    "Registrar la recepción física de pedidos en depósito (recepción por ítem o confirmación a nivel pedido) y generar retiros de proveedor.",
    "deposito_sector",   # nueva categoría — perfil operario de almacén
    200,                 # orden
    True,                # es_critico (escribe estado del pedido)
)

def upgrade() -> None:
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES ('deposito.recibir_mercaderia', 'Recibir mercadería',
                '...descripcion...', 'deposito_sector', 200, true, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)
    # Asignar SOLO a SUPERADMIN (acceso garantizado; SUPERADMIN además bypassa por es_superadmin).
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permisos p
        WHERE r.codigo = 'SUPERADMIN' AND p.codigo = 'deposito.recibir_mercaderia'
        ON CONFLICT DO NOTHING;
    """)

def downgrade() -> None:
    op.execute("DELETE FROM roles_permisos_base WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo='deposito.recibir_mercaderia')")
    op.execute("DELETE FROM permisos WHERE codigo='deposito.recibir_mercaderia'")
```

**Decision D-PERM (LD4):** seed the permiso but assign it ONLY to SUPERADMIN. Operarios de almacén get it via **per-user override** (`usuarios_permisos_override`, `concedido=true`) or a future role assignment — NOT auto-granted to ADMIN/GERENTE/etc. Rationale: depósito is a distinct profile; admins shouldn't silently inherit it. This is documented for the rollout (§9): after deploy, the admin must grant the override to warehouse users via the existing user-permissions UI.

**Enforcement:** all four new endpoints use `Depends(require_permiso("deposito.recibir_mercaderia"))` (the existing dep at `api/deps.py:105`). Constant: define `PERMISO_RECEPCION = "deposito.recibir_mercaderia"` near the router/service to avoid hardcoded strings (project rule).

**D2 resolved (coexistencia de permisos):** POST ingresos requires SOLO `deposito.recibir_mercaderia` (LOCKED — single permiso, no OR with `gestionar_ordenes_compra`). Keeps the operario profile clean; admins who also need it get the override. R6 closed.

**Frontend gating:** `usePermisos().tienePermiso('deposito.recibir_mercaderia')` gates the tab entry and all action buttons. SUPERADMIN bypasses.

---

## 5. Saldo acumulativo — fórmula y query

**Formula per OC line (`pod_id`):**
```
saldo(pod_id) = pod_qty
              − COALESCE(pod_confirmedqty, 0)        -- ya confirmado en ERP
              − Σ cantidad_recibida (pricing-app, ese pod_id)
```
This extends the prior design's AD3. The `Σ ingresos pricing-app` term — which was always 0 in Slice 1 — now becomes real because the table exists.

**`GET /pedidos/{id}/recepcion/saldos` query** (read-only, one round-trip per source):
```sql
-- A) líneas OC vivas + nombre de ítem (extiende oc_ingresos_service.get_orden_compra_detalle, ver §7)
SELECT d.pod_id, d.item_id, d.stor_id, s.stor_desc,
       d.pod_qty, d.pod_confirmedqty, d.pod_price,
       p.nombre AS item_nombre               -- LEFT JOIN, NULL si fantasma
FROM tb_purchase_order_detail d
LEFT JOIN tb_storage   s ON s.comp_id = d.comp_id AND s.stor_id = d.stor_id
LEFT JOIN productos_erp p ON p.item_id = d.item_id     -- JOIN nuevo, §7
WHERE d.comp_id = :comp AND d.bra_id = :bra AND d.poh_id = :poh
ORDER BY d.pod_id;

-- B) recibido acumulado en pricing-app, agrupado por pod_id
SELECT pod_id, COALESCE(SUM(cantidad_recibida),0) AS recibido_pricing
FROM pedido_compra_ingresos
WHERE pedido_id = :pedido_id AND pod_id IS NOT NULL
GROUP BY pod_id;
```
Service joins A+B in Python: `saldo_pendiente = pod_qty − pod_confirmedqty − recibido_pricing`. Response per line adds `recibido_pricing` and `item_nombre`; response root carries `tiene_oc: bool` (pedido.oc_poh_id is not None) so the frontend decides CON-OC vs SIN-OC mode without a second call.

**Recálculo de estado tras cada tanda** (`recalcular_estado`):
1. Recompute `saldo(pod_id)` for ALL lines of the OC.
2. If `∀ línea: saldo <= 0` → `pedido.estado = 'recibido'`.
3. Else (`∃ saldo > 0`) → `pedido.estado = 'con_faltantes'`.
4. Emit event (§8).

**Over-receipt 409 (R3, LOCKED):** in `registrar_ingresos`, for each incoming `{pod_id, cantidad_recibida}` validate `cantidad_recibida <= saldo(pod_id)` computed from CURRENT cumulative state. If any line exceeds → raise 409 (`detail` names the pod_id and remaining saldo) and roll back the WHOLE tanda (atomic — no partial insert). v1 has zero tolerance; tolerance band deferred (D3 closed: bloqueo).

**Edge: línea con saldo 0 que recibe más → 409.** Línea ya completa no admite más.

---

## 6. Modo SIN OC — `POST /pedidos/{id}/recepcion/confirmar-pedido`

When `pedido.oc_poh_id IS NULL` there are no OC lines to iterate, so receipt is confirmed at pedido level.

**Contract:** body `{ "completo": bool, "observaciones": str | null }`.
- `completo = true` → `pedido.estado = 'recibido'` (terminal).
- `completo = false` → `pedido.estado = 'con_faltantes'`.

**Persistence decision D-SINOC:** write ONE sentinel row in `pedido_compra_ingresos` with `pod_id = NULL`, `oc_* = NULL`, `item_id = NULL`, `stor_id = NULL`, `cantidad_recibida = 1` (placeholder satisfying the `> 0` check — represents "1 confirmation act", not a quantity), `usuario_id`, `observaciones`. Rationale: keeps WHO/WHEN audit uniform in one table instead of relying only on the event; the `ix_pci_pod ... WHERE pod_id IS NOT NULL` index excludes these rows from saldo aggregation, so they never pollute CON-OC math. The state guard still applies: a `recibido` pedido rejects further confirmar with 409.

**Guard:** if pedido HAS an OC (`oc_poh_id` not null), `confirmar-pedido` returns 400 ("use recepción por ítem"). And vice-versa: `POST ingresos` on a pedido without OC returns 409 ("vinculá la OC primero o usá confirmar-pedido").

Frontend in SIN-OC mode shows the cartelito "Falta vincular la orden de compra" + a single "Confirmar recepción" button (and "Confirmar con faltantes" secondary).

---

## 7. JOIN productos_erp para nombre de ítem (R1 ítems fantasma)

`oc_ingresos_service.get_orden_compra_detalle` (used by `GET .../orden-compra/detalle`) is extended with `LEFT JOIN productos_erp p ON p.item_id = d.item_id`, adding `item_nombre` to `OrdenCompraLineaResponse` (schema `oc_ingreso.py`). The same JOIN feeds `recepcion/saldos`.

**Ghost-item handling:** LEFT JOIN → `item_nombre` is `NULL` when the ERP item isn't synced into `productos_erp`. The service does NOT fail; it returns `item_nombre = None`. Frontend fallback: render `Ítem #{item_id}` (or `Ítem ERP {item_id} (sin nombre)`) when null. Same degradation as `pedidos_preparacion.py:254` ghost items. The exact `productos_erp` PK/column for item must be confirmed at apply time (assumption: `item_id`) — see Open Decisions.

---

## 8. Eventos (`compras_eventos`, JSONB) — LD6

Append-only via existing `CompraEvento` model. Two new `tipo` values (string col, length 48 — fits). No CheckConstraint change needed on `compras_eventos` (its CHECK is on `entidad_tipo`, not `tipo`).

| tipo | cuándo | payload |
|------|--------|---------|
| `recepcion_registrada` | tras una tanda que deja el pedido en `recibido` | `{ "lineas": [{pod_id, cantidad_recibida, saldo_post}], "estado_resultante": "recibido", "observaciones": str? }` |
| `recepcion_con_faltantes` | tras una tanda que deja `con_faltantes` (o confirmar `completo=false`) | `{ "lineas": [...], "saldos_pendientes": [{pod_id, saldo}], "estado_resultante": "con_faltantes", "observaciones": str? }` |

`entidad_tipo = CompraEvento.ENTIDAD_TIPO_PEDIDO`, `entidad_id = pedido_id`, `usuario_id = user.id`. Emitted inside the same transaction as the ingreso insert + estado update (atomicidad). `GET /pedidos/{id}/recepcion/eventos` filters `entidad_tipo='pedido_compra' AND entidad_id=:id AND tipo IN (...)` ordered by `created_at DESC`.

---

## 9. Retiro proveedor — contrato del mini-flujo (LD5)

Pure reuse, no TabEnviosFlex montado.

1. Pedido con `requiere_envio = True` (col ya existe, L59) muestra botón "Cargar retiro" en su acordeón.
2. `ModalCargarRetiro.jsx` llama `GET /proveedores/{proveedor_id}/direcciones` (endpoint existente, devuelve `DireccionResponse[]` activas; `administracion_proveedores.py:507`). El usuario elige una dirección (radio-select). Si hay una sola, se preselecciona.
3. Al confirmar → `POST /pedidos/{pedido_id}/generar-etiqueta-envio` con body `{ "proveedor_direccion_id": int }` (param opcional ya soportado, router L907-940 — internamente `etiqueta_retiro_service.generar_etiqueta_retiro`, crea `EtiquetaEnvio` tipo `retiro_proveedor`).
4. Feedback: toast de éxito + `shipping_id`/`id` devueltos. NO se monta el módulo Envíos Flex.

**Permiso del retiro en recepción:** el endpoint `generar-etiqueta-envio` HOY exige `administracion.gestionar_ordenes_compra` (router L915). El operario de depósito NO lo tiene. **Open Decision D-RETIRO** (ver §11): para que el operario dispare retiros desde la tab, hay que ampliar ese endpoint a aceptar `deposito.recibir_mercaderia` OR `gestionar_ordenes_compra`. Sin esto, el botón "Cargar retiro" daría 403 al operario. Recomendación: agregar el OR (helper `require_alguno([...])` o check explícito en el endpoint). Esto es la única excepción al "permiso único" y es necesaria para el flujo de retiro.

---

## 10. Frontend — estructura (Slice B)

Stack: React + Zustand (solo si hace falta global; default useState local) + CSS Modules + Tesla design tokens + lucide-react. NO Tailwind/inline en componentes nuevos de compras (consistente con ModalVincularOC).

**Tab registration:** add `{ id: 'deposito', label: 'Depósito', ... }` to the `TABS` array in `AdministracionCompras.jsx` (L25-75), rendering `<TabRecepcionDeposito />` when active.

**`TabRecepcionDeposito.jsx`** (`frontend/src/components/compras/`):
- Lista pedidos `estado=pagado` (reusa el filtro de query param que ya soporta el backend; filtro adicional `requiere_envio` opcional). Tras una recepción, los pedidos pasan a `recibido`/`con_faltantes` — la tab puede ofrecer un filtro de estado para verlos.
- Cada pedido = fila/acordeón. Al expandir: `GET /pedidos/{id}/recepcion/saldos`.
  - `tiene_oc=true` → tabla de ítems: columnas `[tilde] · ítem (nombre o fallback #id) · depósito · pod_qty · recibido_prev · saldo · [input cantidad]`.
  - `tiene_oc=false` → cartelito "Falta vincular la orden de compra" + botones confirmar.
- **Estado local de la tanda (useState):** `{ [pod_id]: cantidadInput }`. Reglas (input = fuente de verdad):
  - Tilde de línea → setea `input = saldo` de esa línea.
  - Destilde → setea `input = 0`.
  - "Marcar todo" → setea `input = saldo` para todas las líneas.
  - Editar input manualmente: `0 < input <= saldo` válido; `input > saldo` → borde rojo + botón submit deshabilitado (espeja el 409 backend, evita el round-trip).
- **Habilitación de botones:**
  - "Registrar recepción" habilitado si ∃ línea con `input > 0` y ningún `input > saldo`.
  - Botón refleja el resultado esperado: si todos los inputs == saldo → "Marcar recibido"; si parcial → "Registrar (quedará con faltantes)".
- Submit → `POST .../recepcion/ingresos { lineas: [{pod_id, cantidad_recibida}], observaciones? }` (solo líneas con `input > 0`). On 409 → toast con el detail. On 200 → refresca saldos + estado del pedido.
- `requiere_envio=true` → botón "Cargar retiro" que abre `ModalCargarRetiro`.

**`ModalCargarRetiro.jsx`:** radio-select de direcciones (`GET /proveedores/{id}/direcciones`) → `POST .../generar-etiqueta-envio`. Espeja el shape de modal de `ModalVincularOC.jsx`.

**Servicios/hooks:** extender `useComprasPedidos.js` (o un `useRecepcionDeposito.js` nuevo) con `getSaldos`, `registrarIngresos`, `confirmarPedido`, `getEventosRecepcion`, `cargarRetiro`. Llamadas vía `services/api.js` (axios). Zustand nuevo: NO requerido — estado de tanda es efímero por acordeón.

### 10.1 Pantallas que necesita STITCH (placeholder — gate previo a implementar Slice B)

El diseño visual concreto lo genera **stitch**. El orquestador debe pedirle estos mockups ANTES de codear Slice B:

1. **Acordeón de pedido** — fila colapsada (nº pedido, proveedor, estado badge `pagado`/`recibido`/`con_faltantes`, flag requiere_envio) + estado expandido.
2. **Tabla de ítems (CON OC)** — fila por línea con: checkbox tilde, nombre de ítem (+ fallback ítem fantasma), depósito, pedido, recibido previo, saldo, input de cantidad. Estado de error de input (input > saldo).
3. **Barra de acciones** — checkbox "Marcar todo", botón primario "Registrar recepción / Marcar recibido", textarea observaciones, estado deshabilitado.
4. **Cartelito SIN OC** — banner de advertencia "Falta vincular la orden de compra" + botones "Confirmar recepción" / "Confirmar con faltantes".
5. **Mini-modal de retiro** (`ModalCargarRetiro`) — lista/radio de direcciones del proveedor + botón "Generar retiro" + feedback de éxito.
6. (opcional) **Timeline de eventos de recepción** — lista read-only de `recepcion_registrada`/`recepcion_con_faltantes` con fecha/usuario/detalle.

---

## 11. Slices, migración y rollout

**Slice A (backend, ~400 líneas, budget alto):**
- Migración Alembic `YYYYMMDD_recepcion_deposito.py` (naming del proyecto). `down_revision` = el head actual — resolver con `alembic heads` al momento de apply (el último de compras es `20260618_add_oc_link_to_pedidos_compra` de Slice 1 del change previo; confirmar que sigue siendo head). Contenido: (a) `CREATE TABLE pedido_compra_ingresos` + índices; (b) drop+add `ck_pedidos_compra_estado` con los 2 estados nuevos; (c) seed `deposito.recibir_mercaderia` + asignación SOLO SUPERADMIN. (Se puede partir en 2 migraciones encadenadas si se prefiere granularidad; una sola es aceptable.) Sin backfill.
- Modelo `PedidoCompraIngreso` + actualizar literal del CheckConstraint en `pedido_compra.py`.
- `services/recepcion_service.py`: `computar_saldos`, `registrar_ingresos` (validación 409 + insert atómico + recalcular + evento), `confirmar_pedido_sin_oc`, `recalcular_estado`.
- Extender `oc_ingresos_service.get_orden_compra_detalle` con JOIN `productos_erp` + `item_nombre` en el schema.
- Endpoints Batch K en `administracion_compras.py` (tras Batch J), todos `require_permiso("deposito.recibir_mercaderia")`. Schemas Pydantic en `oc_ingreso.py` (o `recepcion.py` nuevo): `SaldoLineaResponse`, `SaldosResponse`, `IngresoLinea`, `RegistrarIngresosRequest`, `ConfirmarPedidoRequest`, `EventoRecepcionResponse`.
- Resolver D-RETIRO: ampliar `generar-etiqueta-envio` para aceptar el permiso de depósito (OR).
- Tests pytest (§12).

**Slice B (frontend, ~400 líneas, budget alto):** depende de A **y** del output de stitch (§10.1, gate previo). Tab + `TabRecepcionDeposito.jsx` + `ModalCargarRetiro.jsx` + hook + CSS Module Tesla.

**Rollout:** deploy Slice A → correr `alembic upgrade head` → grant manual del permiso `deposito.recibir_mercaderia` a los usuarios operarios (override `concedido=true`) vía UI de permisos. Luego Slice B. La tab queda oculta para quien no tenga el permiso. Cero impacto en pedidos existentes (sin backfill, estados nuevos opt-in).

**Review Workload Forecast:** 2 slices, cada uno ~400 líneas → riesgo de budget 400 ALTO en ambos. Chained PRs recomendado (stacked-to-main). Decisión de split necesaria antes de apply.

---

## 12. Testabilidad (Strict TDD, pytest)

Tests de integración bajo `backend/tests/integration/`, espejando `test_oc_vincular_s1_endpoints.py` / `test_compras_vincular_factura_endpoints.py`. Cada endpoint: caso 403 sin permiso `deposito.recibir_mercaderia`.

- **saldos:** computa `pod_qty − pod_confirmedqty − Σ ingresos`; tras una tanda baja el saldo; `tiene_oc` true/false; `item_nombre` null en ítem fantasma (LEFT JOIN).
- **ingresos:** inserta tanda; 409 al exceder saldo (acumulado, atómico — no inserta parcial); transición `pagado→con_faltantes` (∃ saldo) y `pagado→recibido` (saldos 0); re-recepción desde `con_faltantes`→`recibido`; 409 sobre pedido `recibido`; 409 sobre pedido sin OC; emite evento correcto; NUNCA escribe `tb_purchase_order_detail`/stock.
- **confirmar-pedido:** `completo=true`→`recibido`, `false`→`con_faltantes`; 400 si el pedido tiene OC; row sentinela `pod_id IS NULL` no afecta saldos; 409 si ya `recibido`.
- **eventos:** lista filtra por entidad+tipo, orden DESC.
- **state machine:** `recibido` terminal; `con_faltantes` no terminal.

ERP mirrors read-only en todos los tests.

---

## 13. ADRs (decisiones con rationale)

- **AD1 — Tabla `pedido_compra_ingresos` append-only, grano `pod_id`, saldo derivado.** Rechazado: payload JSONB único en evento (no queryable por pod_id, no soporta tandas múltiples). Receipts acumulativos necesitan historial estructurado.
- **AD2 — Estado via CheckConstraint extendido (no Python Enum, no tabla de historia).** `compras_eventos` ya cubre el historial de transiciones. Rechazado: tabla `pedido_compra_estados_historia` (over-engineering).
- **AD3 — Permiso `deposito.recibir_mercaderia` seedeado por migración, asignado SOLO a SUPERADMIN; operarios vía override.** Perfil de almacén distinto del de compras. Rechazado: reusar `gestionar_ordenes_compra` (mezcla perfiles). Rechazado: auto-grant a ADMIN/GERENTE (acceso silencioso indebido).
- **AD4 — Over-receipt bloqueado (409), tanda atómica.** v1 sin tolerancia; simple y seguro. Tolerancia diferida.
- **AD5 — `con_faltantes` cubre el rol de recepción parcial; no se crea estado nuevo.** Menos estados, mismo poder expresivo.
- **AD6 — Modo SIN-OC escribe row sentinela `pod_id NULL` (no solo evento).** Audit WHO/WHEN uniforme en una tabla; índice parcial excluye sentinelas del saldo.
- **AD7 — Saldo SIEMPRE derivado, nunca materializado.** Single source of truth, sin drift entre tandas.
- **AD8 — ERP strictly read-only (heredado).** Recepción jamás escribe stock ni `tb_*`.

---

## 14. Open Decisions (confirmar antes de tasks/apply)

- **D-RETIRO (recomendado: ampliar):** `generar-etiqueta-envio` hoy exige `gestionar_ordenes_compra`; para que el operario dispare el retiro desde la tab hay que aceptar también `deposito.recibir_mercaderia` (OR). Sin esto el botón da 403. ¿Se amplía el endpoint? (Recomendación: sí, es el único OR necesario.)
- **D-PERROERP:** columna real de `productos_erp` para joinear el nombre del ítem (asunción: `item_id` ↔ `productos_erp.item_id`, nombre en `productos_erp.nombre`). Verificar contra el esquema real antes de codear el JOIN (mismo riesgo de "ítem fantasma" que ya existe).
- **D-MIGSPLIT:** ¿una sola migración (tabla + constraint + permiso) o tres encadenadas? Una es aceptable; tres dan granularidad de rollback. Recomendación: una, salvo que se prefiera rollback fino del permiso.
- **D-FILTRODEPO (diferido, R/D6):** ¿la tab filtra por depósito del operario logueado? v1 muestra todos los pedidos pagados; filtrado por `stor_id`/sucursal del operario se difiere (no hay modelo operario↔depósito confirmado).
- **D-REABRIR (diferido, D4):** `recibido` es terminal en v1; reabrir no soportado.
- **D-NOTIF (diferido, D5):** notificar a compras cuando queda `con_faltantes` — fuera de scope v1.
