# Proposal — Vincular Orden de Compra del ERP al Pedido + Ingreso por Depósito

**Change ID:** `compras-vincular-orden-compra-erp`
**Fase:** proposal
**Status:** draft
**Owner:** Compras (PM) + Backend Lead
**Fecha:** 2026-06-18

---

## Why

En el módulo de compras, el detalle del pedido (`ModalPedidoDetalle.jsx`) ya permite vincular una **factura del ERP** al pedido (vía `ModalVincularFactura`). Pero falta el otro extremo del circuito de abastecimiento: **la Orden de Compra (OC)**.

El quilombo concreto hoy:

1. **No hay trazabilidad pedido ↔ OC.** El pedido de compra cargado en el pricing-app no se cruza con la Orden de Compra real que vive en el ERP (`tb_purchase_order_header` / `tb_purchase_order_detail`, ya sincronizadas y read-only). Saber "qué OC originó este pedido" es manual: alguien lo busca en el ERP.
2. **No se ve el desglose a depósito.** Cada línea de la OC en el ERP ya trae `stor_id` (a qué depósito entra cada ítem y en qué cantidad). Esa información existe pero NO se muestra en el pricing-app. El equipo no sabe, desde el pedido, qué mercadería va a entrar a cada depósito.
3. **El ingreso por depósito se confirma a mano / no se registra.** Cuando la mercadería de la OC efectivamente llega, no hay forma en el pricing-app de **confirmar el ingreso por depósito** (qué se recibió realmente, cuánto, cuándo, quién). No queda registro propio del acto de recepción.

El patrón de vinculación de factura ya está validado en producción. Esta feature lo **espeja** para OCs y agrega la capa de recepción.

---

## What

Permitir, desde el detalle del pedido de compra:

1. **Vincular / desvincular / re-vincular** una Orden de Compra del ERP al pedido (mutable), espejando exactamente el flujo de `ModalVincularFactura`.
2. **Ver el desglose a depósito** (read-only) de la OC vinculada: ítems y cantidades por depósito, leídos de `tb_purchase_order_detail.stor_id` + `tb_storage`.
3. **Confirmar el ingreso por depósito**: registrar en una tabla NUEVA del pricing-app la recepción real de mercadería por depósito (qué se recibió, cuánto, cuándo, quién confirmó).

Las tablas del ERP (`tb_purchase_order_header`, `tb_purchase_order_detail`, `tb_storage`) son **mirrors read-only**: NUNCA se escribe en ellas. El vínculo y el registro de ingreso viven en NUESTRAS tablas.

---

## Decisiones de producto FIJAS (cerradas por el usuario)

Estas cuatro decisiones NO se discuten en esta fase — el diseño se construye alrededor de ellas:

### D1 — Cardinalidad: uno a uno
Un pedido ↔ una OC. El vínculo se guarda como **3 columnas nullable** sobre `pedidos_compra` (`oc_comp_id`, `oc_bra_id`, `oc_poh_id`), NO una tabla join. Espeja cómo la factura guarda `ct_transaction_id` (FK lógica, sin constraint físico contra el mirror del ERP).

### D2 — Desglose CON confirmar ingreso (no solo display)
Dos capas:
- **(a)** Vista read-only de ítems/cantidad por depósito, joineando `tb_purchase_order_detail.stor_id` con `tb_storage`.
- **(b)** Workflow para confirmar/registrar el ingreso real por depósito, persistido en una **tabla nueva** (`pedido_compra_ingresos` o similar).

### D3 — Candidatas: solo OCs abiertas/pendientes del proveedor
El listado de OCs candidatas se filtra por `supp_id` del proveedor (mismo patrón que factura) **y** por estado "pendiente de recepción". **El campo exacto del ERP que marca "pendiente" es una incógnita abierta** (el explore sugirió `pho_selectedinrecepcion` pero NO está confirmado). Ver Riesgo R1 — esto se resuelve en `sdd-design`, no se hardcodea acá.

### D4 — Mutable: sí
Vincular + desvincular + re-vincular, espejando el `desvincular-factura` existente.

