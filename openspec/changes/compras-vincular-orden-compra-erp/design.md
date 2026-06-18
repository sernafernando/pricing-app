# Design — Vincular OC del ERP al Pedido + Ingreso por Depósito

**Change:** `compras-vincular-orden-compra-erp`
**Fase:** design
**Status:** draft
**Persistence mode:** hybrid
**Fecha:** 2026-06-18

---

## 0. Resumen ejecutivo de decisiones

| #   | Tema | Decisión | Resuelve |
|-----|------|----------|----------|
| AD1 | Cardinalidad | Uno-a-uno. 3 cols nullable en `pedidos_compra` (`oc_comp_id` INT, `oc_bra_id` INT, `oc_poh_id` BIGINT). FK lógica sin constraint físico (espeja `ct_transaction_id`). | D1 |
| AD2 | Criterio "OC pendiente de recepción" | OC con al menos una línea NO procesada: `bool_and(COALESCE(d.pod_isprocessed, FALSE)) = FALSE`. Excluye OCs ya vinculadas a otro pedido. VERIFICADO contra data real (pod_isprocessed: 265 t / 11 f / 0 null). Descartados `pho_selectedinrecepcion` (no confiable) y `pod_confirmedqty` (siempre 0 en compras). | R1 |
| AD3 | Saldo pendiente por línea | `saldo = pod_qty - pod_confirmedqty - SUM(ingresos.cantidad_recibida del pricing-app)`. El `pod_confirmedqty` es el confirmado en el ERP; nuestros ingresos son registro interno adicional. | R2 |
| AD4 | Granularidad del ingreso | Una fila por línea de OC recibida (grano `pod_id`), recepción parcial/acumulada. La identidad de línea se persiste como snapshot: `oc_comp_id/oc_bra_id/oc_poh_id/pod_id`. | R2 |
| AD5 | Desvincular con ingresos | Permitido. Desvincular limpia las 3 cols pero **NO borra** filas de `pedido_compra_ingresos` (registro histórico inmutable). Se advierte en UI si hay ingresos. | R3, D4 |
| AD6 | Detalle de OC en vivo | El desglose lee el mirror en vivo (`tb_purchase_order_detail` join `tb_storage`). El ingreso es snapshot del momento (no se re-deriva del ERP). | R3 |
| AD7 | Permiso | `administracion.gestionar_ordenes_compra` para TODOS los endpoints (link + desglose + ingresos). No se crea permiso nuevo. | D5, R4 |
| AD8 | Stock / ERP | Solo registro interno. NUNCA se escribe stock ni se escribe al ERP. Los mirrors son READ-ONLY. | D7 |
| AD9 | Ubicación | Endpoints en `routers/administracion_compras.py` (Batch J), lógica en `services/oc_ingresos_service.py` (nuevo) + helpers reutilizados de `pedidos_service.py`. | — |

---

## 1. Slices

- **Slice 1 — Vínculo OC + desglose read-only.** Migración `+3 cols`. Endpoints: `oc-candidatas`, `vincular-oc`, `desvincular-oc`, `orden-compra/detalle`. `ModalVincularOC.jsx` + sección desglose read-only en `ModalPedidoDetalle.jsx`. ~380 líneas.
- **Slice 2 — Confirmar ingreso por depósito.** Migración tabla `pedido_compra_ingresos`. Endpoints: `GET/POST .../ingresos`. UI confirmar ingreso (campo cantidad por línea + saldo). ~400 líneas.

Cada slice es un PR encadenado; Slice 2 depende de Slice 1 (necesita las 3 cols pobladas para resolver la OC del pedido).

---

## 2. Criterio "OC pendiente de recepción" (R1 RESUELTO)

### Columnas REALES disponibles (verificadas en los modelos)

- `tb_purchase_order_header`: `supp_id`, `pho_selectedinrecepcion` (Boolean, **typo del ERP conservado**: `pho_` no `poh_`), `poh_cd`, `poh_total`, `poh_deliverydate`.
- `tb_purchase_order_detail`: `pod_qty` (Numeric), `pod_confirmedqty` (Numeric), `pod_initqty` (Numeric), `stor_id`, `item_id`, `pod_price`.

NO existe ninguna columna de "estado" tipo `poh_status`. Por eso el criterio se deriva.

### Criterio elegido (VERIFICADO contra data real — 2026-06-18)

