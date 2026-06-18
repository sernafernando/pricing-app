# Tasks — Vincular OC del ERP al Pedido + Ingreso por Depósito

**Change:** `compras-vincular-orden-compra-erp`
**Fase:** tasks
**Status:** draft
**Persistence mode:** hybrid
**Fecha:** 2026-06-18

---

## 0. Leyenda y convenciones

- **IDs**: `OC-S1.<NUM>` (Slice 1) / `OC-S2.<NUM>` (Slice 2).
- **Size**: S (<2h), M (2-6h), L (6-12h).
- **TDD marker**: tasks marcados `[TEST]` son tests pytest que deben escribirse ANTES del código de producción asociado (Strict TDD).
- **Depends on**: lista de IDs o `ninguno`.
- **Parallelizable with**: lista de IDs dentro del mismo bloque que pueden correr en paralelo, o `no`.
- **Artifacts**: `NEW` / `MODIFIED`.
- **Acceptance criteria**: checklist binaria verificable.
- **Spec ref**: `REQ-OC-NNN` / `AD-N`.

**Conventions:**
- Migraciones Alembic: `YYYYMMDD_descripcion.py` (naming del proyecto).
- Tests integración en `backend/tests/integration/`, unitarios en `backend/tests/unit/`.
- Test runner: `cd backend && pytest tests/ -v --tb=short`.
- Linter backend: `ruff format --check` + `ruff check`.
- Linter frontend: `npx eslint`.
- **ERP tables are READ-ONLY.** No INSERT/UPDATE/DELETE against `tb_purchase_order_*` or `tb_storage`.
- **Gate Slice 1 → Slice 2**: todas las tasks OC-S1 en ✅ y tests verdes antes de arrancar Slice 2.

---

## Resumen ejecutivo

| Bloque | Tasks | Parallelizable | Est. líneas |
|--------|-------|----------------|-------------|
| Slice 1 — preflight, migración, backend, frontend | 18 | parcialmente | ~390 |
| Slice 2 — migración, backend ingresos, anular, frontend | 13 | parcialmente | ~380 |
| **TOTAL** | **31** | — | **~770** |

Critical path: `OC-S1.1 → OC-S1.2 → OC-S1.3/4 → OC-S1.5/6/7/8 → OC-S1.9/10 → OC-S1.11 → OC-S1.12 → OC-S2.1 → OC-S2.2/3 → OC-S2.4/5/6/7 → OC-S2.8/9 → OC-S2.10 → OC-S2.11`

---

## ═══════════════════════════════════════
## SLICE 1 — Vínculo OC + Desglose Read-Only
## ═══════════════════════════════════════

> **Shippable boundary**: Slice 1 es un PR independiente y mergeable en `develop`. Incluye migración, 4 endpoints, modal de vinculación y desglose read-only. Slice 2 depende de Slice 1 (FK sobre `pedidos_compra` con 3 cols pobladas).

---

### Task OC-S1.1 — GATE: Verificar criterio "OC pendiente" contra data real del ERP

**Size:** S
**Depends on:** ninguno
**Parallelizable with:** no (BLOQUEANTE — ningún task de Slice 1 arranca hasta que este da OK)
**Status:** ✅ done

**Descripción:**
Correr las 3 queries de verificación del design §2 contra la base de datos real antes de cualquier implementación. Si los resultados difieren del criterio esperado, ajustar el criterio documentado en el design y en los tests antes de continuar.

**Queries a correr (design §2):**
```sql
-- A) Distribución del flag de recepción
SELECT pho_selectedinrecepcion, COUNT(*)
FROM tb_purchase_order_header
GROUP BY pho_selectedinrecepcion;

-- B) ¿pod_confirmedqty se usa?
SELECT
  COUNT(*) AS total_lineas,
  COUNT(*) FILTER (WHERE pod_confirmedqty IS NULL) AS confirmed_null,
  COUNT(*) FILTER (WHERE pod_confirmedqty = 0) AS confirmed_cero,
  COUNT(*) FILTER (WHERE pod_confirmedqty < pod_qty) AS con_saldo,
  COUNT(*) FILTER (WHERE pod_confirmedqty = pod_qty) AS completas
FROM tb_purchase_order_detail;

-- C) Sanity candidatas para un proveedor real
SELECT h.comp_id, h.bra_id, h.poh_id, h.poh_total, h.pho_selectedinrecepcion,
       SUM(d.pod_qty) AS qty_total,
       SUM(d.pod_confirmedqty) AS qty_confirmada
FROM tb_purchase_order_header h
JOIN tb_purchase_order_detail d
  ON (d.comp_id, d.bra_id, d.poh_id) = (h.comp_id, h.bra_id, h.poh_id)
WHERE h.supp_id = :supp_id_real
GROUP BY h.comp_id, h.bra_id, h.poh_id, h.poh_total, h.pho_selectedinrecepcion
ORDER BY h.poh_cd DESC NULLS LAST
LIMIT 50;
```

**Fallback:**
- Si (A) muestra `pho_selectedinrecepcion` uniformemente NULL → quitar criterio 2 del filtro.
- Si (B) muestra `pod_confirmedqty` casi siempre NULL/0 → degradar criterio 3 a `SUM(pod_qty) > 0`.
- Actualizar design.md §2 con la variante elegida antes de OC-S1.4.

**Acceptance criteria:**
- [ ] Las 3 queries corren sin error.
- [ ] El criterio definitivo está documentado en design.md §2 (confirmado o ajustado).
- [ ] Resultado pegado en `openspec/changes/compras-vincular-orden-compra-erp/state.yaml` bajo `preflight.criterio_pendiente`.

**Artifacts:**
- `openspec/changes/compras-vincular-orden-compra-erp/state.yaml` (MODIFIED)
- `openspec/changes/compras-vincular-orden-compra-erp/design.md` (MODIFIED si ajuste)

**Spec ref:** AD2, R1

---

