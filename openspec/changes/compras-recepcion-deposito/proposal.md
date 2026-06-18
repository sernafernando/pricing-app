# Proposal — Recepción de Mercadería por Depósito

**Change ID:** `compras-recepcion-deposito`
**Fase:** proposal
**Status:** draft
**Owner:** Compras + Depósito
**Fecha:** 2026-06-18
**Persistence:** hybrid (este archivo + engram `sdd/compras-recepcion-deposito/proposal`)
**Depende de:** `compras-vincular-orden-compra-erp` (Slice 1 — vínculo OC + `GET /pedidos/{id}/orden-compra/detalle`) — **ya mergeado**.

---

## Why

Hoy cuando un pedido de compra queda `pagado`, el circuito en el pricing-app **termina ahí**. Nadie registra QUÉ llegó físicamente al depósito, CUÁNDO, ni si llegó completo. La recepción de mercadería vive en la cabeza del operario de depósito, en papel o en WhatsApp.

Problemas concretos:

1. **Cero trazabilidad de recepción**: no hay registro de qué unidades de un pedido pagado efectivamente entraron. No se puede reclamar un faltante al proveedor con evidencia.
2. **Entregas parciales invisibles**: el proveedor manda 30 de 50 unidades hoy y el resto en una semana. Hoy no hay forma de registrar la primera tanda y esperar la segunda.
3. **Retiros desconectados**: cuando el acuerdo dice que retiramos nosotros (`requiere_envio=true`), el operario tiene que ir a otro módulo monolítico (TabEnviosFlex, ~4300 líneas) a cargar el retiro a mano, reescribiendo datos del proveedor que ya existen en `proveedor_direcciones`.
4. **Perfil de depósito sin herramienta propia**: el operario de almacén no debería tener acceso a toda la administración de compras (aprobar, pagar) solo para confirmar que llegó la mercadería.

El negocio necesita cerrar el loop: **pedido pagado → mercadería recibida (completa o con faltantes documentados) → evidencia auditable**.

---

## What

Vista nueva de **recepción de mercadería** dentro de `AdministracionCompras.jsx` (tab `deposito`), pensada para el perfil de operario de almacén. Lista los pedidos `pagado`, y para cada uno permite registrar qué llegó — acumulando entregas en tandas hasta completar el pedido.

Flujo según el flag `requiere_envio` del pedido:
- **`requiere_envio = true`** → "tenemos que retirarlo del proveedor": además de recibir, ofrece cargar un **retiro a la dirección del proveedor** reutilizando el endpoint existente `POST /pedidos/{id}/generar-etiqueta-envio`.
- **`requiere_envio = false`** → "nos llega a nosotros": solo recepción.

Cada pedido es un acordeón (spoiler). Al abrir:
- **Pedido CON OC vinculada** → recepción **por ítem**: líneas de `GET /pedidos/{id}/orden-compra/detalle` (con nombre legible vía JOIN a `productos_erp`, fallback a `item_id`/código en ítems fantasma). Por línea: tilde + input de unidades recibidas. Tilde "marcar todo". Botones "Recibido" / "Marcar con faltantes".
- **Pedido SIN OC vinculada** → cartelito "falta vincular OC" + confirmación de recepción **a nivel pedido** (no hay fuente de ítems).

---

## Locked Product Decisions

Estas 6 decisiones están cerradas y la propuesta se construye alrededor de ellas.

### LD1 — Recepción ACUMULATIVA en tandas (tabla `pedido_compra_ingresos`)
La mercadería puede llegar en varias entregas. Cada ingreso de línea es un row append-only en `pedido_compra_ingresos` (snapshot de identidad de línea OC: `oc_comp_id/oc_bra_id/oc_poh_id/pod_id` + `item_id` + `stor_id`, más `cantidad_recibida`, `fecha_ingreso`, `usuario_id`, `observaciones`).

**Saldo por línea = cantidad pedida (de la OC: `pod_qty − COALESCE(pod_confirmedqty,0)`) − Σ(`cantidad_recibida` de los ingresos pricing-app de ese `pod_id`).**

