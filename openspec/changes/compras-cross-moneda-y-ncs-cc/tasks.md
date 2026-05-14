# Tasks: Compras Cross-Moneda + NCs Visibles en CC

> Change: `compras-cross-moneda-y-ncs-cc`
> Mode: hybrid (Engram topic `sdd/compras-cross-moneda-y-ncs-cc/tasks` + filesystem)
> Depends on: `proposal.md`, `specs.md`, `design.md`

## Convenciones del task breakdown

- **Batches secuenciales** (1 → 6): el orden es importante. Cada batch = 1 commit (conventional commits, SIN Co-Authored-By) y, según volumen, 1 sub-update o todo agrupado en el PR final.
- **Estimaciones**: S (≤30min), M (30-90min), L (>90min).
- **Mapping Spec ID**: cada task cita FR-XXX / NFR-XXX cuando aplica.
- **Acceptance criteria**: bullets testables, observables (no implementación).
- **Decisiones aplicadas a las Open Questions del design**:
  1. **Redondeo** → `Decimal.ROUND_HALF_UP`, 2 decimales para ARS, 4 decimales para USD (consistente con el resto del módulo). Documentar en el task de conversion.
  2. **ModalAplicarNC con dropdown de NCs** → NO. Solo se acepta prop `pedidoDestinoId` para pre-cargar destino. La selección de NC sigue siendo manual.
  3. **Filtro moneda NC↔pedido** → misma moneda obligatoria (NC USD solo a pedido USD). Cross-moneda NC↔pedido OUT OF SCOPE en este change (solo OP↔pedido es cross-moneda).

- **No tests automáticos como gate** (pytest manual). Pre-commit hook `ruff format check`.

---

## Batch 1: Backend — TC ponderado + endpoints (additive, no breaking)

> Objetivo: agregar capacidades read-only (TC ponderado server-side + endpoint NCs disponibles) sin tocar comportamiento de escritura.
> Commit: `feat(compras): TC ponderado por pedido + endpoint NCs disponibles`

- [ ] **T1.1** — Implementar `pedidos_service.calcular_tc_ponderado_pedido(pedido_id)` con query agregada.
  - **Files**: `backend/app/services/pedidos_service.py`
  - **Acceptance**:
    - Función firmada `(session: Session, pedido_id: int) -> Optional[Decimal]`.
    - Filtra `Imputacion.destino_tipo == "pedido_compra"`, `destino_id == pedido.id`, `moneda_imputada == pedido.moneda`, `tipo_cambio IS NOT NULL`, `es_reversal == False`.
    - Devuelve `Decimal` cuantizado a 4 decimales (`ROUND_HALF_UP`) o `None` si denominador = 0.
  - **Spec mapping**: FR-005 (cálculo correcto).
  - **Estimación**: M

- [ ] **T1.2** — Implementar batch variant `calcular_tc_ponderado_pedido_batch(pedido_ids)`.
  - **Files**: `backend/app/services/pedidos_service.py`
  - **Acceptance**:
    - Firma `(session: Session, pedido_ids: list[int]) -> dict[int, Optional[Decimal]]`.
    - 1 sola query agregada con `GROUP BY destino_id` (sin N+1).
    - Pedido_id ausente del result → `None` en el dict.
  - **Spec mapping**: FR-005 (batch), NFR-001 (N+1 prohibido).
  - **Estimación**: M

- [ ] **T1.3** — Agregar `tipo_cambio_ponderado: Optional[Decimal] = None` a `PedidoCompraResponse` y popular desde router (detalle + listado).
  - **Files**: `backend/app/schemas/pedido_compra.py`, `backend/app/routers/administracion_compras.py` (handlers de detalle + listado de pedidos)
  - **Acceptance**:
    - Schema declara campo opcional, default `None`.
    - Endpoint detalle (`GET /pedidos-compra/{id}`) usa `calcular_tc_ponderado_pedido`.
    - Endpoint listado usa `calcular_tc_ponderado_pedido_batch` antes de armar el response.
  - **Spec mapping**: FR-006, NFR-004 (backward compat — campo opcional).
  - **Estimación**: S

