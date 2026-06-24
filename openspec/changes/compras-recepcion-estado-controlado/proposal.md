# Proposal — Recepción en Dos Pasos: estado `recibido` (llegó) + `controlado` (chequeado)

**Change ID:** `compras-recepcion-estado-controlado`
**Fase:** proposal
**Status:** draft
**Owner:** Compras + Depósito
**Fecha:** 2026-06-24
**Persistence:** hybrid (este archivo + engram `sdd/compras-recepcion-estado-controlado/proposal`)
**Supersede a:** `compras-recepcion-deposito` — **decisión D4** (que declaró `recibido` terminal y dejó la re-apertura fuera de alcance). Este change cambia deliberadamente la semántica de `recibido`: deja de ser "terminal/chequeado" para ser "llegó pero falta controlar".

---

## Why

Hoy el circuito de recepción de depósito (entregado por `compras-recepcion-deposito`) tiene **un solo evento de cierre**: cuando el operario marca `recibido`, el pedido queda terminal y se asume que llegó Y se controló en un mismo acto. Esto **fusiona dos hechos de negocio distintos**:

1. **La mercadería LLEGÓ físicamente al depósito** (hecho de logística, inmediato).
2. **La mercadería FUE CONTROLADA** (conteo/chequeo contra lo pedido, puede tardar horas o días).

Problema concreto: **los vendedores no tienen visibilidad de que el producto YA llegó** hasta que alguien termina de controlarlo. Si la mercadería entró al depósito a la mañana pero el control recién se hace a la tarde, un vendedor que consulta el sistema sigue viendo el pedido como `pagado` (sin novedad), pierde una venta o le dice al cliente "todavía no llegó" cuando físicamente ya está en el galpón.

El negocio necesita **separar la llegada del control**:

- **`recibido`** = "llegó, ya está en el depósito" → señal temprana y visible para ventas, aunque todavía no se haya contado.
- **`controlado`** = "llegó Y se chequeó OK" → cierre real del circuito (lo que hoy significa `recibido`).

Esto convierte la recepción en un **proceso de dos pasos** (arribo → control) en vez de un único acto, sin agregar permisos ni romper la trazabilidad ya construida.

### Por qué supera la D4 del change anterior

El change `compras-recepcion-deposito` (D4) declaró `recibido` **terminal** y dejó explícitamente fuera de alcance "reabrir un pedido recibido". Esa decisión asumía que llegada y control eran el mismo evento. La realidad operativa mostró que **no lo son**: el operario quiere registrar el arribo apenas baja del camión y dejar el control para después. Este change reabre esa decisión de diseño de forma controlada — no agregando "re-apertura" arbitraria, sino **insertando un paso intermedio legítimo** (`recibido`) antes del nuevo terminal (`controlado`).

---

## What

Recepción de depósito pasa de un acto único a un **flujo de dos pasos gateado por estado**, reutilizando la infraestructura existente (servicio, endpoints, permiso, tabla de ingresos, eventos). No hay tablas nuevas ni permisos nuevos.

### Máquina de estados objetivo (LOCKED)

```
pagado          ──[Recibido]──────►  recibido       (llegó, NO controlado aún)
recibido        ──[Controlado]────►  controlado     (terminal — "chequeado OK")
recibido        ──[Con faltantes]─►  con_faltantes
con_faltantes   ──[Controlado]────►  controlado     (una vez resuelto el faltante)
```

- **Estados receptivos (accionables)**: `pagado` (→`recibido`), `recibido` (→`controlado` / `con_faltantes`), `con_faltantes` (→`controlado`).
- **Terminal**: `controlado`.
- `con_faltantes` deja de ser un loop sobre sí mismo: ahora es **intermedio** y resuelve hacia `controlado`.

### Decisiones de producto cerradas (LOCKED — no se re-litigan)