### Task OC-S1.2 — Alembic migration: +3 cols nullable en `pedidos_compra`

**Size:** S
**Depends on:** OC-S1.1
**Parallelizable with:** no
**Status:** ✅ done

**Descripción:**
Crear la migración Alembic `20260618_add_oc_link_to_pedidos_compra.py`. Tres `op.add_column` nullable + índice parcial.

```python
# upgrade
op.add_column('pedidos_compra', sa.Column('oc_comp_id', sa.Integer(), nullable=True))
op.add_column('pedidos_compra', sa.Column('oc_bra_id', sa.Integer(), nullable=True))
op.add_column('pedidos_compra', sa.Column('oc_poh_id', sa.BigInteger(), nullable=True))
op.create_index(
    'ix_pedidos_compra_oc_poh',
    'pedidos_compra',
    ['oc_comp_id', 'oc_bra_id', 'oc_poh_id'],
    postgresql_where=sa.text('oc_poh_id IS NOT NULL')
)

# downgrade
op.drop_index('ix_pedidos_compra_oc_poh', table_name='pedidos_compra')
op.drop_column('pedidos_compra', 'oc_poh_id')
op.drop_column('pedidos_compra', 'oc_bra_id')
op.drop_column('pedidos_compra', 'oc_comp_id')
```

**Acceptance criteria:**
- [ ] `alembic upgrade head` aplica sin error.
- [ ] Las 3 columnas existen y son NULL en todas las filas pre-existentes.
- [ ] El índice parcial `ix_pedidos_compra_oc_poh` existe en el schema.
- [ ] `alembic downgrade -1` revierte limpiamente.

**Artifacts:**
- `backend/alembic/versions/20260618_add_oc_link_to_pedidos_compra.py` (NEW)

**Spec ref:** REQ-OC-001

---

### Task OC-S1.3 — SQLAlchemy model: extender `PedidoCompra` con 3 cols + índice

**Size:** S
**Depends on:** OC-S1.2
**Parallelizable with:** no
**Status:** ✅ done

**Descripción:**
Agregar las 3 columnas nullable al modelo `PedidoCompra` en `backend/app/models/pedido_compra.py` y declarar el índice parcial. Espejar el patrón de `ct_transaction_id`.

```python
oc_comp_id = Column(Integer, nullable=True)
oc_bra_id  = Column(Integer, nullable=True)
oc_poh_id  = Column(BigInteger, nullable=True)

__table_args__ = (
    Index(
        'ix_pedidos_compra_oc_poh',
        'oc_comp_id', 'oc_bra_id', 'oc_poh_id',
        postgresql_where=text('oc_poh_id IS NOT NULL')
    ),
    # ... existing args ...
)
```

**Acceptance criteria:**
- [ ] El modelo importa sin error.
- [ ] Los 3 campos están presentes en `PedidoCompra.__table__.columns`.
- [ ] El índice parcial está declarado en `__table_args__`.

**Artifacts:**
- `backend/app/models/pedido_compra.py` (MODIFIED)

**Spec ref:** REQ-OC-001, AD1

---

### Task OC-S1.4 — Pydantic schemas: `OCCandidataResponse`, `VincularOCRequest`, `OrdenCompraDetalleResponse`

**Size:** S
**Depends on:** OC-S1.3
**Parallelizable with:** OC-S1.5 (pueden escribirse en paralelo una vez el modelo existe)
**Status:** ✅ done

**Descripción:**
Agregar los schemas Pydantic en `backend/app/schemas/pedido_compra.py` (o nuevo `schemas/oc_ingreso.py`):

- `VincularOCRequest`: `oc_comp_id: int`, `oc_bra_id: int`, `oc_poh_id: int`. Validator: los 3 deben estar presentes (422 si no).
- `OCCandidataResponse`: `oc_comp_id`, `oc_bra_id`, `oc_poh_id`, `poh_cd`, `poh_total`, `qty_pendiente`.
- `OrdenCompraDetalleResponse`: `oc_comp_id`, `oc_bra_id`, `oc_poh_id`, lista `lines` (cada línea: `pod_id`, `item_id`, `stor_id`, `deposito_nombre`, `pod_qty`, `pod_confirmedqty`, `saldo_pendiente`, `pod_price`).

**Acceptance criteria:**
- [ ] Los 3 schemas importan sin error desde el router.
- [ ] `VincularOCRequest` con body incompleto (solo 2 de 3 campos) lanza `ValidationError`.
- [ ] `OrdenCompraDetalleResponse` serializa correctamente desde un dict de prueba.

**Artifacts:**
- `backend/app/schemas/pedido_compra.py` (MODIFIED) o `backend/app/schemas/oc_ingreso.py` (NEW)

**Spec ref:** REQ-OC-001, REQ-OC-002, REQ-OC-006

---

### Task OC-S1.5 — [TEST] Tests integración OC-candidatas (failing first)

**Size:** M
**Depends on:** OC-S1.4
**Parallelizable with:** OC-S1.6 (tests vincular/desvincular pueden escribirse en paralelo)
**Status:** ✅ done
**[TEST]** — escribir ANTES de OC-S1.7

**Descripción:**
Crear `backend/tests/integration/test_oc_vincular_s1_endpoints.py` con los tests de `oc-candidatas`. Deben fallar con `404 Not Found` (endpoint no existe aún).

Tests a incluir:
- `test_oc_candidatas_filtra_por_supp_id_y_criterio_pendiente` — seed 1 OC pendiente + 1 no pendiente para `supp_id=42`; solo la pendiente aparece. (REQ-OC-002)
- `test_oc_candidatas_excluye_oc_no_pendiente` — flag `pho_selectedinrecepcion=TRUE` excluye la OC. (REQ-OC-002, AD2)
- `test_oc_candidatas_excluye_ya_vinculada_a_otro_pedido` — OC vinculada a P2 no aparece en candidatas de P1. (REQ-OC-002)
- `test_oc_candidatas_retorna_lista_vacia_sin_ocs` — 200 con `{"items": []}`. (REQ-OC-002)
- `test_oc_candidatas_403_sin_permiso` — sin `gestionar_ordenes_compra`. (REQ-OC-010)
- `test_oc_candidatas_404_pedido_inexistente` — pedido_id=9999. (REQ-OC-012)