- [ ] **T1.4** — Endpoint `GET /administracion/compras/ncs-locales/disponibles?proveedor_id=X`.
  - **Files**: `backend/app/routers/administracion_compras.py`, `backend/app/schemas/nota_credito_local.py` (nuevo `NCDisponibleSummary`)
  - **Acceptance**:
    - Query param `proveedor_id: int = Query(..., ge=1)` (422 si falta).
    - Filtros: `proveedor_id`, `estado IN ('aprobado', 'aplicada_parcial')`, `saldo_pendiente > 0` (post-filter usando agregación de imps de la NC).
    - Paginación `limit` (default 100, max según policy) + `offset` (default 0).
    - Orden `created_at DESC, id DESC` (NFR-002).
    - Response schema `list[NCDisponibleSummary]` (id, numero, fecha, importe, moneda, saldo_pendiente, estado).
  - **Spec mapping**: FR-007, NFR-002.
  - **Estimación**: L

- [ ] **T1.5** — Enriquecer `GET /administracion/compras/cc-proveedor/{proveedor_id}/por-pedido` con `tc_ponderado` por grupo.
  - **Files**: `backend/app/routers/administracion_compras.py`, `backend/app/schemas/cc_proveedor.py` (campo `tc_ponderado: Optional[Decimal] = None` en `CCAgrupadoPorPedido`)
  - **Acceptance**:
    - Cada grupo del response trae `tc_ponderado` (null si pedido same-moneda).
    - Cálculo usa `calcular_tc_ponderado_pedido_batch` con los `pedido_compra_id` del response (1 query batch).
    - Response sigue siendo `list[CCAgrupadoPorPedido]` (NO se cambia a object) — NCs disponibles se obtienen vía endpoint T1.4 dedicado.
  - **Spec mapping**: FR-008 (parte `tc_ponderado`), NFR-001, NFR-004.
  - **Estimación**: M

- [ ] **T1.6** — Tests unit del batch 1.
  - **Files**:
    - `backend/tests/unit/test_pedidos_service.py` (nuevo o extender)
    - `backend/tests/integration/test_administracion_compras_router.py` (extender)
  - **Acceptance**:
    - `test_tc_ponderado_calcula_promedio_correcto`: 2 imps con TCs distintos → ratio correcto (cuantizado 4 decimales).
    - `test_tc_ponderado_pedido_same_moneda_devuelve_none`: imp sin TC → `None`.
    - `test_tc_ponderado_batch_evita_n1`: usa `assert` sobre contador de queries o `expire_all + query_count` — 1 sola query (NFR-001).
    - `test_endpoint_ncs_disponibles_filtra_por_proveedor_y_saldo`: 3 NCs (aprobado saldo=500, aplicada_parcial saldo=200, aprobado saldo=0) → response con 2 (no la de saldo=0).
    - `test_endpoint_ncs_disponibles_sin_proveedor_id_422`: sin query param → 422.
  - **Spec mapping**: FR-005, FR-007, NFR-001, NFR-005.
  - **Estimación**: L

---

## Batch 2: Backend — Relajar validación cross-moneda en imputaciones

> Objetivo: permitir cross-moneda en `imputaciones_service` cuando viene TC > 0.
> Commit: `feat(compras/imputaciones): permitir cross-moneda con TC obligatorio`

- [ ] **T2.1** — Modificar `_validar_moneda_consistente` para aceptar `tipo_cambio: Optional[Decimal] = None` y permitir cross-moneda cuando TC > 0.
  - **Files**: `backend/app/services/imputaciones_service.py`
  - **Acceptance**:
    - Firma nueva: `_validar_moneda_consistente(origen_moneda, destino_moneda, tipo_cambio=None)`.
    - Same-moneda → return sin error (sin importar TC).
    - Cross-moneda + `tipo_cambio is None or Decimal(tipo_cambio) <= 0` → `HTTPException(400)` con mensaje claro ("Cross-moneda requiere tipo_cambio > 0").
    - Cross-moneda + TC > 0 → return sin error.
  - **Spec mapping**: FR-001.
  - **Estimación**: S

- [ ] **T2.2** — Verificar que `crear_imputacion` no necesita cambios estructurales (el caller pasa `moneda_imputada` correcta + `tipo_cambio`).
  - **Files**: `backend/app/services/imputaciones_service.py`
  - **Acceptance**:
    - Confirmar via lectura de código que `crear_imputacion` recibe `moneda_imputada` y `tipo_cambio` como params y los persiste tal cual.
    - Si hay alguna validación interna que rompa con `moneda_imputada != origen.moneda`, removerla o adaptarla.
    - Comentario en líneas 196-201 (la validación cross-moneda la hace el caller) sigue siendo accurate.
  - **Spec mapping**: FR-002, FR-012 (append-only).
  - **Estimación**: S