1. **Renombrar** el estado actual `recibido` (que hoy significa "recibido completo + controlado") → **`controlado`** (nuevo terminal).
2. **Agregar** un nuevo estado `recibido` con **nuevo significado** = llegó pero no fue controlado.
3. **Propósito de negocio**: los vendedores ven que el producto LLEGÓ antes de que se termine el control.
4. **Permisos**: las TRES acciones (Recibido / Controlado / Con faltantes) usan el gate existente `deposito.recibir_mercaderia`. **No se crea permiso nuevo.**
5. **`con_faltantes` es INTERMEDIO** (no terminal): transiciona a `controlado` una vez resuelto el faltante.
6. **Tabs de filtro (UI depósito)**: "Por recibir" (`pagado`) · "Recibidos sin controlar" (`recibido`) · "Controlados" (`controlado`) · "Con faltantes" (`con_faltantes`).
7. **Badge**: `recibido` → tono ámbar/"parcial", label "Recibido"; `controlado` → tono verde/"pagado", label "Controlado"; `con_faltantes` sin cambios.
8. **Migración de datos**: filas existentes con el viejo `recibido` → `controlado` (one-way, documentada). El usuario puede borrar datos por separado; igual se escribe la migración como default seguro.
9. **Gating de botones en frontend** (ambas ramas CON-OC y SIN-OC):
   - `estado == pagado` → botón **"Recibido"**.
   - `estado == recibido` → botones **"Controlado"** + **"Con faltantes"**.
   - `estado == con_faltantes` → botón **"Controlado"**.

### Alcance del cambio (qué se toca)

**Backend — máquina de estados + migración**
- Ampliar el `CheckConstraint` de `pedidos_compra.estado` para incluir `controlado` (manteniendo `recibido` y `con_faltantes`). Nueva lista completa: `borrador, pendiente_aprobacion, aprobado, rechazado, cancelado, pagado_parcial, pagado, recibido, con_faltantes, controlado`.
  Ref: `backend/app/models/pedido_compra.py` L144-148 (CheckConstraint).
- Migración Alembic siguiendo el patrón DROP+ADD de `backend/alembic/versions/20260618_recepcion_deposito.py`, con **data migration ordenada**:
  1. `UPDATE pedidos_compra SET estado='controlado' WHERE estado='recibido';`
  2. DROP constraint viejo.
  3. ADD constraint nuevo (incluye `recibido` con su nuevo significado + `controlado`).
- Ampliar `ESTADOS_PEDIDO` (tuple) en `backend/app/schemas/pedido_compra.py` L19-29 con `controlado`.

**Backend — servicio de recepción** (`backend/app/services/recepcion_service.py`)
- `_ESTADOS_RECEPTIVOS`: pasa de `{pagado, con_faltantes}` a `{pagado, recibido, con_faltantes}` (L50) — ahora `recibido` es receptivo (acepta transición a `controlado`/`con_faltantes`).
- Guard de terminal `_validar_estado_receptivo` (L58-74, especialmente L65): el rechazo 409 "ya recibido" pasa a ser sobre `controlado` (nuevo terminal), no sobre `recibido`.
- `recalcular_estado` (L199-215, asignación L213): la lógica de transición debe distinguir arribo (`pagado→recibido`) de control (`recibido→controlado`/`con_faltantes`). **Cómo se decide controlado vs recibido en el camino SIN-OC depende del flag `completo:bool` — ver Decisión Abierta D-SINOC.**
- Branch de evento (L336) y `confirmar_pedido_sin_oc` (L399+, asignación L438): alinear con el nuevo terminal.

**Backend — endpoints** (`backend/app/routers/administracion_compras.py`)
- `GET /pedidos/{id}/recepcion/saldos` (L4917): el set de estados visibles ya incluye `recibido`; agregar `controlado` donde corresponda y validar que `recibido` (nuevo significado) siga mostrando saldos.
- `POST /pedidos/{id}/recepcion/ingresos` (L4925+, CON OC): ahora debe poder accionar tanto el arribo como el control según el estado actual del pedido.
- `POST /pedidos/{id}/recepcion/confirmar-pedido` (L4959+, SIN OC): mismo flujo de dos pasos para pedidos sin OC vinculada.