> Nota: la tabla y la fórmula de saldo ya estaban diseñadas como **Slice 2** del change anterior (`compras-vincular-orden-compra-erp`, AD3/AD4). Este change **adopta esa tabla** y le agrega la capa de UI de depósito + máquina de estados. Ver Riesgos R-DUP.

### LD2 — Dos modos en la misma vista
- **CON OC** → recepción por ítem (fuente: `orden-compra/detalle` + JOIN nombre).
- **SIN OC** → cartelito + confirmación a nivel pedido. Sin ítems, sin inputs por línea; solo `recibido` global o `con_faltantes` con observación libre.

### LD3 — Estados nuevos del pedido: `recibido` y `con_faltantes`
`estado` es `String(24)` + `CheckConstraint`. Se amplía el constraint (no es Enum). Transiciones:
- `pagado → recibido` (toda la mercadería del pedido recibida; todos los saldos = 0).
- `pagado → con_faltantes` (quedó saldo > 0 en al menos una línea).
- **`con_faltantes` NO es terminal**: puede seguir recibiendo tandas. `con_faltantes → con_faltantes` (otra tanda parcial) y `con_faltantes → recibido` (tanda que completa).

**Decisión sobre estado intermedio** (a confirmar en spec): NO se crea un estado separado `recepcion_parcial`. `con_faltantes` cubre ese rol — semánticamente significa "recibido parcialmente, falta saldo". El detalle (cuánto falta y de qué líneas) vive en los ingresos + el evento, no en un estado adicional. Razón: minimizar la superficie del CheckConstraint y evitar una máquina de estados con estados redundantes. Ver Decisión Abierta D1.

### LD4 — Permiso nuevo `deposito.recibir_mercaderia`
Permiso granular separado de compras. El operario de depósito recibe SOLO este permiso, sin `administracion.gestionar_ordenes_compra`. Gatea: la tab `deposito`, los endpoints de recepción y la acción de cargar retiro. Se crea en migración, **no se asigna a ningún rol por default** (asignación manual vía admin).

> Esto difiere del change anterior (AD7: todo bajo `gestionar_ordenes_compra`). El vínculo/desglose/registro de ingreso "administrativo" sigue bajo `gestionar_ordenes_compra`; la **vista de depósito y sus acciones** usan el permiso nuevo. Ver Decisión Abierta D2 (¿el endpoint POST ingresos acepta ambos permisos?).

### LD5 — Rama "Requiere envío": reusar endpoint existente, NO montar TabEnviosFlex
Si `requiere_envio = true`, un botón "Cargar retiro" abre un **mini-modal** que lista `GET /proveedores/{id}/direcciones`, el usuario elige una, y se dispara `POST /pedidos/{id}/generar-etiqueta-envio` con `proveedor_direccion_id`. Esto crea una `EtiquetaEnvio` tipo `retiro_proveedor` (vínculo ya existente en el modelo). **NO se monta TabEnviosFlex** (monolito 4300 líneas) — solo se dispara su endpoint y se muestra feedback (toast + link opcional a Envíos Flex).

### LD6 — Feedback/reporte vía `compras_eventos` (payload JSONB)
Cada recepción y cada reporte de faltantes se registra como evento append-only en `compras_eventos` (`entidad_tipo='pedido_compra'`). Tipos nuevos: `recepcion_registrada` y `recepcion_con_faltantes`. El `payload` JSONB guarda el detalle: líneas afectadas, `cantidad_recibida` y `saldo_pendiente` por línea en esa tanda.

---

## Lógica de cantidad (recomendada)

**El input "unidades que llegaron" es la fuente de verdad por línea, por tanda.** El tilde y "marcar todo" son atajos de UI, no estado persistido aparte.

- **Tilde de línea** = atajo: completa el input con el **saldo pendiente** de esa línea (`saldo_actual`).
- **"Marcar todo"** = completa todos los inputs con su saldo pendiente respectivo.
- **"Recibido" habilitado** cuando la tanda lleva **todos los saldos a 0** (`∀ línea: cantidad_recibida_tanda == saldo_actual`).
- **"Marcar con faltantes" habilitado** cuando, tras aplicar la tanda, **queda saldo > 0** en al menos una línea.
- Una línea con input `0` no participa de la tanda (no genera row en `pedido_compra_ingresos`; CHECK `cantidad_recibida > 0`).