---

## Scope — DOS SLICES SECUENCIALES

La feature se entrega en **dos slices encadenados** para mantener cada PR revisable (presupuesto ~400 líneas por PR; el confirmar-ingreso es no trivial y empujaría un solo PR por encima del presupuesto).

### Slice 1 — Vínculo OC + desglose read-only (ENTRA primero)

**Backend:**
- 3 columnas nullable en `pedidos_compra`: `oc_comp_id` (Integer), `oc_bra_id` (Integer), `oc_poh_id` (BigInteger). Índice parcial sobre `oc_poh_id IS NOT NULL`.
- `GET /administracion/compras/pedidos/{id}/oc-candidatas` — lista OCs del proveedor (`supp_id`) filtradas por "pendiente de recepción" (campo a confirmar en design), excluyendo la ya vinculada.
- `POST /administracion/compras/pedidos/{id}/vincular-oc` — body `{ comp_id, bra_id, poh_id }`. Setea las 3 columnas.
- `DELETE /administracion/compras/pedidos/{id}/desvincular-oc` — limpia las 3 columnas (re-vincular = desvincular + vincular).
- `GET /administracion/compras/pedidos/{id}/orden-compra/detalle` — desglose read-only: ítems/cantidades por depósito (join `tb_purchase_order_detail` + `tb_storage`).
- Permiso: `administracion.gestionar_ordenes_compra` (el mismo que gatea el flujo factura — confirmado en explore).

**Frontend:**
- `ModalVincularOC.jsx` — sub-modal espejo de `ModalVincularFactura.jsx`: tabla con radio-select de OC candidatas.
- Sección de desglose por depósito (read-only) dentro de `ModalPedidoDetalle.jsx` cuando hay OC vinculada.
- Botones vincular / desvincular en `ModalPedidoDetalle.jsx`, gateados por permiso.

### Slice 2 — Confirmar ingreso por depósito (ENTRA después)

**Backend:**
- Tabla nueva `pedido_compra_ingresos` (sketch abajo): registra recepción real por depósito.
- `POST /administracion/compras/pedidos/{id}/ingresos` — confirma ingreso de uno o varios renglones por depósito.
- `GET /administracion/compras/pedidos/{id}/ingresos` — lista ingresos confirmados del pedido.
- (Posible) `DELETE`/anulación de un ingreso confirmado — a definir en design según política de corrección.
- Permiso: a definir en design — reusar `administracion.gestionar_ordenes_compra` o agregar `administracion.confirmar_ingreso_compra` (confirmar ingreso es un acto operativo distinto de vincular).

**Frontend:**
- Workflow de confirmación de ingreso por depósito dentro de `ModalPedidoDetalle.jsx` (o sub-modal `ModalConfirmarIngreso.jsx`): sobre el desglose read-only, permitir registrar cantidades recibidas por depósito.
- Vista del estado de ingresos (qué ya se confirmó vs qué falta).

### Out of Scope (este change)

1. **Cardinalidad muchos-a-muchos** (pedido ↔ varias OCs, entregas parciales por múltiples OCs). Cerrado por D1: uno a uno.
2. **Escritura al ERP** (registrar la recepción de vuelta en `tb_purchase_order_detail.pod_confirmedqty`). Solo leemos del ERP; el registro de ingreso es propio del pricing-app. Reconciliación bidireccional → futuro.
3. **Auto-match OC por fecha/monto.** Selección manual por el usuario (espeja factura).
4. **Movimientos de stock** (`stock_por_deposito`) derivados del ingreso confirmado. Este change registra el ingreso; el impacto en stock es un change aparte.
5. **Aprobación/workflow de estados del ingreso** (multi-paso). Slice 2 registra el ingreso; si se requiere flujo de aprobación de recepción, va a un change futuro.

---

## Data model

### Modificación a `pedidos_compra` (Slice 1) — backward-compatible, todo nullable