**Frontend** (`frontend/src/components/compras/TabRecepcionDeposito.jsx`)
- `FILTER_TABS` (L18-22): redefinir a las 4 tabs lockeadas (Por recibir / Recibidos sin controlar / Controlados / Con faltantes) y su mapeo de `?estado=` (L536-540).
- `estadoBadge` local (L24-35, case `recibido` L30) y mapping de botones: gating por estado según LD9, en ambas ramas CON-OC (`AccordionBodyConOc`, botón actual L313) y SIN-OC (`AccordionBodySinOc`, botón actual L386). Mensajes de éxito (L346) a alinear.
- `frontend/src/components/compras/_shared/EstadoBadge.jsx` (`MAPPING_PEDIDO`, key `recibido` L41): `recibido` → tono "parcial"/ámbar label "Recibido"; agregar `controlado` → tono "pagado"/verde label "Controlado".

**Tests (Strict TDD — pytest)** (`backend/tests/integration/test_recepcion_deposito_endpoints.py`)
- ~60 assertions existentes referencian `recibido` como terminal → renombrar a `controlado`. Algunas **INVIERTEN su semántica**: tests que afirmaban `recibido → 409 (terminal)` ahora deben afirmar `controlado → 409`, y `recibido` debe **aceptar** ingresos (control).
- Tests nuevos: `pagado→recibido` (arribo intermedio), `recibido→controlado`, `recibido→con_faltantes`, `con_faltantes→controlado`.

---

## Blast radius del rename (inventario del explore)

El rename `recibido(viejo) → controlado` y la re-semantización de `recibido(nuevo)` impactan **solo** estas referencias de estado (el explore separó cuidadosamente las que NO son estado):

**Backend — referencias de estado (cambian):**
- `recepcion_service.py` L65 (guard terminal), L213 (asignación en `recalcular_estado`), L336 (branch de evento), L438 (asignación en `confirmar_sin_oc`).
- `administracion_compras.py` L4917 (set visible de saldos).
- `pedido_compra.py` L146 (literal del CheckConstraint).
- `pedido_compra.py` schemas L27 (tuple `ESTADOS_PEDIDO`).

**Backend — NO impactadas (falsos positivos confirmados por el explore):**
- `recepcion_service.py` L151, L158, L173-174, L185 → alias SQL y var Python `recibido_pricing` (NO es el estado).
- `cheques_service.py` L621 → evento de cheque `'recibido'` (**dominio distinto, NO tocar**).
- `ncs_locales_service.py`, `ordenes_pago_service.py`, `st_app.py`, scripts → strings no relacionados.

**Frontend — referencias de estado (cambian):**
- `TabRecepcionDeposito.jsx` L30 (case en `estadoBadge`), L313 (texto botón), L346 (mensaje éxito), L386 (botón SIN-OC), L537 (mapeo `?estado=`).
- `EstadoBadge.jsx` L41 (key `MAPPING_PEDIDO`).

---

## Scope — NO ENTRA (out-of-scope / non-goals)

1. **Permiso nuevo**: NO se crea. Las tres acciones usan `deposito.recibir_mercaderia` (LD4).
2. **Evento de cheque `'recibido'`** (`cheques_service.py` L621): es de otro dominio, NO se toca.
3. **Integración RMA / devoluciones**: fuera de alcance.
4. **Reabrir un `controlado`** (corrección post-cierre): el downgrade es **one-way**. Una vez `controlado`, no se vuelve atrás en v1.
5. **Notificación push a ventas** cuando un pedido pasa a `recibido`: el estado queda visible (badge/filtro), pero el push/alerta automática es un change aparte.
6. **Tabla, fórmula de saldo y lógica de ingresos acumulativos**: se reutilizan tal cual del change anterior. Este change solo cambia la **capa de estados + UI de gating**, no el modelo de ingresos.
7. **Reversa de la migración de datos**: el `downgrade()` no puede reconstruir qué filas eran `recibido(viejo)` vs `recibido(nuevo)` — la migración es **irreversible en la práctica** (ver Riesgos).