**Over-receipt** (recibir más que el saldo): por defecto **bloqueado** — `cantidad_recibida` de la tanda > `saldo_actual` → HTTP 409 (espeja la validación del change anterior: ingreso no puede exceder saldo acumulado). Ver Decisión Abierta D3 si el negocio quiere permitir over-receipt con tolerancia.

**Re-apertura desde `con_faltantes`**: no es "re-apertura" — el pedido `con_faltantes` sigue aceptando ingresos. Cada nueva tanda recalcula saldos; si llega a 0 en todas las líneas, transiciona a `recibido`. **`recibido` SÍ es terminal**: no acepta más ingresos (HTTP 409). Ver Decisión Abierta D4 (¿reabrir un `recibido` por devolución/error?).

---

## Scope

### ENTRA (in-scope)

**Backend**
- Ampliar `CheckConstraint` de `pedidos_compra.estado` con `recibido` y `con_faltantes` (migración Alembic).
- Adoptar/crear tabla `pedido_compra_ingresos` (si no fue creada por Slice 2 del change anterior — ver R-DUP).
- Endpoints de recepción: listar saldos por línea, registrar tanda de ingreso (por ítem), confirmar recepción a nivel pedido (sin OC), transición de estado, registro de evento de faltantes.
- JOIN a `productos_erp` en `orden-compra/detalle` para `item_nombre` (con fallback a `item_id`/código en ítems fantasma).
- Permiso nuevo `deposito.recibir_mercaderia` (seed en migración, sin asignación a rol).
- Tipos de evento nuevos en `compras_eventos`: `recepcion_registrada`, `recepcion_con_faltantes`.

**Frontend**
- Tab `deposito` en `AdministracionCompras.jsx`.
- Componente `TabRecepcionDeposito.jsx`: lista pedidos `pagado` (+ filtro `requiere_envio`), cada uno acordeón.
- Sub-vista por modo: por ítem (tilde + input + "marcar todo" + botones) / a nivel pedido (cartelito sin OC).
- Mini-modal "Cargar retiro" (lista direcciones proveedor + dispara `generar-etiqueta-envio`).
- Diseño visual generado con **stitch ANTES** de implementar la slice de frontend (ver §Stitch).

### NO ENTRA (out-of-scope)

1. **Escritura de stock / ERP**: la recepción NUNCA escribe stock ni toca mirrors ERP (read-only). Solo registra en `pedidos_compra` (estado) y `pedido_compra_ingresos`. (Espeja AD8 del change anterior.)
2. **Reabrir un pedido `recibido`** (devoluciones, correcciones post-cierre): diferido. Ver D4.
3. **Recepción de pedidos sin OC con detalle por ítem**: sin fuente de ítems no se modela; solo confirmación a nivel pedido.
4. **Notificación/alerta automática a compras** cuando queda `con_faltantes`: el evento queda registrado; el push/notificación se evalúa en change aparte. Ver D5.
5. **Filtrado por depósito/sucursal del operario logueado**: v1 muestra todos los depósitos; el filtro por `stor_id` del operario es refinamiento posterior. Ver D6.
6. **Montar TabEnviosFlex** o cualquier gestión de envíos más allá de disparar el retiro (LD5).
7. **Over-receipt con tolerancia configurable**: v1 bloquea exceso de saldo. Ver D3.

---

## Modelo de datos

### Estados (`pedidos_compra.estado`, `String(24)` + CheckConstraint)
Actuales: `borrador | pendiente_aprobacion | aprobado | rechazado | cancelado | pagado_parcial | pagado`.
**Nuevos**: `recibido`, `con_faltantes`.

Máquina de estados (subconjunto relevante):
```
pagado ──(tanda completa)──────────────► recibido        [terminal]
pagado ──(tanda parcial, saldo>0)──────► con_faltantes
con_faltantes ──(tanda parcial)────────► con_faltantes   [no terminal]
con_faltantes ──(tanda que completa)───► recibido        [terminal]
```