Una OC es candidata si:

1. `h.supp_id = :supp_id` (proveedor del pedido), Y
2. tiene al menos una línea NO procesada: `bool_and(COALESCE(d.pod_isprocessed, FALSE)) = FALSE` (en `HAVING`), Y
3. `(h.comp_id, h.bra_id, h.poh_id)` no está vinculada a OTRO pedido (`pedidos_compra` con esas 3 cols y `id <> :pedido_id`).

**Razón:** Regla de negocio confirmada por el usuario (dueño del dominio): `pod_isProcessed = TRUE` en una línea significa que ya se recibió y procesó; una OC está totalmente recibida cuando TODAS sus líneas están processed. Por ende "pendiente de recepción" = la OC tiene al menos una línea sin procesar.

### Verificación contra data real (ejecutada 2026-06-18)

- **`pho_selectedinrecepcion` — DESCARTADO.** Distribución real 17 `t` / 3 `f` / 4 NULL, pero tanto OCs abiertas como cerradas pueden tenerlo en `false`: no refleja el estado de recepción.
- **`pod_confirmedqty` — DESCARTADO.** Las 276 líneas en `0` (solo se usa en ventas/importación), así que el saldo `pod_qty - pod_confirmedqty` es inútil en compras.
- **`pod_isprocessed` — ELEGIDO.** Poblado y discriminante: 265 `t` / 11 `f`, sin NULLs. Es el único campo sincronizado que refleja recepción real.

---

## 3. Data model

### 3.1 `pedidos_compra` (+3 columnas) — Slice 1

```sql
ALTER TABLE pedidos_compra ADD COLUMN oc_comp_id INTEGER;     -- FK lógica → tb_purchase_order_header.comp_id
ALTER TABLE pedidos_compra ADD COLUMN oc_bra_id  INTEGER;     -- FK lógica → tb_purchase_order_header.bra_id
ALTER TABLE pedidos_compra ADD COLUMN oc_poh_id  BIGINT;      -- FK lógica → tb_purchase_order_header.poh_id

-- Índice parcial: filtra rápido las que tienen OC vinculada (espeja ix_pedidos_compra_ct_transaction)
CREATE INDEX ix_pedidos_compra_oc_poh
    ON pedidos_compra (oc_comp_id, oc_bra_id, oc_poh_id)
    WHERE oc_poh_id IS NOT NULL;
```

Sin FK física (los 3 forman la PK compuesta del mirror read-only; una FK real bloquearía el sync). Las 3 son nullable; o las 3 están seteadas o las 3 son NULL (invariante validado en el servicio, no por constraint para no complicar el sync/backfill). Tipos espejan el mirror: `comp_id`/`bra_id` = `Integer`, `poh_id` = `BigInteger`.

Modelo SQLAlchemy en `pedido_compra.py`: 3 `Column` nullable + `Index("ix_pedidos_compra_oc_poh", ..., postgresql_where="oc_poh_id IS NOT NULL")`.

### 3.2 `pedido_compra_ingresos` (NUEVA) — Slice 2

```sql
CREATE TABLE pedido_compra_ingresos (
    id                  BIGSERIAL    PRIMARY KEY,
    pedido_id           BIGINT       NOT NULL REFERENCES pedidos_compra(id) ON DELETE RESTRICT,
    -- Snapshot de la identidad de la línea de OC (FK lógica al mirror, sin constraint físico)
    oc_comp_id          INTEGER      NOT NULL,
    oc_bra_id           INTEGER      NOT NULL,
    oc_poh_id           BIGINT       NOT NULL,
    pod_id              BIGINT       NOT NULL,
    item_id             INTEGER      NOT NULL,
    stor_id             INTEGER      NOT NULL,   -- depósito (snapshot de pod.stor_id)
    cantidad_recibida   NUMERIC(18,6) NOT NULL CHECK (cantidad_recibida > 0),
    fecha_ingreso       DATE         NOT NULL DEFAULT CURRENT_DATE,
    usuario_id          INTEGER      NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    observaciones       TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX ix_pci_pedido        ON pedido_compra_ingresos (pedido_id);
CREATE INDEX ix_pci_oc_linea      ON pedido_compra_ingresos (oc_comp_id, oc_bra_id, oc_poh_id, pod_id);
```

**Decisiones:**