---

## First-slice scope boundary (estimación para el delivery guard)

Cambio **transversal pero de superficie acotada** (rename + un estado + gating). Estimación gruesa de líneas cambiadas:

- **Backend**: migración (~40) + constraint/schema/servicio/endpoints (~120) ≈ **~160 líneas**.
- **Tests**: ~60 assertions a renombrar/invertir + ~6 tests nuevos ≈ **~150-200 líneas** (la parte más pesada por la inversión semántica).
- **Frontend**: filter tabs + gating + badge en 2 archivos ≈ **~80-120 líneas**.

**Total estimado ≈ 400-480 líneas.** Esto **roza/supera el presupuesto de 400 líneas** principalmente por el volumen de tests. Recomendación para el delivery guard:

- **Opción preferida**: 2 slices stacked-to-main — **Slice A = Backend** (migración + estados + servicio + endpoints + tests, donde vive el grueso y el riesgo) y **Slice B = Frontend** (filter tabs + gating + badge). Slice B depende de A mergeada.
- **Opción alternativa**: PR único con `size:exception` justificado (el rename es atómico y dividirlo deja estados inconsistentes a mitad de camino entre BE y FE). Decidirlo en el guard previo a apply según `delivery_strategy`.

Se **flaggea explícitamente** que la estimación supera 400 líneas para que el guard actúe.

---

## Riesgos

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|-----------|
| R1 | **Migración de datos irreversible**: el `UPDATE recibido→controlado` no se puede revertir (el `downgrade` no distingue origen). | Si se aplica en prod y hay que volver atrás, se pierde la distinción. | Documentar como one-way. `downgrade()` solo revierte el constraint, no los datos (deja constancia en el docstring). El usuario podría wipear datos por separado; igual se entrega la migración como default seguro. |
| R2 | **~60 assertions a actualizar, algunas que INVIERTEN semántica**: tests que afirmaban `recibido` terminal (409) ahora deben afirmar `controlado` terminal y `recibido` receptivo. | Alto riesgo de tests "renombrados pero no invertidos" → falsos verdes. | Strict TDD: primero hacer fallar los tests con la nueva semántica (incluido el caso invertido), luego implementar. Revisar caso por caso los que tocan el guard terminal. |
| R3 | **Semántica del flag `completo:bool` en SIN-OC**: hoy `confirmar_pedido_sin_oc` decide `recibido(viejo terminal)` vs `con_faltantes` con un `completo:bool`. Con dos pasos, ¿`completo=true` significa arribo (→`recibido`) o control OK (→`controlado`)? | Sin decisión clara, el camino SIN-OC queda ambiguo y puede saltar el paso intermedio. | **Decisión Abierta D-SINOC** (al design): definir cómo el SIN-OC distingue arribo de control (probablemente el endpoint pasa a recibir la acción objetivo según estado actual, no solo `completo:bool`). |
| R4 | **Colisión de labels en filter tabs**: "Recibidos sin controlar" (`recibido`) vs el viejo tab "Recibidos" que ahora mapea a `controlado`. | Operario confunde qué tab muestra qué. | Labels lockeados explícitos (LD6): "Por recibir" / "Recibidos sin controlar" / "Controlados" / "Con faltantes". Verificar que el mapeo `?estado=` (L537) coincida 1:1 con cada label. |
| R5 | **Re-semantización silenciosa de `recibido`**: el string no cambia, pero su significado sí (de terminal a intermedio). | Cualquier consumidor externo que asuma `recibido`=terminal rompe. | El inventario del explore confirma que NO hay consumidores externos del estado fuera del módulo de recepción. Documentar el cambio de significado en el design y en `compras_eventos`. |
| R6 | **`con_faltantes` cambia de loop a intermedio**: antes loopeaba; ahora resuelve a `controlado`. | Tests/lógica que asumían `con_faltantes` no-terminal-loop deben ajustarse. | Cubierto por el rediseño de `recalcular_estado` y nuevos tests `con_faltantes→controlado`. |