Fixtures requeridas: seed `tb_purchase_order_header` + `tb_purchase_order_detail` + `tb_storage` + `proveedores.supp_id`.

**Acceptance criteria:**
- [ ] Todos los tests existen y corren (`pytest`) — deben fallar con 404/ImportError, NO con errores de fixture.
- [ ] Fixtures de seed crean los registros ERP necesarios en la sesión de test.

**Artifacts:**
- `backend/tests/integration/test_oc_vincular_s1_endpoints.py` (NEW)

**Spec ref:** REQ-OC-002, REQ-OC-010, REQ-OC-012

---

### Task OC-S1.6 — [TEST] Tests integración vincular-oc / desvincular-oc (failing first)

**Size:** M
**Depends on:** OC-S1.4
**Parallelizable with:** OC-S1.5
**Status:** ✅ done
**[TEST]** — escribir ANTES de OC-S1.8

Tests a agregar en `test_oc_vincular_s1_endpoints.py`:
- `test_vincular_oc_setea_3_cols` — 200, pedido tiene `oc_poh_id=12345`. (REQ-OC-003)
- `test_vincular_oc_409_ya_vinculado` — 409 `"Pedido already has a linked OC. Unlink first."`. (REQ-OC-003)
- `test_vincular_oc_404_oc_no_existe` — OC inexistente → 404. (REQ-OC-003)
- `test_vincular_oc_409_proveedor_mismatch` — OC de otro supp_id → 409 `"supplier mismatch"`. (REQ-OC-003)
- `test_vincular_oc_403_sin_permiso`. (REQ-OC-010)
- `test_vincular_oc_404_pedido_inexistente`. (REQ-OC-012)
- `test_desvincular_oc_limpia_3_cols` — 204, cols = NULL. (REQ-OC-004)
- `test_desvincular_oc_409_sin_oc_vinculada`. (REQ-OC-004)
- `test_desvincular_oc_403_sin_permiso`. (REQ-OC-010)
- `test_relink_via_desvincular_vincular` — secuencia DELETE+POST; pedido queda con nueva OC. (REQ-OC-005)

**Acceptance criteria:**
- [ ] Tests corren y fallan (endpoint ausente), no por fixture.

**Artifacts:**
- `backend/tests/integration/test_oc_vincular_s1_endpoints.py` (MODIFIED — append)

**Spec ref:** REQ-OC-003, REQ-OC-004, REQ-OC-005

---

### Task OC-S1.7 — [TEST] Tests integración detalle OC (failing first)

**Size:** S
**Depends on:** OC-S1.4
**Parallelizable with:** OC-S1.5, OC-S1.6
**Status:** ✅ done
**[TEST]** — escribir ANTES de OC-S1.9

Tests a agregar en `test_oc_vincular_s1_endpoints.py`:
- `test_orden_compra_detalle_retorna_lineas_por_deposito` — OC con 3 líneas: item A→dep1, item A→dep2, item B→dep1; respuesta tiene 3 entradas sin colapsar. (REQ-OC-006, EC-01)
- `test_orden_compra_detalle_409_sin_oc_vinculada`. (REQ-OC-006)
- `test_orden_compra_detalle_403_sin_permiso`. (REQ-OC-010)
- `test_orden_compra_detalle_no_escribe_erp` — assert que `tb_purchase_order_detail` no recibe writes (mock session). (REQ-OC-011)

**Acceptance criteria:**
- [ ] Tests corren y fallan sin fixture errors.

**Artifacts:**
- `backend/tests/integration/test_oc_vincular_s1_endpoints.py` (MODIFIED — append)

**Spec ref:** REQ-OC-006, REQ-OC-011, EC-01

---

### Task OC-S1.8 — Servicio `pedidos_service.py`: `vincular_oc` + `desvincular_oc`

**Size:** M
**Depends on:** OC-S1.5, OC-S1.6 (tests escritos)
**Parallelizable with:** OC-S1.9
**Status:** ✅ done

**Descripción:**
Agregar funciones en `backend/app/services/pedidos_service.py`, espejando `vincular_factura` / `desvincular_factura`:

- `vincular_oc(db, pedido_id, req: VincularOCRequest, current_user)`:
  1. `_obtener_pedido_o_404(db, pedido_id)` → 404 si no existe.
  2. 409 si `pedido.oc_poh_id IS NOT NULL` (`"Pedido already has a linked OC. Unlink first."`).
  3. Verifica que `(req.oc_comp_id, req.oc_bra_id, req.oc_poh_id)` existe en `tb_purchase_order_header` (404 si no).
  4. Verifica que `supp_id` del proveedor del pedido coincide con el de la OC (409 `"supplier mismatch"` si no).
  5. Verifica que la OC satisface CRITERION-PENDIENTE (criterio final post-OC-S1.1) — 409 si no.
  6. Setea las 3 cols, `_registrar_evento("OC_VINCULADA")`. No commit (router commitea).

- `desvincular_oc(db, pedido_id, current_user)`:
  1. `_obtener_pedido_o_404` → 404.
  2. 409 si `oc_poh_id IS NULL` (`"Pedido has no linked OC"`).
  3. Cuenta filas en `pedido_compra_ingresos` para ese `pedido_id` (query con `func.count`). Si > 0 → 409 `"Cannot unlink OC: confirmed ingresos exist. Anular ingresos first."`.
  4. Limpia las 3 cols, `_registrar_evento("OC_DESVINCULADA", payload={oc anterior, ingresos_count=0})`.