### Tabla `pedido_compra_ingresos` (append-only)
Definida en el design del change anterior (AD4). Campos: `id BIGSERIAL PK`, `pedido_id BIGINT FK RESTRICT`, snapshot de identidad de línea (`oc_comp_id`, `oc_bra_id`, `oc_poh_id`, `pod_id`), `item_id`, `stor_id`, `cantidad_recibida NUMERIC(18,6)` (CHECK > 0), `fecha_ingreso DATE default CURRENT_DATE`, `usuario_id FK RESTRICT`, `observaciones TEXT`, `created_at`. Índices `ix_pci_pedido`, `ix_pci_oc_linea`.

> **R-DUP**: confirmar en spec/design si Slice 2 del change anterior ya creó esta tabla. Si existe → este change solo la consume + agrega la capa de estados/UI. Si NO → la migración de esta tabla entra en la Slice A de este change. La fórmula de saldo y el grano `pod_id` se mantienen idénticos para no fragmentar la lógica.

### `compras_eventos` (sin cambios de schema, solo tipos nuevos)
`tipo ∈ {... , recepcion_registrada, recepcion_con_faltantes}`. `payload` JSONB con `{ lineas: [{ pod_id, item_id, cantidad_recibida, saldo_pendiente }], requiere_envio, retiro_generado }`.

---

## Superficie de API (endpoints nuevos)

Todos bajo el router de compras existente, gateados por `deposito.recibir_mercaderia` (ver D2 sobre coexistencia con `gestionar_ordenes_compra`).

| Método | Ruta | Propósito |
|--------|------|-----------|
| `GET` | `/pedidos/{id}/recepcion/saldos` | Líneas con `pod_qty`, recibido acumulado, `saldo_pendiente`, `item_nombre` (JOIN `productos_erp` + fallback). Indica si el pedido tiene OC vinculada. |
| `POST` | `/pedidos/{id}/recepcion/ingresos` | Registra una tanda: body `{ lineas: [{ pod_id, cantidad_recibida }], observaciones? }`. Inserta rows en `pedido_compra_ingresos`, recalcula saldos, transiciona estado (`recibido`/`con_faltantes`), emite evento. 409 si excede saldo. |
| `POST` | `/pedidos/{id}/recepcion/confirmar-pedido` | Modo SIN OC: confirma recepción a nivel pedido. Body `{ completo: bool, observaciones? }` → `recibido` o `con_faltantes`. Emite evento. |
| `GET` | `/pedidos/{id}/recepcion/eventos` | Historial de eventos de recepción del pedido (opcional; puede reusar endpoint de eventos existente filtrando por tipo). |

**Reuso (existentes, sin cambios)**: `GET /pedidos/{id}/orden-compra/detalle` (se le agrega el JOIN de nombre), `GET /proveedores/{id}/direcciones`, `POST /pedidos/{id}/generar-etiqueta-envio`.

> Nota de diseño: si el change anterior ya expuso `POST /pedidos/{id}/ingresos` (Slice 2), evaluar consolidar contra `/recepcion/ingresos` en lugar de duplicar. Ver R-DUP + D2.

---

## Archivos afectados (estimado)

**Backend**
- `backend/app/models/pedido_compra.py` — ampliar CheckConstraint de `estado`.
- `backend/app/models/pedido_compra_ingreso.py` — modelo (si no existe del change anterior).
- `backend/app/models/compra_evento.py` — tipos de evento nuevos en CheckConstraint.
- `backend/app/services/oc_ingresos_service.py` — JOIN `productos_erp` en detalle; lógica de saldos/recepción/transición.
- `backend/app/routers/administracion_compras.py` — endpoints de recepción.
- `backend/app/schemas/oc_ingreso.py` — schemas request/response de recepción.
- Migración Alembic: `YYYYMMDD_add_recepcion_estados_y_permiso_deposito.py` (+ tabla ingresos si aplica).
- Seed de permiso `deposito.recibir_mercaderia`.