- **Append-only.** Cada confirmación de recepción es una fila nueva; el saldo se computa restando la suma. Corregir un error = registrar un ingreso de ajuste negativo NO se permite (CHECK > 0); para v1 los errores se manejan a nivel proceso (no hay delete en API). Si se necesita revertir, es tarea futura (campo `es_reversal`, fuera de scope).
- **Snapshot de identidad de línea** (`oc_*` + `pod_id` + `item_id` + `stor_id`): si el ERP re-sincroniza y cambia la OC, el ingreso histórico queda intacto (AD6). No hay FK física al mirror.
- **`ON DELETE RESTRICT` sobre `pedido_id`**: no permitir borrar un pedido con ingresos registrados.
- **NO** se escribe en `stock_por_deposito` ni en el ERP (AD8).

### 3.3 Plan de migraciones Alembic

Naming del proyecto: `YYYYMMDD_descripcion.py` (revisión slug). Dos migraciones, una por slice:

1. `20260618_add_oc_link_to_pedidos_compra.py` (Slice 1): `op.add_column` x3 + `op.create_index` parcial. `downgrade` dropea índice + 3 cols.
2. `20260619_create_pedido_compra_ingresos.py` (Slice 2): `op.create_table` + 2 índices. `downgrade` dropea tabla. `down_revision` = la de Slice 1.

Sin backfill (cols arrancan NULL; tabla arranca vacía).

---

## 4. Backend

### 4.1 Ubicación

- Endpoints: `routers/administracion_compras.py`, nuevo bloque **"Batch J — Vincular OC del ERP + ingreso por depósito"**, inmediatamente después del Batch I (factura). Mismos helpers: `_obtener_pedido_o_404`, `_pedido_response`, `_commit_or_rollback`, `require_permiso(...)`.
- Lógica de vínculo: extender `services/pedidos_service.py` con `vincular_oc` / `desvincular_oc` (espejan `vincular_factura`/`desvincular_factura`, incluido `_registrar_evento` con nuevos tipos `OC_VINCULADA` / `OC_DESVINCULADA`).
- Lógica de ingresos + candidatas + desglose: nuevo `services/oc_ingresos_service.py`.

### 4.2 Endpoints (todos `Depends(require_permiso("administracion.gestionar_ordenes_compra"))`)

| Método | Ruta | Slice | Descripción |
|--------|------|-------|-------------|
| GET | `/pedidos/{id}/oc-candidatas` | 1 | OCs pendientes del proveedor (criterio §2) |
| POST | `/pedidos/{id}/vincular-oc` | 1 | Setea las 3 cols. Body `{oc_comp_id, oc_bra_id, oc_poh_id}` |
| DELETE | `/pedidos/{id}/desvincular-oc` | 1 | Limpia las 3 cols (no borra ingresos) |
| GET | `/pedidos/{id}/orden-compra/detalle` | 1 | Desglose líneas+depósito (read-only del mirror) + saldo por línea |
| GET | `/pedidos/{id}/ingresos` | 2 | Lista ingresos registrados del pedido |
| POST | `/pedidos/{id}/ingresos` | 2 | Registra recepción parcial de una línea |

### 4.3 Query `oc-candidatas`

`supp_id` desde `proveedores` (mismo patrón que facturas-candidatas: `SELECT supp_id FROM proveedores WHERE id=:pid`; si NULL → `[]` + WARNING). Luego (raw `text()` como el resto del módulo):

```sql
SELECT h.comp_id, h.bra_id, h.poh_id, h.poh_total, h.poh_cd,
       SUM(d.pod_qty) AS qty_total,
       COUNT(*) FILTER (WHERE COALESCE(d.pod_isprocessed, FALSE) = FALSE) AS lineas_pendientes
FROM tb_purchase_order_header h
JOIN tb_purchase_order_detail d
  ON (d.comp_id, d.bra_id, d.poh_id) = (h.comp_id, h.bra_id, h.poh_id)
WHERE h.supp_id = :supp_id
  AND NOT EXISTS (
      SELECT 1 FROM pedidos_compra p
      WHERE p.oc_poh_id = h.poh_id AND p.oc_comp_id = h.comp_id
        AND p.oc_bra_id = h.bra_id AND p.id <> :pedido_id
  )
GROUP BY h.comp_id, h.bra_id, h.poh_id, h.poh_total, h.poh_cd
HAVING bool_and(COALESCE(d.pod_isprocessed, FALSE)) = FALSE  -- al menos una línea sin procesar
ORDER BY h.poh_cd DESC NULLS LAST
LIMIT 100
```