**Acceptance criteria:**
- [ ] `test_vincular_oc_setea_3_cols` pasa.
- [ ] `test_vincular_oc_409_ya_vinculado` pasa.
- [ ] `test_vincular_oc_404_oc_no_existe` pasa.
- [ ] `test_vincular_oc_409_proveedor_mismatch` pasa.
- [ ] `test_desvincular_oc_limpia_3_cols` pasa.
- [ ] `test_desvincular_oc_409_sin_oc_vinculada` pasa.
- [ ] `test_relink_via_desvincular_vincular` pasa.

**Artifacts:**
- `backend/app/services/pedidos_service.py` (MODIFIED)

**Spec ref:** REQ-OC-003, REQ-OC-004, REQ-OC-005, AD5

---

### Task OC-S1.9 — Nuevo servicio `oc_ingresos_service.py`: candidatas + desglose

**Size:** M
**Depends on:** OC-S1.5, OC-S1.7 (tests escritos)
**Parallelizable with:** OC-S1.8
**Status:** ✅ done

**Descripción:**
Crear `backend/app/services/oc_ingresos_service.py` con:

- `get_oc_candidatas(db, pedido_id)`:
  Resuelve `supp_id` del proveedor del pedido (WARNING + `[]` si NULL). Ejecuta la query parametrizable (design §4.3) con el criterio final post-OC-S1.1. Retorna lista de `OCCandidataResponse`.

- `get_orden_compra_detalle(db, pedido_id)`:
  404 si pedido no existe; 409 `"Pedido has no linked OC"` si `oc_poh_id IS NULL`. Query design §4.4. Por cada línea `pod_id`, computa `saldo_pendiente = pod_qty - COALESCE(pod_confirmedqty,0) - recibido_pricing` (en S1, `recibido_pricing` siempre 0 ya que tabla `pedido_compra_ingresos` no existe aún — usar `COALESCE(..., 0)`). Retorna `OrdenCompraDetalleResponse`.

**Acceptance criteria:**
- [ ] `test_oc_candidatas_filtra_por_supp_id_y_criterio_pendiente` pasa.
- [ ] `test_oc_candidatas_excluye_oc_no_pendiente` pasa.
- [ ] `test_oc_candidatas_excluye_ya_vinculada_a_otro_pedido` pasa.
- [ ] `test_oc_candidatas_retorna_lista_vacia_sin_ocs` pasa.
- [ ] `test_orden_compra_detalle_retorna_lineas_por_deposito` pasa.
- [ ] `test_orden_compra_detalle_409_sin_oc_vinculada` pasa.
- [ ] `test_orden_compra_detalle_no_escribe_erp` pasa.

**Artifacts:**
- `backend/app/services/oc_ingresos_service.py` (NEW)

**Spec ref:** REQ-OC-002, REQ-OC-006, AD2, AD6, AD8

---

### Task OC-S1.10 — Endpoints Batch J en `administracion_compras.py` (Slice 1)

**Size:** M
**Depends on:** OC-S1.8, OC-S1.9
**Parallelizable with:** no
**Status:** ✅ done

**Descripción:**
Agregar bloque **"Batch J — Vincular OC del ERP"** en `backend/app/routers/administracion_compras.py`, inmediatamente después del Batch I (factura). Cuatro endpoints:

```python
@router.get("/pedidos/{pedido_id}/oc-candidatas", response_model=List[OCCandidataResponse])
@router.post("/pedidos/{pedido_id}/vincular-oc", response_model=PedidoCompraSummary)
@router.delete("/pedidos/{pedido_id}/desvincular-oc", status_code=204)
@router.get("/pedidos/{pedido_id}/orden-compra/detalle", response_model=OrdenCompraDetalleResponse)
```

Todos con `Depends(require_permiso("administracion.gestionar_ordenes_compra"))`.
Handlers llaman a los servicios correspondientes, `_commit_or_rollback` donde aplica.

**Acceptance criteria:**
- [ ] Los 4 endpoints aparecen en `GET /openapi.json`.
- [ ] Todos los tests de OC-S1.5, OC-S1.6, OC-S1.7 pasan en verde.
- [ ] `test_oc_candidatas_403_sin_permiso` pasa.
- [ ] `test_vincular_oc_403_sin_permiso` pasa.
- [ ] `test_orden_compra_detalle_403_sin_permiso` pasa.
- [ ] Ningún test de Batch I (factura) regresa en rojo.

**Artifacts:**
- `backend/app/routers/administracion_compras.py` (MODIFIED)

**Spec ref:** REQ-OC-010, AD7, AD9

---

### Task OC-S1.11 — Frontend: `ModalVincularOC.jsx` + CSS Module

**Size:** M
**Depends on:** OC-S1.10 (endpoints disponibles)
**Parallelizable with:** OC-S1.12
**Status:** ✅ done

**Descripción:**
Crear `frontend/src/components/compras/ModalVincularOC.jsx` espejando `ModalVincularFactura.jsx`:
- Props: `{ pedido, onClose, onVinculada }`.
- `usePermisos()` gate — si sin permiso, no renderiza tabla.
- `useEffect` → `GET /pedidos/{id}/oc-candidatas`; spinner con `Loader2`.
- Tabla radio-select: columnas Nº OC (`poh_cd`), Fecha, Total, Qty pendiente.
- Botón "Vincular OC" → `POST /pedidos/{id}/vincular-oc`; on success → `onVinculada(updatedPedido)`.
- Manejo de error 409 (ya vinculado) y 404.
- Iconos: `Link2`, `Loader2`, `X`, `AlertCircle` de `lucide-react`.
- `ModalVincularOC.module.css` — clona estructura del de factura, tokens `var(--bg-primary)`, `var(--text-primary)`, etc. Sin Tailwind, sin inline styles.

**Acceptance criteria:**
- [ ] El componente renderiza sin errores en la app.
- [ ] La lista de candidatas se carga y muestra correctamente.
- [ ] Seleccionar una OC y clickar "Vincular" llama al endpoint y cierra el modal.
- [ ] Error 409 muestra mensaje inline con `AlertCircle`.
- [ ] ESLint sin errores.