- [ ] **T2.3** — Adaptar tests existentes + agregar test nuevo.
  - **Files**: `backend/tests/unit/test_imputaciones_service.py`
  - **Acceptance**:
    - Renombrar `test_cross_moneda_raise_400` → `test_cross_moneda_sin_tc_raise_400`. Reescribir aserciones: la llamada sin TC sigue dando 400, pero el caller del helper ahora pasa TC opcional.
    - Nuevo `test_cross_moneda_con_tc_ok`: `_validar_moneda_consistente("ARS", "USD", tipo_cambio=Decimal("1500"))` no lanza.
    - Mantener `test_cross_moneda_caja_op_con_tc_override_ok` (PR #624) intacto si está en este file.
  - **Spec mapping**: FR-001, NFR-005.
  - **Estimación**: M

---

## Batch 3: Backend — OP cross-moneda en `ejecutar_pago`

> Objetivo: permitir crear/editar/ejecutar OPs cross-moneda con TC; grabar imp en moneda destino.
> Commit: `feat(compras/ordenes-pago): cross-moneda OP↔pedido con conversión por TC`

- [ ] **T3.1** — Renombrar/reescribir `_validar_items_misma_moneda_que_op` → `_validar_items_cross_moneda_con_tc`.
  - **Files**: `backend/app/services/ordenes_pago_service.py`
  - **Acceptance**:
    - Firma nueva: `_validar_items_cross_moneda_con_tc(session, *, items, op_moneda, op_tipo_cambio)`.
    - Same-moneda → continue (no error).
    - Cross-moneda + TC missing/<=0 → `HTTPException(400)` con mensaje detallado por item index (item idx, OP moneda, pedido id, pedido moneda).
    - Cross-moneda + TC > 0 → continue.
  - **Spec mapping**: FR-004.
  - **Estimación**: M

- [ ] **T3.2** — Aplicar la nueva validación en los 3 call sites (`crear`, `editar`, `ejecutar_pago`).
  - **Files**: `backend/app/services/ordenes_pago_service.py`
  - **Acceptance**:
    - `crear()` (línea ~415): pasar `op_tipo_cambio=tipo_cambio` (del payload).
    - `editar()` (líneas ~919 y ~927, ambos call sites): pasar `tc_final` ya resuelto.
    - `ejecutar_pago()` (línea ~725): pasar `op.tipo_cambio` (después de aplicar override si lo hay).
    - Ninguna llamada al helper viejo queda en el codebase.
  - **Spec mapping**: FR-004.
  - **Estimación**: S

- [ ] **T3.3** — Modificar el loop de items en `ejecutar_pago` para convertir cross-moneda y grabar imp en moneda destino.
  - **Files**: `backend/app/services/ordenes_pago_service.py`
  - **Acceptance**:
    - Para cada item con `tipo == "pedido_compra"`, leer `pedido_destino = session.get(PedidoCompra, item.id)`.
    - Si `pedido_destino.moneda != op.moneda`:
      - OP ARS → pedido USD: `monto_imputado = (monto_item_origen / Decimal(tc_op)).quantize(Decimal("0.0001"), ROUND_HALF_UP)` (USD usa 4 decimales).
      - OP USD → pedido ARS: `monto_imputado = (monto_item_origen * Decimal(tc_op)).quantize(Decimal("0.01"), ROUND_HALF_UP)` (ARS usa 2 decimales).
      - `moneda_imputada = pedido_destino.moneda`, `tipo_cambio = Decimal(tc_op)`.
    - Si same-moneda: `monto_imputado = monto_item_origen`, `moneda_imputada = op.moneda`, `tipo_cambio = None`.
    - Saldo "a_cuenta" / mixta sigue en moneda OP origen (sin conversión).
    - Docstring del método actualizado con la fórmula y el redondeo aplicado.
  - **Spec mapping**: FR-002, FR-003.
  - **Estimación**: L

- [ ] **T3.4** — Actualizar docstring de `cc_proveedor_service.aplicar_imputacion` (no cambia código, solo doc).
  - **Files**: `backend/app/services/cc_proveedor_service.py`
  - **Acceptance**:
    - Docstring aclara que en cross-moneda el HABER queda en moneda destino (no origen), y que esto es el resultado esperado por contabilidad.
  - **Spec mapping**: FR-002 (semántica).
  - **Estimación**: S

- [ ] **T3.5** — Tests unit + integration de OP cross-moneda.
  - **Files**:
    - `backend/tests/unit/test_ordenes_pago_service.py`
    - `backend/tests/integration/test_cross_moneda_e2e.py` (nuevo)
  - **Acceptance**:
    - `test_op_cross_moneda_ejecuta_pago_genera_imp_usd` (NEW unit): OP ARS con `tipo_cambio=1500`, item por 1.500.000 ARS de pedido USD → imp resultante con `moneda_imputada=USD`, `monto_imputado=1000.0000`, `tipo_cambio=1500`.
    - `test_op_cross_moneda_sin_tc_raise_400` (NEW unit): mismo escenario sin TC → 400.
    - `test_op_cross_moneda_ejecuta_pago_redondea_half_up` (NEW unit): caso 1.000.000 / 1500 → `666.6667` (no `666.6666`).
    - `test_e2e_op_cross_moneda_ars_paga_pedido_usd` (NEW integration): flujo completo `POST /ordenes-pago` → `POST /pagar` → verificar imp + CC mov HABER USD + caja_movimiento ARS.
    - Tests pre-existentes de cross-moneda caja↔OP (PR #624) siguen pasando sin cambios.
  - **Spec mapping**: FR-003, FR-004, NFR-005.
  - **Estimación**: L

---

## Batch 4: Backend — Reversals cross-moneda (verificación)

> Objetivo: confirmar que `desimputar` ya maneja correctamente el caso cross-moneda (es append-only y copia moneda+monto+TC del original).
> Commit: `test(compras/imputaciones): reversal cross-moneda genera DEBE en moneda destino`

- [ ] **T4.1** — Verificar `desimputar` / `revertir_imputacion` en `imputaciones_service.py` (líneas ~526-618).
  - **Files**: `backend/app/services/imputaciones_service.py`, `backend/app/services/cc_proveedor_service.py`
  - **Acceptance**:
    - Lectura de código confirma que el reversal copia `moneda_imputada`, `monto_imputado`, `tipo_cambio` de la imp original.
    - `cc_proveedor_service.aplicar_imputacion` proyecta el reversal como DEBE en `imp.moneda_imputada` (no en `op.moneda`).
    - Si hay un edge case detectado, abrir un sub-task; si no, este task es solo doc/verify.
  - **Spec mapping**: FR-012 (append-only).
  - **Estimación**: S

- [ ] **T4.2** — Test del reversal cross-moneda.
  - **Files**: `backend/tests/unit/test_imputaciones_service.py`
  - **Acceptance**:
    - `test_reversal_cross_moneda_genera_debe_en_moneda_destino`: imp original USD 666.67 con TC 1500 → reversal USD 666.67 con TC 1500, `es_reversal=True`. Aplicación al CC genera DEBE 666.67 USD.
  - **Spec mapping**: FR-002, FR-012.
  - **Estimación**: M

---

## Batch 5: Frontend — `ModalOrdenPagoNueva` cross-moneda UI

> Objetivo: habilitar la creación de OPs cross-moneda con TC desde la UI, sin confirm destructivo.
> Commit: `feat(compras/ordenes-pago-modal): cross-moneda OP con campo TC`

> **Dependencia**: requiere Batch 3 mergeado (backend acepta cross-moneda con TC).

- [ ] **T5.1** — Detectar cross-moneda y eliminar el confirm destructivo de cambio de moneda con items pre-cargados.
  - **Files**: `frontend/src/components/compras/ModalOrdenPagoNueva.jsx`
  - **Acceptance**:
    - Computar `tieneCrossMoneda = items.some(it => it.tipo === 'pedido_compra' && pedidoDe(it.id).moneda !== form.moneda)`.
    - El `confirmMoneda` (línea ~159) solo dispara si NO hay TC válido (mantiene flujo a_cuenta sin TC).
    - Cuando `tieneCrossMoneda && tcValido` → cambio de moneda procede sin confirm.
  - **Spec mapping**: FR-009.
  - **Estimación**: M

- [ ] **T5.2** — Renderizar input "TC" condicional cuando hay cross-moneda.
  - **Files**: `frontend/src/components/compras/ModalOrdenPagoNueva.jsx`
  - **Acceptance**:
    - El campo `tipo_cambio` (existente en líneas ~504-520) se renderiza si `form.moneda === 'USD'` OR `tieneCrossMoneda`.
    - Label dinámico: `"TC ${form.moneda} ↔ ${otraMoneda}"` cuando es cross-moneda.
    - Placeholder informativo (ej: "1500" si ARS↔USD).
  - **Spec mapping**: FR-009.
  - **Estimación**: S

- [ ] **T5.3** — Validación de submit: bloquear con error inline si TC inválido.
  - **Files**: `frontend/src/components/compras/ModalOrdenPagoNueva.jsx`
  - **Acceptance**:
    - Antes de submit: `requiereTc = form.moneda === 'USD' || tieneCrossMoneda`.
    - Si `requiereTc && !(parseFloat(form.tipo_cambio) > 0)` → setear error inline "TC requerido (> 0) para cross-moneda." y abortar submit.
    - Si OK: `tcEnviable = parseFloat(form.tipo_cambio)` se manda en el payload.
  - **Spec mapping**: FR-009.
  - **Estimación**: S

- [ ] **T5.4** — Mostrar preview de conversión por item cross-moneda.
  - **Files**: `frontend/src/components/compras/ModalOrdenPagoNueva.jsx`
  - **Acceptance**:
    - Debajo del input de monto de cada item cross-moneda, mostrar línea pequeña: `"USD 1000 × TC 1500 = $1.500.000"` (o inversa según direcciones).
    - Solo cuando `form.tipo_cambio > 0` AND item es cross-moneda. Actualiza en tiempo real.
  - **Spec mapping**: FR-009 (UX claridad).
  - **Estimación**: M

- [ ] **T5.5** — Manual QA del modal.
  - **Files**: documentar en este `tasks.md` (sección "QA Notes" al final del batch).
  - **Acceptance**:
    - Checklist documentado: (a) abrir modal con pedido USD pre-cargado, cambiar OP a ARS, verificar que NO aparece confirm destructivo. (b) ingresar TC=1500, verificar preview. (c) submit con TC=0 → error inline. (d) submit con TC=1500 → POST con `tipo_cambio: 1500`.
    - Resultado anotado (PASS/FAIL) por cada item del checklist.
  - **Spec mapping**: FR-009.
  - **Estimación**: M

### Batch 5 QA Checklist

> Implementación verificada por code-walk. `npm run build` y `npx eslint`
> sobre `ModalOrdenPagoNueva.jsx` pasan sin warnings nuevos. Browser QA
> queda pendiente del próximo deploy en staging.

- [ ] **(a) Pedido USD pre-cargado, cambiar OP a ARS → NO confirm destructivo.**
  - Implementado en `frontend/src/components/compras/ModalOrdenPagoNueva.jsx`:
    - Lógica `handleChange('moneda')` líneas 229-262: confirm solo dispara si `tieneItemsPedido && !tcOk`. Si hay TC válido, el cambio procede sin diálogo.
    - El handler `handleConfirmMoneda` (líneas 268-275) ya NO limpia items ni resetea modo. Solo aplica el cambio de moneda; el user carga TC después.
    - Texto del confirm (líneas 854-862) reescrito: "Cross-moneda requiere TC" + "Los items se mantienen".
- [ ] **(b) Ingresar TC=1500 con items cross-moneda → preview se muestra por item.**
  - Implementado en líneas 729-768: bloque IIFE dentro del `<td>` del input de monto. Verifica `tipo === 'pedido_compra'`, `pedido.moneda !== form.moneda`, `tcValido`, y `montoItem > 0`. Renderiza `<div className={styles.previewConversion}>` con el formato `{op} {÷|×} TC {tc} = {dest}` usando `formatCurrency` del propio componente.
  - Dirección: OP ARS / pedido USD → `÷` (montoARS / TC = USD). OP USD / pedido ARS → `×` (montoUSD × TC = ARS).
- [ ] **(c) Submit con TC=0 (o vacío) y cross-moneda → error inline en campo TC, sin POST.**
  - Implementado en `handleSubmit` líneas 369-379: corta antes del `validar()` y setea `tcError`. Render del error inline en líneas 595-602 (`<div id="tc-error" className={styles.errorInline} role="alert">`). Input adopta `aria-invalid="true"` y borde rojo vía `styles.inputError`.
  - El error se limpia en cualquier cambio del campo `tipo_cambio` (línea 261) o de moneda válida (línea 258).
- [ ] **(d) Submit con TC=1500 y cross-moneda → POST con `tipo_cambio: 1500`.**
  - Implementado: `tcEnviable` línea 334 ahora se calcula con `requiereTc = form.moneda === 'USD' || tieneCrossMoneda`. `buildPayload` (línea 339) y `buildEditPayload` (línea 355) mandan `tipo_cambio: tcEnviable` sin cambios.
- [ ] **(e) Label dinámico del campo TC en cross-moneda.**
  - Implementado en líneas 581-585: `"TC {form.moneda} ↔ {otraMonedaCross} *"` (ej. `"TC ARS ↔ USD *"`). Para OP USD sin cross-moneda mantiene `"Tipo de cambio (ARS por 1 USD) *"`.
- [ ] **(f) Field hint cambia según contexto (no se acumula con error).**
  - Implementado líneas 603-609: `errorInline` y `fieldHint` son mutuamente exclusivos (`{tcError ? <errorInline/> : <fieldHint/>}`).

**Notas técnicas adicionales**:
- Lookup `pedidoDe(id)` (líneas 172-179) combina `pendientesDelProveedor` + `pedidoInicial` como fallback. Sin esto, el pedido pre-cargado no aparecería en el detector cross-moneda si el user cambia la moneda del form.
- Filtro `pedidosDisponibles` (líneas 184-189) ahora NO filtra por moneda del form: cross-moneda es válido con TC, así que el dropdown muestra todos los pedidos del proveedor.
- CSS Module: `errorInline`, `inputError`, `previewConversion` agregados a `ModalOrdenPagoNueva.module.css` usando `var(--cf-accent-red)` y `var(--cf-text-tertiary)`. Sin hardcoded colors ni inline styles.

---

## Batch 6: Frontend — `TabCCProveedores` con NCs disponibles + acciones por pedido

> Objetivo: mostrar NCs disponibles en el hero del CC + botones "Aplicar NC" e "Imputar pago" por card de pedido.
> Commit: `feat(compras/cc): NCs disponibles en hero + acciones por pedido (Aplicar NC, Imputar pago)`

> **Dependencia**: requiere Batch 1 (endpoint NCs disponibles + tc_ponderado) y Batch 5 (modal cross-moneda).

- [ ] **T6.1** — Fetch de NCs disponibles en mount + en cambio de proveedor activo.
  - **Files**: `frontend/src/components/compras/TabCCProveedores.jsx`
  - **Acceptance**:
    - Función `fetchNcsDisponibles` que llama `GET /administracion/compras/ncs-locales/disponibles?proveedor_id=X&limit=100`.
    - `useEffect` dispara en `proveedorIdActivo` change.
    - State `ncsDisponibles: NCDisponibleSummary[]` (default `[]`).
    - On error → setea `[]` (no rompe la vista).
  - **Spec mapping**: FR-010 (parte fetch).
  - **Estimación**: S

- [ ] **T6.2** — Sección "NCs disponibles" en el hero (después del header del proveedor).
  - **Files**: `frontend/src/components/compras/TabCCProveedores.jsx`, `frontend/src/components/compras/TabCCProveedores.module.css` (si aplica)
  - **Acceptance**:
    - Render condicional: si `ncsDisponibles.length > 0`.
    - Usar `DataTable` existente (mismo patrón que otras tablas del módulo).
    - Columnas: `número`, `fecha` (formato dd/mm/yyyy), `importe` (formatCurrency con moneda), `saldo` (formatCurrency con moneda).
    - Sin paginación visual en hero (max 100 ya viene del backend; si proveedor tiene más, queda truncado).
  - **Spec mapping**: FR-010 (hero NCs).
  - **Estimación**: M

- [ ] **T6.3** — `GrupoPedidoCard` (vista por-pedido): agregar botones "Aplicar NC" e "Imputar pago" en footer.
  - **Files**: `frontend/src/components/compras/TabCCProveedores.jsx` (componente interno `GrupoPedidoCard` línea ~786), `TabCCProveedores.module.css`
  - **Acceptance**:
    - Footer del card con 3 botones (orden): `Aplicar NC`, `Imputar pago`, `Desimputar` (existente).
    - Estilo consistente con el resto del módulo (Tesla Design System).
    - Botones reciben handlers `onAplicarNC` / `onImputarPago` como props nuevos.
  - **Spec mapping**: FR-010 (acciones por card).
  - **Estimación**: M

- [ ] **T6.4** — Handler `onAplicarNC(pedidoId)` → abre `ModalAplicarNC` con prop `pedidoDestinoId`.
  - **Files**: `frontend/src/components/compras/TabCCProveedores.jsx`
  - **Acceptance**:
    - State `showAplicarNCDesdeCard: { pedidoId } | null`.
    - Setear `null` al click del botón.
    - Modal monta cuando state ≠ null.
    - Al cerrar con reload → refetch `fetchPorPedido` + `fetchNcsDisponibles`.
  - **Spec mapping**: FR-010 (acción Aplicar NC).
  - **Estimación**: S

- [ ] **T6.5** — Handler `onImputarPago(pedidoId)` → abre `ModalOrdenPagoNueva` con pedido + proveedor pre-cargados.
  - **Files**: `frontend/src/components/compras/TabCCProveedores.jsx`
  - **Acceptance**:
    - State `showImputarPagoDesdeCard: { pedidoId } | null`.
    - Encontrar `pedidoInicial` desde `porPedido` por `pedido_compra_id`.
    - Pasar `proveedorInicial={proveedorCtx}` (ya cargado).
    - Al cerrar con reload → refetch `fetchDetalle + fetchPorPedido + fetchNcsDisponibles`.
  - **Spec mapping**: FR-010 (acción Imputar pago).
  - **Estimación**: S

- [ ] **T6.6** — `ModalAplicarNC.jsx`: aceptar prop `pedidoDestinoId` y pre-cargar destino.
  - **Files**: `frontend/src/components/compras/ModalAplicarNC.jsx`
  - **Acceptance**:
    - Nueva prop `pedidoDestinoId: number | null = null`.
    - `useEffect` on mount: si `pedidoDestinoId` viene → setear `destinoTipo='pedido_compra'`, `pedidoId=String(pedidoDestinoId)`.
    - Selector de destino deshabilitado (read-only) cuando `pedidoDestinoId` viene.
    - **NO se agrega dropdown de NCs disponibles** (decisión: la NC sigue eligiéndose manualmente, el modal asume `nc` prop como hoy).
    - Si `nc` no viene Y `pedidoDestinoId` viene → mostrar error o cerrar (no se soporta este combo en v1).
  - **Spec mapping**: FR-011.
  - **Estimación**: M

- [ ] **T6.7** — Renderizar `tc_ponderado` debajo del header de cada pedido USD que lo tenga.
  - **Files**: `frontend/src/components/compras/TabCCProveedores.jsx` (componente `GrupoPedidoCard`)
  - **Acceptance**:
    - Si `grupo.tc_ponderado != null` → render línea `<span>TC pond.: {Number(grupo.tc_ponderado).toFixed(2)}</span>` debajo del header.
    - Si `null` → no se renderiza nada (no aparece "TC pond.: -" ni similar).
    - Estilo discreto (color secundario, font-size menor que el header).
  - **Spec mapping**: FR-010 (TC ponderado en UI), FR-008.
  - **Estimación**: S

- [ ] **T6.8** — Manual QA del CC.
  - **Files**: documentar en sección "QA Notes" al final.
  - **Acceptance**:
    - Checklist documentado: (a) seleccionar proveedor con NCs aprobadas → hero muestra tabla. (b) seleccionar proveedor sin NCs → hero NO muestra sección (no muestra `[]` ni tabla vacía). (c) click "Aplicar NC" en card → modal abre con pedido pre-cargado, selector deshabilitado. (d) click "Imputar pago" en card → modal abre con pedido + proveedor pre-cargados. (e) pedido USD con imps cross-moneda → header muestra "TC pond.: 1500.00". (f) pedido same-moneda → no muestra línea de TC pond.
    - Resultado anotado (PASS/FAIL) por cada item.
  - **Spec mapping**: FR-010, FR-011.
  - **Estimación**: M

---

## Orden de ejecución y dependencias

```
Batch 1 (BE read-only)  ─────┐
                              ├──▶ Batch 5 (FE modal OP) ──▶ Batch 6 (FE CC)
Batch 2 (BE imp val)    ──┐  │
                          ├──┴──▶ Batch 3 (BE OP cross-moneda) ──▶ Batch 4 (BE reversals)
                          │
```

- **Batches 1, 2** pueden ejecutarse en paralelo (touch separate files, both additive).
- **Batch 3** depende de 2 (valida con TC vía helper) y consume helpers de 1 (`calcular_tc_ponderado_pedido` para tests de regresión).
- **Batch 4** depende de 3 (reversals de imps cross-moneda).
- **Batch 5** depende de 3 mergeado (backend acepta cross-moneda con TC).
- **Batch 6** depende de 1 (endpoint NCs disponibles + tc_ponderado) y 5 (modal cross-moneda completo).

Recomendación práctica: ejecutar **secuencial 1 → 2 → 3 → 4 → 5 → 6** para evitar branches paralelos.

---

## QA Notes (a completar durante implementación)

### Batch 5 QA Checklist

- [ ] Abrir `ModalOrdenPagoNueva` con pedido USD pre-cargado, cambiar OP a ARS → **NO** aparece confirm destructivo.
- [ ] Ingresar TC=1500 → preview muestra `"USD 1000 × TC 1500 = $1.500.000"` debajo del monto.
- [ ] Submit con TC vacío o ≤ 0 → error inline "TC requerido (> 0) para cross-moneda."
- [ ] Submit con TC=1500 → POST con `tipo_cambio: 1500` en payload; modal cierra al recibir 201.

### Batch 6 QA Checklist

- [ ] Proveedor con 2 NCs aprobadas → hero muestra tabla con número, fecha, importe, saldo.
- [ ] Proveedor sin NCs disponibles → hero **NO** renderiza la sección.
- [ ] Click "Aplicar NC" en card de pedido → `ModalAplicarNC` abre con pedido pre-cargado y selector deshabilitado.
- [ ] Click "Imputar pago" en card de pedido → `ModalOrdenPagoNueva` abre con pedido + proveedor pre-cargados.
- [ ] Pedido USD con imps cross-moneda → header del card muestra `"TC pond.: 1500.00"`.
- [ ] Pedido same-moneda → header del card **NO** muestra línea de TC pond.

### E2E QA Checklist (post-merge a develop)

- [ ] Crear OP ARS con item pedido USD + TC=1500 → OK (no 400).
- [ ] Ejecutar OP → imp con `moneda_imputada=USD`, `monto_imputado` convertido, `tipo_cambio=1500` persistido.
- [ ] CC del proveedor muestra HABER USD; caja ARS muestra egreso ARS.
- [ ] `GET /pedidos-compra/{id}` devuelve `tipo_cambio_ponderado` correcto.
- [ ] Reversal de imp cross-moneda → DEBE USD en CC; OP NO se anula (verificar tooltip).
- [ ] Aplicar NC desde hero → modal abre, user elige pedido manual; aplicación OK.
- [ ] Aplicar NC desde card de pedido → modal abre con pedido pre-cargado.

---

## Resumen

| Batch | Tasks | Foco | Riesgo |
|-------|-------|------|--------|
| 1 | 6 | BE additive: TC ponderado helpers + endpoint NCs disponibles | Bajo (additive) |
| 2 | 3 | BE imputaciones: relajar validación cross-moneda con TC | Medio (rompe 1 test, semántica de helper) |
| 3 | 5 | BE OP: validar+convertir cross-moneda en `ejecutar_pago` | Alto (core write path) |
| 4 | 2 | BE reversals: verificar comportamiento cross-moneda | Bajo (verify + 1 test) |
| 5 | 5 | FE modal OP: habilitar UI cross-moneda con TC | Medio (UX changes) |
| 6 | 8 | FE CC: NCs disponibles + acciones por pedido | Medio (componentes nuevos en hero + footer card) |
| **Total** | **29** | | |

Total de tasks: **29**.
Mapeo a specs: FR-001 a FR-013 + NFR-001 a NFR-005 cubiertos en algún task.