**Frontend**
- `frontend/src/pages/AdministracionCompras.jsx` — entrada en array TABS.
- `frontend/src/components/compras/TabRecepcionDeposito.jsx` — vista principal.
- `frontend/src/components/compras/ModalCargarRetiro.jsx` — mini-modal de retiro.
- `frontend/src/hooks/useComprasPedidos.js` (o hook de recepción dedicado) — llamadas a los endpoints nuevos.
- CSS Modules + tokens Tesla; iconos `lucide-react`.

**Tests (Strict TDD — pytest)**
- `backend/tests/integration/test_recepcion_deposito_endpoints.py` — saldos, ingreso tanda (parcial/completa), transiciones de estado, 409 over-receipt, modo sin OC, 403 sin permiso, evento emitido, recepción nunca escribe stock.

---

## Delivery — Slices (stacked-to-main)

Change grande → se corta en 2 slices stacked-to-main (chain strategy ya elegida). Cada slice apunta a ~400 líneas; riesgo de presupuesto de review **alto** en ambas.

### Slice A — Backend (recepción + estados + permiso)
Migración (estados + permiso + tabla ingresos si no existe) · modelo · servicio de saldos/recepción/transición · JOIN nombre ítems · endpoints `/recepcion/*` · eventos · tests de integración.
**Límite**: termina cuando los endpoints pasan tests con dato real (incluyendo modo sin OC y 403 sin permiso). **Riesgo de budget**: alto (~400 líneas incl. tests).

### Slice B — Frontend (tab depósito + UI recepción + mini-modal retiro)
Tab `deposito` · `TabRecepcionDeposito.jsx` (acordeón, tilde/inputs, "marcar todo", botones) · `ModalCargarRetiro.jsx` · hook · estilos Tesla.
**Precede**: generación de diseño con **stitch** (ver abajo). **Límite**: UI funcional contra los endpoints de Slice A. **Riesgo de budget**: alto.

> Slice B **depende** de Slice A mergeada. Stacked-to-main: A → main, luego B → main.

---

## Dónde entra Stitch

El **diseño visual del frontend (Slice B) se genera con stitch ANTES de implementar la slice**. Concretamente:
- Antes de escribir `TabRecepcionDeposito.jsx` y `ModalCargarRetiro.jsx`, se produce con stitch el mockup/layout de: la lista de pedidos con acordeón, la tabla de ítems con tilde + input + "marcar todo", la barra de acciones ("Recibido" / "Marcar con faltantes"), el cartelito "falta vincular OC", y el mini-modal de retiro.
- El resultado de stitch alimenta la implementación con tokens Tesla + `lucide-react`. Queda explícito como **gate previo a Slice B** en el plan de tasks.

---

## Riesgos

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|-----------|
| R1 | **Ítems fantasma**: `item_id` del ERP sin match en `productos_erp` (visto en `pedidos_preparacion.py:254`). | La línea aparece sin nombre legible; el operario no sabe qué recibir. | Fallback: mostrar `item_id`/código como nombre. El JOIN es LEFT, nunca filtra la línea. Test de integración con un ítem sin match. |
| R2 | **Pedidos SIN OC vinculada**: no hay fuente de ítems. | No se puede recibir por línea. | Modo a nivel pedido (cartelito + confirmar completo/faltantes). UX explícita "falta vincular OC". |
| R3 | **Over-receipt**: recibir más que el saldo. | Datos de recepción inconsistentes vs. lo pedido. | v1: bloqueo (409 si tanda > saldo). Decisión D3 para tolerancia futura. |
| R4 | **Re-apertura / estado terminal**: `recibido` terminal vs. `con_faltantes` no terminal. | Confusión si un pedido `recibido` necesita corrección. | v1: `recibido` rechaza ingresos (409). Reapertura diferida (D4). `con_faltantes` siempre acepta tandas. |
| R-DUP | **Duplicación con Slice 2 del change anterior**: tabla `pedido_compra_ingresos` y `POST .../ingresos` ya estaban diseñados allí. | Dos tablas/endpoints para lo mismo; lógica de saldo fragmentada. | **Confirmar en spec/design** el estado real de Slice 2. Consolidar: una sola tabla, una sola fórmula de saldo, endpoints unificados bajo `/recepcion/*` o reuso del existente. BLOQUEANTE antes de tasks. |
| R5 | **Permiso nuevo sin asignar**: `deposito.recibir_mercaderia` no se asigna a ningún rol. | Nadie puede usar la tab hasta asignarlo. | Seed crea el permiso, no lo asigna. Documentar en onboarding a quién dárselo. |
| R6 | **Coexistencia de permisos en POST ingresos** (D2): ¿el admin de compras también puede registrar ingresos? | Bloqueo operativo si solo depósito puede. | Definir en spec: probablemente el endpoint acepta `deposito.recibir_mercaderia` OR `administracion.gestionar_ordenes_compra`. |