**Artifacts:**
- `frontend/src/components/compras/ModalVincularOC.jsx` (NEW)
- `frontend/src/components/compras/ModalVincularOC.module.css` (NEW)

**Spec ref:** REQ-OC-002, REQ-OC-003, §5.1

---

### Task OC-S1.12 — Frontend: sección OC en `ModalPedidoDetalle.jsx` + hook

**Size:** M
**Depends on:** OC-S1.10 (endpoints disponibles)
**Parallelizable with:** OC-S1.11
**Status:** ✅ done

**Descripción:**
Extender `ModalPedidoDetalle.jsx` con la sección "Orden de compra" (debajo de la sección factura):

- Si `pedido.oc_poh_id`: muestra Nº OC (`poh_cd`) + botón "Desvincular OC" (gate permiso) + tabla desglose (`GET orden-compra/detalle`) agrupada por depósito: Depósito | Item | Pod qty | Saldo pendiente.
- Si `!pedido.oc_poh_id`: botón "Vincular OC" que abre `ModalVincularOC`.
- Patrón condicional idéntico al de `ModalVincularFactura` (línea ~819).
- Desvincular → `DELETE desvincular-oc`; on 409 muestra mensaje `"No se puede desvincular: hay ingresos registrados. Anulá los ingresos primero."`.
- Extender `useComprasPedidos.js` con `fetchOcDetalle(pedidoId)` y `desvinculaOc(pedidoId)`.

**Acceptance criteria:**
- [ ] Pedido con OC vinculada muestra el desglose y el botón desvincular.
- [ ] Pedido sin OC vinculada muestra el botón vincular que abre el modal.
- [ ] Desvincular exitoso actualiza el estado del pedido en el modal.
- [ ] 409 en desvincular muestra mensaje inline.
- [ ] ESLint sin errores.

**Artifacts:**
- `frontend/src/components/compras/ModalPedidoDetalle.jsx` (MODIFIED)
- `frontend/src/hooks/useComprasPedidos.js` (MODIFIED)

**Spec ref:** REQ-OC-004, REQ-OC-006, §5.2

---

### Task OC-S1.13 — Smoke test manual Slice 1 + ruff lint

**Size:** S
**Depends on:** OC-S1.10, OC-S1.11, OC-S1.12
**Parallelizable with:** no
**Status:** ✅ done

**Descripción:**
Verificación end-to-end manual del flujo de Slice 1 antes de abrir el PR:
1. Vincular una OC real desde la UI → confirmar 3 cols seteadas en DB.
2. Ver el desglose por depósito.
3. Desvincular (pedido sin ingresos) → cols = NULL.
4. Intentar vincular una OC de otro proveedor → verificar 409 en UI.
5. `cd backend && ruff format --check && ruff check` → 0 errores.
6. `npx eslint frontend/src` → 0 errores.
7. `cd backend && pytest tests/ -v --tb=short` → todos los tests S1 verdes.

**Acceptance criteria:**
- [ ] Flujo manual completo sin errores de consola.
- [ ] Ruff y ESLint sin errores.
- [ ] Todos los tests de Slice 1 en verde.

**Spec ref:** REQ-OC-001..006, REQ-OC-010..012

---

## ═══════════════════════════════════════
## SLICE 2 — Confirmar Ingreso por Depósito
## ═══════════════════════════════════════

> **Gate de entrada**: todas las tasks de Slice 1 en ✅ y tests verdes.
> **Shippable boundary**: Slice 2 es un PR separado, encadenado a Slice 1. Incluye la tabla `pedido_compra_ingresos`, endpoints GET/POST ingresos, endpoint `anular_ingreso`, y UI confirmar ingreso.

---

### Task OC-S2.1 — Alembic migration: crear `pedido_compra_ingresos`

**Size:** S
**Depends on:** OC-S1.13 (gate Slice 1 OK)
**Parallelizable with:** no
**Status:** ⬜ pending

**Descripción:**
Crear `20260619_create_pedido_compra_ingresos.py`. `down_revision` = revision de `20260618_add_oc_link_to_pedidos_compra.py`.

Schema (design §3.2):
- `id BIGSERIAL PK`, `pedido_id BIGINT NOT NULL FK pedidos_compra RESTRICT`, `oc_comp_id INT NOT NULL`, `oc_bra_id INT NOT NULL`, `oc_poh_id BIGINT NOT NULL`, `pod_id BIGINT NOT NULL`, `item_id INT NOT NULL`, `stor_id INT NOT NULL`, `cantidad_recibida NUMERIC(18,6) NOT NULL CHECK >0`, `fecha_ingreso DATE NOT NULL DEFAULT CURRENT_DATE`, `usuario_id INT NOT NULL FK usuarios RESTRICT`, `observaciones TEXT`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
- Índices: `ix_pci_pedido ON (pedido_id)`, `ix_pci_oc_linea ON (oc_comp_id, oc_bra_id, oc_poh_id, pod_id)`.

**Acceptance criteria:**
- [ ] `alembic upgrade head` aplica sin error.
- [ ] Tabla `pedido_compra_ingresos` existe con todos los campos y constraints.
- [ ] Los 2 índices existen.
- [ ] `alembic downgrade -1` revierte limpiamente.

**Artifacts:**
- `backend/alembic/versions/20260619_create_pedido_compra_ingresos.py` (NEW)

**Spec ref:** REQ-OC-007

---

### Task OC-S2.2 — SQLAlchemy model: `PedidoCompraIngreso`

**Size:** S
**Depends on:** OC-S2.1
**Parallelizable with:** no
**Status:** ⬜ pending

**Descripción:**
Crear `backend/app/models/pedido_compra_ingreso.py` con `PedidoCompraIngreso(Base)`. FK `pedido_id → PedidoCompra.id` y `usuario_id → Usuario.id` (relationship opcional para join). `CheckConstraint("cantidad_recibida > 0")`.