```python
# backend/app/models/pedido_compra.py
oc_comp_id = Column(Integer, nullable=True)   # FK lógica a tb_purchase_order_header.comp_id
oc_bra_id  = Column(Integer, nullable=True)   # tb_purchase_order_header.bra_id
oc_poh_id  = Column(BigInteger, nullable=True) # tb_purchase_order_header.poh_id
# Índice parcial: oc_poh_id IS NOT NULL
```

Migración Alembic `YYYYMMDD_add_oc_link_to_pedidos_compra.py`: 3 `op.add_column` + índice parcial. Sin FK físico (mirror read-only, mismo criterio que `ct_transaction_id`).

### Tabla nueva `pedido_compra_ingresos` (Slice 2) — sketch

```python
# backend/app/models/pedido_compra_ingreso.py  (tabla: pedido_compra_ingresos)
id              = Column(BigInteger, primary_key=True)
pedido_id       = Column(BigInteger, ForeignKey("pedidos_compra.id"), nullable=False, index=True)
# Identidad de la línea de OC recibida (read-only del ERP, sin FK físico):
oc_comp_id      = Column(Integer, nullable=False)
oc_bra_id       = Column(Integer, nullable=False)
oc_poh_id       = Column(BigInteger, nullable=False)
pod_id          = Column(Integer, nullable=False)   # línea de detalle de la OC
item_id         = Column(BigInteger, nullable=False)
stor_id         = Column(Integer, nullable=False)   # depósito al que ingresa
cantidad_recibida = Column(Numeric, nullable=False)
fecha_ingreso   = Column(DateTime, default=lambda: datetime.now(UTC))
usuario_id      = Column(Integer, ForeignKey(...), nullable=False)  # quién confirmó
observaciones   = Column(String, nullable=True)
created_at / updated_at
# Índice: (pedido_id), (oc_comp_id, oc_bra_id, oc_poh_id, pod_id)
```

Estructura exacta (granularidad: ¿un registro por línea-depósito o un header de ingreso con líneas? ¿cantidad parcial acumulada vs total?) se cierra en `sdd-design`.

---

## API surface (espejando los endpoints de factura)

| Método | Ruta | Slice | Espeja |
|--------|------|-------|--------|
| GET | `/administracion/compras/pedidos/{id}/oc-candidatas` | 1 | `facturas-candidatas` |
| POST | `/administracion/compras/pedidos/{id}/vincular-oc` | 1 | `vincular-factura` |
| DELETE | `/administracion/compras/pedidos/{id}/desvincular-oc` | 1 | `desvincular-factura` |
| GET | `/administracion/compras/pedidos/{id}/orden-compra/detalle` | 1 | (nuevo — desglose) |
| GET | `/administracion/compras/pedidos/{id}/ingresos` | 2 | (nuevo) |
| POST | `/administracion/compras/pedidos/{id}/ingresos` | 2 | (nuevo) |

Todos bajo el router de compras existente, con `Depends(get_current_user)` + check de permiso vía `PermisosService.tiene_permiso`.

---

## Affected files

**Backend:**
- `backend/app/models/pedido_compra.py` — +3 columnas (Slice 1).
- `backend/app/models/pedido_compra_ingreso.py` — modelo nuevo (Slice 2).
- `backend/alembic/versions/YYYYMMDD_add_oc_link_to_pedidos_compra.py` (Slice 1).
- `backend/alembic/versions/YYYYMMDD_create_pedido_compra_ingresos.py` (Slice 2).
- Router de compras (donde viven `vincular-factura` / `facturas-candidatas`) — +endpoints OC + ingresos.
- Pydantic schemas: `OCCandidataResponse`, `VincularOCRequest`, `OrdenCompraDetalleResponse`, `IngresoCreate`, `IngresoResponse`.
- Tests pytest: `tests/test_compras_vincular_oc.py`, `tests/test_compras_ingresos.py` (Strict TDD activo — tests primero).