---

## Decisiones Abiertas (diferidas a design)

- **D-SINOC** *(la más importante)* — **¿Cómo dispara el camino SIN-OC `controlado` vs `recibido` dado el flag `completo:bool` actual?** Hoy `POST /recepcion/confirmar-pedido` recibe `{completo: bool}` y decide `recibido`/`con_faltantes`. Con el flujo de dos pasos hay que definir si:
  - el endpoint pasa a interpretar la acción según el `estado` actual del pedido (pagado→recibido; recibido→controlado/con_faltantes), o
  - se agrega un campo de acción explícito al body, o
  - `completo:bool` se reinterpreta (completo=control OK→controlado; incompleto→con_faltantes), asumiendo el arribo como paso previo separado.
  **Bloqueante para spec/design del camino SIN-OC.**
- **D-CONOC** — En el camino CON-OC, ¿el arribo (`pagado→recibido`) se registra **sin** tocar ingresos por línea (solo cambio de estado), y el control (`recibido→controlado`) es el que valida saldos? ¿O el arribo ya exige cargar ingresos? Definir en design la relación entre el botón "Recibido" y la tabla `pedido_compra_ingresos`.
- **D-MIGRACION-WIPE** — Confirmar con el usuario si va a wipear datos (en cuyo caso el `UPDATE` es defensivo/no-op) o si hay filas reales `recibido(viejo)` en prod que dependen del `UPDATE`. No bloqueante para escribir la migración (se entrega como default seguro).

---

## Criterios de aceptación (alto nivel)

- [ ] Un operario con `deposito.recibir_mercaderia` ve las 4 tabs (Por recibir / Recibidos sin controlar / Controlados / Con faltantes) con el mapeo de estado correcto.
- [ ] Pedido `pagado` muestra botón "Recibido"; al accionarlo → estado `recibido`, badge ámbar "Recibido".
- [ ] Pedido `recibido` muestra botones "Controlado" y "Con faltantes"; "Controlado" → terminal, badge verde "Controlado".
- [ ] Pedido `con_faltantes` muestra botón "Controlado"; al resolver → `controlado`.
- [ ] El nuevo terminal `controlado` rechaza nuevos ingresos (409); `recibido` los **acepta** (control).
- [ ] La migración convierte filas viejas `recibido` → `controlado` antes de aplicar el nuevo constraint; `downgrade` revierte solo el constraint (documentado como one-way en datos).
- [ ] Ambas ramas CON-OC y SIN-OC siguen el mismo gating de botones por estado.
- [ ] El evento de cheque `'recibido'` (otro dominio) NO se ve afectado.
- [ ] Tests: las ~60 assertions están renombradas Y las que correspondían al guard terminal están **invertidas** correctamente; existen tests para `pagado→recibido`, `recibido→controlado`, `recibido→con_faltantes`, `con_faltantes→controlado`.

---

## Next Steps

1. **Resolver D-SINOC y D-CONOC** en design (D-SINOC es bloqueante para el camino sin OC).
2. **sdd-spec** → delta specs: estados-pedido (rename + nuevo intermedio), recepcion-arribo (`pagado→recibido`), recepcion-control (`recibido→controlado`/`con_faltantes`), filter-tabs, badge-mapping, data-migration.
3. **sdd-design** → máquina de estados final, contrato del camino SIN-OC (D-SINOC), relación botón "Recibido" ↔ ingresos (D-CONOC), orden exacto de la data migration.
4. **sdd-tasks → apply → verify** — aplicar Review Workload Guard (estimación ~400-480 líneas → evaluar 2 slices stacked-to-main vs PR único con `size:exception`).