**Acceptance criteria:**
- [ ] Modelo importa sin error.
- [ ] Campos y constraints presentes.

**Artifacts:**
- `backend/app/models/pedido_compra_ingreso.py` (NEW)

**Spec ref:** REQ-OC-007

---

### Task OC-S2.3 — Pydantic schemas: `IngresoCreateRequest`, `IngresoLineRequest`, `IngresoResponse`, `AnularIngresoRequest`

**Size:** S
**Depends on:** OC-S2.2
**Parallelizable with:** OC-S2.4
**Status:** ⬜ pending

**Descripción:**
Schemas en `backend/app/schemas/oc_ingreso.py`:
- `IngresoLineRequest`: `pod_id: int`, `cantidad_recibida: Decimal (>0, validator)`, `fecha_ingreso: Optional[date]`, `observaciones: Optional[str]`.
- `IngresoCreateRequest`: `lines: List[IngresoLineRequest]` (min 1 item).
- `IngresoResponse`: `id`, `pedido_id`, `pod_id`, `item_id`, `stor_id`, `deposito_nombre`, `cantidad_recibida`, `fecha_ingreso`, `usuario_id`, `observaciones`, `created_at`.
- `IngresoListResponse`: `pedido_id`, `ingresos: List[IngresoResponse]`, `resumen_lineas: List[ResumenLineaResponse]`.
- `ResumenLineaResponse`: `pod_id`, `item_id`, `cantidad_oc`, `cantidad_recibida_total`, `saldo_pendiente`.
- `AnularIngresoRequest`: `motivo: str` (required, min 1 char) — para `POST /ingresos/{ingreso_id}/anular`.

**Acceptance criteria:**
- [ ] Todos los schemas importan sin error.
- [ ] `IngresoCreateRequest` con `lines=[]` lanza `ValidationError`.
- [ ] `IngresoLineRequest` con `cantidad_recibida=0` lanza `ValidationError`.

**Artifacts:**
- `backend/app/schemas/oc_ingreso.py` (MODIFIED/NEW)

**Spec ref:** REQ-OC-007, REQ-OC-008, REQ-OC-009

---

### Task OC-S2.4 — [TEST] Tests integración POST/GET ingresos (failing first)

**Size:** M
**Depends on:** OC-S2.3
**Parallelizable with:** OC-S2.5
**Status:** ⬜ pending
**[TEST]** — escribir ANTES de OC-S2.6

Crear `backend/tests/integration/test_oc_vincular_s2_ingresos.py`:

- `test_post_ingreso_inserta_fila` — 201, fila creada con `cantidad_recibida=100`. (REQ-OC-008)
- `test_post_ingreso_409_excede_saldo` — prior 80, solicitud 30 → 409 `"Over-receipt: pod_id 1 — saldo pendiente es 20, requested 30"`. (REQ-OC-008)
- `test_post_ingreso_400_pod_no_pertenece_a_oc` — `pod_id` de otra OC → 422. (REQ-OC-008)
- `test_post_ingreso_400_sin_oc_vinculada` — pedido sin OC → 409. (REQ-OC-008)
- `test_post_ingreso_recepcion_parcial_acumulada` — dos llamadas parciales suman sin exceder. (REQ-OC-008)
- `test_post_ingreso_atomicidad_multilinea` — una línea OK + una línea over → 409, ninguna fila insertada. (REQ-OC-008)
- `test_get_ingresos_resumen_saldo_pendiente` — después de ingreso parcial, saldo en `resumen_lineas` correcto. (REQ-OC-009)
- `test_get_ingresos_lista_vacia` — 200, `ingresos=[]`, `resumen_lineas` con saldo=cantidad_oc. (REQ-OC-009)
- `test_ingreso_403_sin_permiso`. (REQ-OC-010)
- `test_ingreso_nunca_escribe_stock` — assert `stock_por_deposito` sin cambios tras ingreso. (REQ-OC-011)

**Acceptance criteria:**
- [ ] Tests corren y fallan (endpoint ausente), fixtures sin error.

**Artifacts:**
- `backend/tests/integration/test_oc_vincular_s2_ingresos.py` (NEW)

**Spec ref:** REQ-OC-008, REQ-OC-009, REQ-OC-010, REQ-OC-011

---

### Task OC-S2.5 — [TEST] Tests integración `anular_ingreso` (failing first)

**Size:** S
**Depends on:** OC-S2.3
**Parallelizable with:** OC-S2.4
**Status:** ⬜ pending
**[TEST]** — escribir ANTES de OC-S2.7

Tests en `test_oc_vincular_s2_ingresos.py` (append):
- `test_anular_ingreso_permite_desvincular_despues` — ingreso → anular → desvincular OC exitoso. (desvincular block es removible)
- `test_anular_ingreso_restaura_saldo` — after anulación, `saldo_pendiente` aumenta en `cantidad_recibida` anulada.
- `test_anular_ingreso_404_ingreso_inexistente`.
- `test_anular_ingreso_409_ingreso_ya_anulado` — no se puede anular dos veces.
- `test_anular_ingreso_403_sin_permiso`.
- `test_desvincular_oc_bloqueado_con_ingresos_activos` — ingreso presente (no anulado) → 409 al desvincular. (REQ-OC-004)

**Acceptance criteria:**
- [ ] Tests corren y fallan (endpoint ausente), fixtures sin error.

**Artifacts:**
- `backend/tests/integration/test_oc_vincular_s2_ingresos.py` (MODIFIED — append)

---

### Task OC-S2.6 — Servicio `oc_ingresos_service.py`: lógica POST/GET ingresos + anular

**Size:** L
**Depends on:** OC-S2.4, OC-S2.5 (tests escritos)
**Parallelizable with:** no
**Status:** ⬜ pending

**Descripción:**
Extender `oc_ingresos_service.py` (Slice 1) con:

- `get_ingresos(db, pedido_id)` → 404 si pedido inexistente. Lista ingresos activos (no anulados). Para `resumen_lineas`: join con `tb_purchase_order_detail` para obtener `pod_qty`; si línea deletada del ERP → `saldo_pendiente = None` (no crash). (EC-03 de specs)

- `post_ingresos(db, pedido_id, req: IngresoCreateRequest, current_user)`:
  1. 404 si pedido no existe.
  2. 409 `"Pedido has no linked OC"` si sin OC.
  3. Para cada línea: verificar `pod_id` en `tb_purchase_order_detail` para la OC vinculada (422 si no). Derivar `item_id`, `stor_id` del mirror (snapshot).
  4. Computar saldo por línea: `pod_qty - COALESCE(pod_confirmedqty,0) - SUM(cantidad_recibida de ingresos ACTIVOS del mismo pod_id)`.
  5. 409 si `cantidad_recibida > saldo_pendiente` (mensaje con valores exactos).
  6. Todas las validaciones ANTES de cualquier insert (atomicidad).
  7. Bulk insert; retorna 201 con filas creadas.

- `anular_ingreso(db, ingreso_id, motivo, current_user)`:
  - Estrategia v1: agregar columna `anulado BOOLEAN DEFAULT FALSE` + `motivo_anulacion TEXT` + `anulado_at TIMESTAMPTZ` + `anulado_por_id INT FK usuarios`. El ingreso no se borra físicamente (histórico).
  - 404 si ingreso no existe.
  - 409 si `anulado=TRUE` ya.
  - Setea `anulado=TRUE, motivo_anulacion=motivo, anulado_at=now(), anulado_por_id=user.id`.
  - Las validaciones de saldo en `post_ingresos` filtran `WHERE NOT anulado`.
  - El bloqueo de `desvincular_oc` cuenta solo `WHERE NOT anulado`.

> **Nota:** `anular_ingreso` requiere un `op.add_column` adicional en la migración OC-S2.1. Si la migración ya se aplicó, crear sub-migración `20260619b_add_anulado_to_pci.py`. Coordinar con OC-S2.1 si se hace todo antes de aplicar.

**Acceptance criteria:**
- [ ] Todos los tests de OC-S2.4 pasan.
- [ ] Todos los tests de OC-S2.5 pasan.
- [ ] `test_desvincular_oc_bloqueado_con_ingresos_activos` pasa.
- [ ] `test_desvincular_oc_limpia_3_cols` (S1) sigue verde.
- [ ] `test_ingreso_nunca_escribe_stock` pasa.

**Artifacts:**
- `backend/app/services/oc_ingresos_service.py` (MODIFIED)

**Spec ref:** REQ-OC-008, REQ-OC-009, design §4.6, AD5

---

### Task OC-S2.7 — Endpoints Batch J Slice 2: GET/POST ingresos + anular

**Size:** M
**Depends on:** OC-S2.6
**Parallelizable with:** no
**Status:** ⬜ pending

**Descripción:**
Agregar a `administracion_compras.py` (Batch J, sub-bloque Slice 2):

```python
@router.get("/pedidos/{pedido_id}/ingresos", response_model=IngresoListResponse)
@router.post("/pedidos/{pedido_id}/ingresos", response_model=IngresoListResponse, status_code=201)
@router.post("/pedidos/{pedido_id}/ingresos/{ingreso_id}/anular", status_code=200)
```

Todos con `Depends(require_permiso("administracion.gestionar_ordenes_compra"))`.

**Acceptance criteria:**
- [ ] Los 3 endpoints aparecen en `GET /openapi.json`.
- [ ] Todos los tests de OC-S2.4 y OC-S2.5 pasan en verde.
- [ ] Ningún test de Slice 1 regresa en rojo.

**Artifacts:**
- `backend/app/routers/administracion_compras.py` (MODIFIED)

**Spec ref:** REQ-OC-008, REQ-OC-009, REQ-OC-010

---

### Task OC-S2.8 — Frontend: `ModalConfirmarIngreso.jsx` + CSS Module

**Size:** M
**Depends on:** OC-S2.7 (endpoints disponibles)
**Parallelizable with:** OC-S2.9
**Status:** ⬜ pending

**Descripción:**
Crear `frontend/src/components/compras/ModalConfirmarIngreso.jsx`:
- Props: `{ pedido, lineaOC, saldoPendiente, onClose, onIngresado }`.
- Campos: `cantidad_recibida` (input numérico ≤ `saldoPendiente`, required), `fecha_ingreso` (date, default hoy), `observaciones` (textarea, opcional).
- Validación client-side: `0 < cantidad <= saldoPendiente`.
- Submit → `POST /pedidos/{id}/ingresos` con `lines: [{ pod_id, cantidad_recibida, fecha_ingreso, observaciones }]`.
- On 409 (over-receipt): muestra mensaje inline con el saldo real del servidor.
- Iconos: `PackagePlus`, `Loader2`, `X`, `AlertCircle`.
- `ModalConfirmarIngreso.module.css` — mismos tokens Tesla.

**Acceptance criteria:**
- [ ] Modal renderiza con el saldo correcto pre-cargado.
- [ ] Submit exitoso llama `onIngresado`.
- [ ] Submit con cantidad > saldo del servidor muestra error 409 inline.
- [ ] ESLint sin errores.

**Artifacts:**
- `frontend/src/components/compras/ModalConfirmarIngreso.jsx` (NEW)
- `frontend/src/components/compras/ModalConfirmarIngreso.module.css` (NEW)

**Spec ref:** REQ-OC-008, §5.3

---

### Task OC-S2.9 — Frontend: historial ingresos + botón anular en `ModalPedidoDetalle.jsx`

**Size:** M
**Depends on:** OC-S2.7 (endpoints disponibles)
**Parallelizable with:** OC-S2.8
**Status:** ⬜ pending

**Descripción:**
Extender la sección "Orden de compra" de `ModalPedidoDetalle.jsx` con Slice 2:

- En la tabla desglose (ya existente de S1): columna acción "Confirmar ingreso" por línea con `saldo_pendiente > 0` → abre `ModalConfirmarIngreso`.
- Sub-sección "Historial de ingresos" (`GET /ingresos`): tabla fecha | item | depósito | cantidad | usuario | botón "Anular" (gate permiso). Botón anular → prompt motivo → `POST /ingresos/{id}/anular`.
- Al confirmar ingreso o anular: refetch desglose + historial.
- Extender `useComprasPedidos.js` con `fetchIngresos(pedidoId)`, `postIngreso(pedidoId, lines)`, `anularIngreso(pedidoId, ingresoId, motivo)`.

**Acceptance criteria:**
- [ ] Botón "Confirmar ingreso" aparece solo en líneas con saldo > 0.
- [ ] Historial lista ingresos activos (no anulados).
- [ ] Anular exitoso desaparece la fila o la marca como anulada en UI.
- [ ] ESLint sin errores.

**Artifacts:**
- `frontend/src/components/compras/ModalPedidoDetalle.jsx` (MODIFIED)
- `frontend/src/hooks/useComprasPedidos.js` (MODIFIED)

**Spec ref:** REQ-OC-009, §5.3

---

### Task OC-S2.10 — Migración adicional: cols `anulado` en `pedido_compra_ingresos`

**Size:** S
**Depends on:** OC-S2.1 (puede hacerse antes de aplicar OC-S2.1 si se agrega al mismo archivo, o como sub-migración si ya aplicó)
**Parallelizable with:** OC-S2.2, OC-S2.3
**Status:** ⬜ pending

**Descripción:**
Si OC-S2.1 todavía no fue aplicado en el entorno target: incorporar las 4 cols de anulación directamente en `20260619_create_pedido_compra_ingresos.py`.

Si ya fue aplicado: crear `20260619b_add_anulado_to_pedido_compra_ingresos.py`:
```python
op.add_column('pedido_compra_ingresos', sa.Column('anulado', sa.Boolean(), nullable=False, server_default='false'))
op.add_column('pedido_compra_ingresos', sa.Column('motivo_anulacion', sa.Text(), nullable=True))
op.add_column('pedido_compra_ingresos', sa.Column('anulado_at', sa.DateTime(timezone=True), nullable=True))
op.add_column('pedido_compra_ingresos', sa.Column('anulado_por_id', sa.Integer(), nullable=True))
op.create_foreign_key('fk_pci_anulado_por', 'pedido_compra_ingresos', 'usuarios', ['anulado_por_id'], ['id'])
```

**Acceptance criteria:**
- [ ] Cols `anulado`, `motivo_anulacion`, `anulado_at`, `anulado_por_id` existen en la tabla.
- [ ] `alembic upgrade head` aplica sin error.
- [ ] `alembic downgrade -1` revierte.

**Artifacts:**
- `backend/alembic/versions/20260619b_add_anulado_to_pedido_compra_ingresos.py` (NEW, si sub-migración)

---

### Task OC-S2.11 — Smoke test manual Slice 2 + ruff lint + PR readiness

**Size:** S
**Depends on:** OC-S2.7, OC-S2.8, OC-S2.9
**Parallelizable with:** no
**Status:** ⬜ pending

**Descripción:**
Verificación end-to-end manual del flujo Slice 2:
1. Confirmar ingreso parcial para una línea de OC desde la UI.
2. Confirmar segundo ingreso parcial; verificar saldo actualizado.
3. Intentar over-receipt → verificar 409 en UI.
4. Anular el primer ingreso → verificar que saldo se recupera.
5. Desvincular OC (ahora posible) → cols = NULL.
6. `cd backend && ruff format --check && ruff check` → 0 errores.
7. `npx eslint frontend/src` → 0 errores.
8. `cd backend && pytest tests/ -v --tb=short` → todos los tests S1+S2 verdes.

**Acceptance criteria:**
- [ ] Flujo manual completo sin errores de consola.
- [ ] Ruff y ESLint sin errores.
- [ ] Todos los tests de Slice 1 y Slice 2 en verde.
- [ ] PR de Slice 2 listo para revisión.

---

## Review Workload Forecast

| Métrica | Slice 1 | Slice 2 | Total |
|---------|---------|---------|-------|
| Est. líneas cambiadas | ~390 | ~380 | ~770 |
| Archivos nuevos | 5 BE + 4 FE = 9 | 3 BE + 4 FE = 7 | 16 |
| Archivos modificados | 3 BE + 2 FE | 3 BE + 2 FE | 10 |
| 400-line budget risk | **Borderline** | **Borderline** | **High** |
| Tests incluidos | 7 test tasks | 5 test tasks | 12 |

**Chained PRs recommended:** YES — Slice 1 y Slice 2 están diseñados como PRs encadenados. Slice 2 tiene FK física sobre tablas creadas en Slice 1 y depende de los endpoints de Slice 1 para las validaciones de saldo.

**Chain strategy:** `feature-branch-chain` — Slice 1 PR targeta `develop`; Slice 2 PR targeta el branch de Slice 1 (para que el diff muestre solo los cambios de Slice 2). Solo Slice 1 se mergea a `develop` primero; luego Slice 2.

**Decision needed before apply:** NO — Los slices y PRs ya están definidos. La única acción requerida antes de `sdd-apply` es ejecutar el task OC-S1.1 (gate de verificación SQL) y confirmar el criterio CRITERION-PENDIENTE. Esto lo hace el desarrollador antes de implementar OC-S1.9.

**Notes:**
- `anular_ingreso` (OC-S2.5/6/7) agrega ~80 líneas extra a Slice 2 respecto a la estimación original del design (que no lo incluía explícitamente). Considerado dentro del presupuesto ~400 de S2.
- Si la migración OC-S2.1 se aplica antes de que se decida incluir `anulado`, se necesita la sub-migración OC-S2.10. Recomendado: incorporar desde el inicio en OC-S2.1.