Response `OCCandidataResponse`: `{oc_comp_id, oc_bra_id, oc_poh_id, poh_total, poh_cd, qty_total, lineas_pendientes}`.

### 4.4 Desglose `orden-compra/detalle` + saldo (AD3)

Lee la OC vinculada del pedido (404 si pedido no existe; 400 si pedido sin OC vinculada). Join detalle→storage; por cada línea computa saldo restando los ingresos del pricing-app:

```sql
SELECT d.pod_id, d.item_id, d.stor_id, s.stor_desc,
       d.pod_qty, d.pod_confirmedqty, d.pod_price
FROM tb_purchase_order_detail d
LEFT JOIN tb_storage s
  ON s.comp_id = d.comp_id AND s.stor_id = d.stor_id
WHERE (d.comp_id, d.bra_id, d.poh_id) = (:comp, :bra, :poh)
ORDER BY d.pod_id
```

Por línea: `recibido_pricing = SELECT COALESCE(SUM(cantidad_recibida),0) FROM pedido_compra_ingresos WHERE oc_*=... AND pod_id=d.pod_id`. `saldo_pendiente = pod_qty - COALESCE(pod_confirmedqty,0) - recibido_pricing`. (En Slice 1 `recibido_pricing` siempre 0 — la tabla no existe aún; el campo se agrega en Slice 2.) Agrupar por `stor_desc` en la respuesta para el desglose por depósito.

### 4.5 `vincular-oc` / `desvincular-oc`

- `vincular_oc`: 404 si pedido inexistente; 409 si ya tiene OC (`oc_poh_id IS NOT NULL`); 400 si proveedor sin `supp_id` o la `(comp,bra,poh)` no es candidata válida para ese proveedor (re-corre el criterio §2). Setea las 3 cols, `_registrar_evento(OC_VINCULADA)`, no commit (el router commitea). Es **mutable**: para re-vincular, primero desvincular.
- `desvincular_oc`: 404; 400 si `oc_poh_id IS NULL`. Si existen ingresos para esa OC+pedido NO los borra (AD5); limpia las 3 cols, `_registrar_evento(OC_DESVINCULADA, payload={oc anterior, ingresos_count})`.

### 4.6 `POST /ingresos` (Slice 2)

Body `IngresoCreateRequest`: `{pod_id, cantidad_recibida, fecha_ingreso?, observaciones?}`. Validaciones:

1. Pedido existe y tiene OC vinculada (400 si no).
2. `pod_id` pertenece a la OC vinculada (400 si no) → de ahí se derivan `item_id` y `stor_id` (snapshot del mirror).
3. `cantidad_recibida > 0` (422 Pydantic) y `<= saldo_pendiente` de esa línea (409 si excede; recepción acumulada no puede superar lo pedido).
4. Inserta fila con `usuario_id = user.id`. `_commit_or_rollback`.

`GET /ingresos` → lista `IngresoResponse` ordenada por `created_at DESC`.

### 4.7 Schemas Pydantic (`schemas/pedido_compra.py` o nuevo `schemas/oc_ingreso.py`)

`OCCandidataResponse`, `VincularOCRequest`, `OrdenCompraDetalleResponse` (lista de líneas con `stor_desc`, `pod_qty`, `saldo_pendiente`), `IngresoCreateRequest`, `IngresoResponse`. Todos con type hints completos y `response_model` explícito en el router.

---

## 5. Frontend

### 5.1 `ModalVincularOC.jsx` (Slice 1, nuevo)

Espeja `ModalVincularFactura.jsx`: sub-modal abierto desde `ModalPedidoDetalle.jsx`. Props `{ pedido, onClose }`. `usePermisos()` para gate. Tabla radio-select de candidatas (`oc-candidatas`), columnas: Nº OC (`poh_id`), Fecha (`poh_cd`), Total (`poh_total`), Qty pendiente. Botón "Vincular" → `POST vincular-oc`. CSS Module `ModalVincularOC.module.css` (clona estructura del de factura, tokens Tesla `var(--bg-primary)` etc, sin Tailwind, sin inline styles). Iconos `lucide-react` (`Link2`, `Loader2`, `X`, `AlertCircle`). `api` desde `services/api.js`.