---

## Decisiones Abiertas (confirmar antes de spec/design)

- **D1** — ¿Alcanza `con_faltantes` como "parcial", o el negocio quiere un estado explícito `recepcion_parcial` distinto de "faltante reclamable"? (Propuesta: alcanza `con_faltantes`.)
- **D2** — ¿El `POST /recepcion/ingresos` acepta solo `deposito.recibir_mercaderia`, o también `administracion.gestionar_ordenes_compra` (para que compras pueda registrar)? (Propuesta: ambos.)
- **D3** — Over-receipt: ¿bloqueo duro (409) o permitir con tolerancia/observación? (Propuesta v1: bloqueo.)
- **D4** — ¿Se necesita reabrir un pedido `recibido` (devolución, error de carga)? (Propuesta v1: no, diferido.)
- **D5** — ¿Notificación a compras cuando queda `con_faltantes`? (Propuesta v1: solo evento, sin push.)
- **D6** — ¿La tab filtra por depósito/sucursal del operario logueado? (Propuesta v1: muestra todos.)
- **R-DUP** — Estado real de Slice 2 del change anterior (tabla + endpoint ingresos). **Bloqueante.**

---

## Criterios de aceptación (alto nivel)

- [ ] Un operario con `deposito.recibir_mercaderia` ve la tab `deposito` con los pedidos `pagado`; sin el permiso, no la ve y los endpoints devuelven 403.
- [ ] Pedido CON OC: el operario registra una tanda parcial → estado pasa a `con_faltantes`, se crean rows en `pedido_compra_ingresos`, se emite evento `recepcion_con_faltantes` con el detalle de saldos.
- [ ] Una segunda tanda que completa los saldos → estado `recibido`, evento `recepcion_registrada`. El pedido `recibido` rechaza nuevos ingresos (409).
- [ ] Recibir más que el saldo de una línea → 409 (over-receipt bloqueado v1).
- [ ] Pedido SIN OC: muestra cartelito "falta vincular OC" y permite confirmar a nivel pedido (`recibido` o `con_faltantes`).
- [ ] Ítem fantasma (sin match en `productos_erp`): la línea se muestra con `item_id`/código como fallback, no se pierde.
- [ ] Pedido `requiere_envio=true`: el mini-modal lista direcciones del proveedor y dispara `generar-etiqueta-envio` creando la `EtiquetaEnvio` tipo `retiro_proveedor`; sin montar TabEnviosFlex.
- [ ] La recepción NUNCA escribe stock ni toca mirrors ERP (verificado por test).
- [ ] El diseño de Slice B se generó con stitch antes de implementar la UI.

---

## Next Steps

1. **Resolver D1–D6 + R-DUP** (R-DUP es bloqueante: confirmar estado de Slice 2 anterior).
2. **sdd-spec** → delta specs por capability: recepcion-saldos, recepcion-ingresos, estados-pedido, permiso-deposito, retiro-proveedor, eventos-recepcion.
3. **sdd-design** → fórmula de saldo consolidada, máquina de estados, contrato de over-receipt, JOIN nombre ítems, decisión de consolidación con tabla del change anterior.
4. **Stitch** → mockups de Slice B (gate previo a su implementación).
5. **sdd-tasks → apply → verify** por slice (A backend, B frontend), stacked-to-main.
