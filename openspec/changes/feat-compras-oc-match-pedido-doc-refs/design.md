# Design: Persist OC-match document numbers on PedidoCompra

## Technical Approach

Add two nullable Text columns on `pedidos_compra`. Extract returns `tipo_documento`; match passes it through; a helper appends unique tokens in the worker persist session (`SELECT FOR UPDATE`, never `editar_pedido`). Operator APIs expose the fields like `observaciones`. FE adds Factura/s and Pedido/s on the three pedido modals (`numero_factura` pattern).

Implements locked deltas: `compras-oc-match-pipeline` and `pedidos-compra`.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|---|---|---|---|
| Storage | widen `numero_factura` / JSON / two Text | ERP `match_forward` + `String(50)` vs extra table | `facturas_documento`, `pedidos_documento` Text NULL, no index |
| Write path | `editar_pedido` vs persist session | `EDITADO` + `match_forward` vs no audit event | Persist session only |
| Extract header | write from `matched` only vs keep `extracted` | match/excel exceptions drop numbers | Keep `extracted`; write-back if `extract_one` returned |
| tipo normalize | prompt-only vs worker aliases | Gemini drift | Worker lowercase/strip + locked aliases; unknown/null → `otro` |
| Create persist | schema-only (today `observaciones` is dropped on POST) vs wire `crear_pedido` | follow silent drop vs spec “create persists” | Add both kwargs on `crear_pedido` + router; do not fix `observaciones` |
| FE | list/chips vs three modals | 400-line budget | Existing `formGroup` inputs; no CSS redesign |

## Data Flow

```
enqueue (MIME unchanged)
    → extract_one (+ tipo_documento)
    → match_renglones (pass-through header)
    → generar Excel (may RechazoExcel)
    → acta (+ one Tipo documento: line)
    → _persist (claim fence)
         → renglones
         → SELECT PedidoCompra FOR UPDATE (job.pedido_id)
         → doc_refs.apply_writeback(pedido, extracted or {})
```

Write-back if extract header exists, tipo ∈ {factura, pedido, proforma, nota_venta}, and at least one non-empty number. `comprobante_pago` / `otro` / unknown: no column write; job still persists. Empty extract: no-op. Excel `error` after extract still writes.

```
factura:            nro_documento → facturas_documento; nro_pedido → pedidos_documento
pedido|proforma|NV: both numbers → pedidos_documento
never:             numero_factura
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/alembic/versions/compras_042_pedido_doc_refs.py` | Create | Two Text NULL; `down_revision = compras_041_oc_match_progress_phase`; no index; rehang if tip moved |
| `backend/app/services/oc_match/doc_refs.py` | Create | normalize, parse, append_unique, route, apply_writeback |
| `backend/tests/unit/test_oc_match_doc_refs.py` | Create | routing, aliases, append/dedupe, skip tipos, never `numero_factura` |
| `backend/app/models/pedido_compra.py` | Modify | Two Text columns after `observaciones` |
| `backend/app/schemas/pedido_compra.py` | Modify | Both on Base, Update, CorreccionPedidoRequest; no `max_length` |
| `backend/app/services/pedidos_service.py` | Modify | Both `CAMPOS_EDITABLES_*`; `crear_pedido` kwargs; clone + `cambios_persistidos`; not `CAMPOS_FINANCIEROS_CORRECCION` |
| `backend/app/routers/administracion_compras.py` | Modify | Pass new kwargs into `crear_pedido` |
| `backend/app/services/oc_match/extract.py` | Modify | JSON + prompt: `tipo_documento` enum |
| `backend/app/services/oc_match/match.py` | Modify | Pass `tipo_documento` in return dict |
| `backend/app/services/oc_match/acta.py` | Modify | One `Tipo documento:` line after nro documento |
| `backend/app/services/oc_match/worker.py` | Modify | Keep `extracted`; after fence+renglones lock pedido and apply write-back |
| `backend/tests/unit/test_oc_match_pipeline.py` | Modify | Acta line; add `doc_refs.py` to mail-ban list |
| `backend/tests/integration/test_oc_match_worker.py` | Modify | GOLDEN `tipo_documento=factura`; assert columns; duplicate no-op; RechazoExcel writes; missing extract does not |
| `backend/tests/unit/test_pedidos_service.py` | Modify | Editable in aprobado; PUT does not call `match_forward` |
| `backend/tests/unit/test_pedidos_corregir.py` | Modify | Clone inherits; financial rules unchanged |
| `frontend/src/components/compras/ModalPedidoCompra.jsx` | Modify | State, create + metadata PUT, two inputs after `numero_factura` |
| `frontend/src/components/compras/ModalPedidoDetalle.jsx` | Modify | Two info rows after N° Factura; null → `—` |
| `frontend/src/components/compras/ModalCorregirPedido.jsx` | Modify | State, fields, payload only when changed |

## Interfaces / Contracts

`doc_refs` is the only new module. Extract numbers are single tokens (do not split on `;`). Stored columns parse on `;` then strip; join with `; `; casefold-dedupe keeps first-seen casing. `apply_writeback` mutates only the two columns.

Pydantic: `facturas_documento: str | None = None` (no max_length). Operator PUT replacement string is the only wipe. `None` ignored like `observaciones` (`exclude_none` + `v is not None`). Modal `|| null` cannot wipe.

Worker must not call `editar_pedido`. `SELECT FOR UPDATE` serializes concurrent jobs on the same pedido.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|--------------|----------|
| Unit | routing, aliases, append, skip, never `numero_factura` | `test_oc_match_doc_refs.py` |
| Unit | edit + clone inherit, no `match_forward` | extend pedidos service/corregir tests |
| Integration | golden factura write, duplicate no-op, excel-error writes, missing extract no-op | `test_oc_match_worker.py` |
| E2E | — | N/A (no modal tests; no list UX) |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

Alembic adds two nullable columns (existing rows stay NULL). Downgrade drops them. Re-check `alembic heads` on `feat/compras-oc-match-pedido-doc-refs` before writing; do not merge unrelated `upstream/main` heads. No feature flag. Single PR to `main`.

## Open Questions

None — `state.yaml` `locked_decisions` cover storage, routing, write-back, FE, and Alembic parent.