**Frontend:**
- `frontend/src/components/compras/ModalVincularOC.jsx` — nuevo (Slice 1).
- `frontend/src/components/compras/ModalPedidoDetalle.jsx` — render condicional de vínculo OC + desglose + botones (Slice 1) y workflow de ingreso (Slice 2).
- `frontend/src/components/compras/ModalConfirmarIngreso.jsx` — nuevo si se separa del detalle (Slice 2).
- CSS Modules correspondientes (Tesla Design System, design tokens).

---

## Key Risks

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|------------|
| R1 | **[alto — INCÓGNITA ABIERTA] Campo del ERP que marca "OC pendiente de recepción" no confirmado.** El explore sugirió `pho_selectedinrecepcion` pero NO está verificado. Puede ser otro campo (estado, fecha de recepción nula, qty confirmada < qty inicial, etc.). | Si filtramos por el campo equivocado, las candidatas muestran OCs ya recibidas o esconden OCs válidas. | **Resolver en `sdd-design`**: inspeccionar `tb_purchase_order_header` con dato real, identificar el campo/condición de "pendiente". NO hardcodear hasta confirmar. Documentar la condición elegida en el spec. |
| R2 | **[medio] Granularidad del registro de ingreso** (¿parcial acumulado? ¿un registro por línea-depósito o header+detalle?). | Modelo mal elegido → no se puede registrar recepción parcial o queda inconsistente. | Definir en `sdd-design` con casos reales (recepción total, parcial, multi-depósito). |
| R3 | **[medio] Datos del ERP cambian post-vínculo.** La OC puede editarse en el ERP después de vincularse (cambian líneas/cantidades/depósitos). | El desglose mostrado y los ingresos confirmados pueden divergir de la OC actual. | Leer el detalle de OC en vivo del mirror (siempre refleja el último sync). Documentar que el ingreso confirmado es un snapshot del momento de recepción, independiente de cambios posteriores en la OC. |
| R4 | **[bajo] Permiso para confirmar ingreso.** Confirmar recepción es un acto operativo distinto de vincular un documento. | Si reusamos `gestionar_ordenes_compra`, cualquiera que vincula puede confirmar ingresos. | Decidir en design: reusar vs nuevo permiso `administracion.confirmar_ingreso_compra`. |
| R5 | **[bajo] Strict TDD activo.** Todo cambio backend necesita tests pytest primero (`cd backend && pytest tests/ -v --tb=short`). | Si se saltea, viola el modo TDD del proyecto. | Tests antes de implementación en ambos slices. |

---

## Acceptance Criteria (alto nivel)

### Slice 1
- [ ] Desde `ModalPedidoDetalle`, un usuario con `gestionar_ordenes_compra` puede ver OCs candidatas del proveedor (solo pendientes), vincular una, y verla reflejada.
- [ ] Desvincular limpia las 3 columnas; re-vincular permite elegir otra OC.
- [ ] El desglose por depósito muestra ítems y cantidades por depósito (read-only) leídos del mirror del ERP.
- [ ] Nunca se escribe en las tablas del ERP.
- [ ] Tests pytest cubren vincular, desvincular, candidatas-filtradas, detalle-desglose.

### Slice 2
- [ ] Un usuario puede confirmar el ingreso de mercadería por depósito sobre la OC vinculada, persistido en `pedido_compra_ingresos`.
- [ ] Se puede consultar el estado de ingresos confirmados del pedido.
- [ ] El registro de ingreso captura quién, cuánto, cuándo y a qué depósito.
- [ ] Tests pytest cubren confirmar ingreso (total, parcial, multi-depósito) y consulta.

---

## Next Steps

1. **sdd-spec** + **sdd-design** (pueden correr en paralelo):
   - `sdd-design` DEBE resolver R1 (campo "pendiente" del ERP) y R2 (granularidad del ingreso) con dato real antes de tasks.
   - `sdd-spec` formaliza los criterios de aceptación por slice.
2. **sdd-tasks** → breakdown por slice (modelos, migración, endpoints, frontend, tests). Forzar boundary entre Slice 1 y Slice 2 (PRs encadenados, ~400 líneas c/u).
3. **sdd-apply** → implementar Slice 1 primero, verificar, luego Slice 2.