### 5.2 Desglose en `ModalPedidoDetalle.jsx` (Slice 1)

Nueva sección read-only "Orden de compra" debajo de la de factura: si `pedido.oc_poh_id`, muestra Nº OC + botón "Desvincular OC" (gate permiso) y una tabla del desglose (`GET orden-compra/detalle`) agrupada por depósito: Depósito | Item | Pedido (`pod_qty`) | Saldo pendiente. Si no hay OC vinculada → botón "Vincular OC" que abre `ModalVincularOC`. Patrón condicional idéntico al de `ModalVincularFactura` (línea ~819).

### 5.3 Ingreso UI (Slice 2)

En la misma tabla del desglose, columna acción "Confirmar ingreso" por línea con saldo > 0 → `ModalConfirmarIngreso.jsx` (input cantidad ≤ saldo, fecha, observaciones) → `POST ingresos`. Bajo la tabla, historial de ingresos (`GET ingresos`): fecha, item, depósito, cantidad, usuario. Recalcula saldo al confirmar (refetch desglose).

### 5.4 Service / estado

Llamadas vía `api` (axios) directo en el componente o en un hook `useComprasPedidos.js` extendido (ya existe y referencia endpoints de factura) — preferir extender el hook existente para consistencia. Estado local (`useState`) para candidatas/desglose/loading; sin Zustand nuevo (no es estado global).

---

## 6. Rollout por slice

- **Slice 1:** migración cols → deploy backend (endpoints + servicio) → deploy frontend (modal + desglose). Reversible: `downgrade` dropea cols (ningún ingreso depende aún).
- **Slice 2:** migración tabla → backend ingresos → frontend confirmar ingreso. Reversible mientras no haya filas; con filas, el `downgrade` las pierde (documentar).
- Antes de Slice 1: correr las queries de verificación §2 y confirmar/ajustar el criterio.

---

## 7. Riesgos

- **R1 (resuelto, requiere verificación):** criterio "pendiente" depende de `pho_selectedinrecepcion` + `pod_confirmedqty`, cuya semántica real en compras NO está confirmada. Mitigación: queries §2 + criterio parametrizable + fallback documentado. **Bloqueante de Slice 1 hasta verificar.**
- **R2 (medio):** doble registro de ingreso (mismo pod_id dos veces) — mitigado por validación `<= saldo_pendiente` acumulado, no por unique (la recepción parcial es legítimamente múltiple).
- **R3 (medio):** OC cambia en el ERP post-vínculo. Desglose lee en vivo (puede cambiar); ingreso es snapshot. Aceptado por diseño (AD6).
- **R4 (bajo):** `comp_id`/`bra_id` del mirror — el módulo de compras ya asume `empresa_id`↔`comp_id` 1↔1 (ver `modulo-compras` D14). Las candidatas filtran solo por `supp_id`, no por `comp_id`, así que no se rompe.
- **R5 (bajo):** invariante "las 3 cols juntas o ninguna" no está en constraint DB; depende del servicio. Aceptable (mismo nivel de garantía que `ct_transaction_id`).

---

## 8. Testabilidad (Strict TDD — pytest)

Tests primero en ambos slices. Patrón: tests de integración bajo `backend/tests/integration/` espejando `test_compras_vincular_factura_endpoints.py`.

- **Slice 1:** `test_oc_candidatas_filtra_por_supp_id_y_pendiente`, `test_oc_candidatas_excluye_ya_vinculadas`, `test_vincular_oc_setea_3_cols`, `test_vincular_oc_409_si_ya_vinculado`, `test_vincular_oc_400_proveedor_sin_supp_id`, `test_desvincular_oc_limpia_cols`, `test_orden_compra_detalle_agrupa_por_deposito`. Fixtures: seed `tb_purchase_order_header/detail` + `tb_storage` + `proveedores.supp_id`.
- **Slice 2:** `test_post_ingreso_inserta_fila`, `test_post_ingreso_409_excede_saldo`, `test_post_ingreso_400_pod_no_pertenece_a_oc`, `test_saldo_descuenta_ingresos_acumulados`, `test_desvincular_no_borra_ingresos`, `test_ingreso_nunca_escribe_stock` (assert `stock_por_deposito` sin cambios).
- Permiso: cada endpoint con test 403 sin `administracion.gestionar_ordenes_compra`.
