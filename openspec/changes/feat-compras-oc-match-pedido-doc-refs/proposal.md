# Proposal: Persist OC-match document numbers on PedidoCompra

## Intent

OC Match extracts `nro_documento` / `nro_pedido` but never writes them to `PedidoCompra`. Operators need supplier invoice/PO numbers. `numero_factura` stays ERP-only. Persist tokens into two Text fields via Gemini `tipo_documento`.

## Scope

### In Scope
- Alembic: `facturas_documento`, `pedidos_documento` Text NULL on `pedidos_compra`; hang off `compras_041_oc_match_progress_phase` (rehang if tip moved). No index.
- Extract `tipo_documento` (`factura|pedido|proforma|nota_venta|comprobante_pago|otro`); keep `nro_documento` / `nro_pedido`; pass through match.
- Write-back helper + worker: append-only unique tokens; join `; `; `SELECT FOR UPDATE`; never wipe; never touch `numero_factura`.
- Routing: `factura` → `nro_documento` → Factura/s; `nro_pedido` if present → Pedido/s. `pedido|proforma|nota_venta` → both → Pedido/s. `comprobante_pago|otro|unknown` → no write-back; MIME enqueue unchanged.
- Write when extract produced routeable numbers, including `RechazoExcel` `error`. Skip if extract never ran.
- API: create/update/response; both `CAMPOS_EDITABLES_*`; `/corregir` inherit (not financial). Operator PUT may replace the string (only wipe). Match `observaciones`.
- Minimal FE (labels **Factura/s**, **Pedido/s**): `ModalPedidoCompra`, `ModalPedidoDetalle`, `ModalCorregirPedido`.
- Branch from `upstream/main`; single PR to `main`.

### Out of Scope
- `numero_factura` / `match_forward`; TabPedidos list; TabRecepcionDeposito chip; adjunto `tipo` CHECK; job extract-JSON; enqueue MIME; CSS redesign; AI-vs-operator flag.

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `compras-oc-match-pipeline`: extract `tipo_documento`; append-only PedidoCompra write-back; one acta `Tipo documento:` line.
- `pedidos-compra`: two Text columns; editable like `observaciones`; `/corregir` inherit; minimal pedido-form FE.

## Approach

Worker writes columns directly (not `editar_pedido`) so AI skips `EDITADO` / `match_forward`. Dedupe case-insensitive; keep first-seen casing. Aliases: `nv` → `nota_venta`; `recibo` → `comprobante_pago`. Null/unknown → `otro`. Each eligible PDF appends.

## Affected Areas

Modified: `pedido_compra.py` model/schemas; `pedidos_service.py`; `oc_match/{extract,match,acta,worker}.py`; pedido + worker tests; three pedido modals. New: `compras_042_…` off `compras_041_…`.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Gemini lumps proforma into `nro_documento` | Med | Enum + skip `otro`/unknown |
| Concurrent jobs race | Med | `SELECT FOR UPDATE` |
| Operator PUT / clone drop tokens | Med | Human override; inherit both columns |
| Wrong Alembic head forks compras | High | Hang off `compras_041_…`; re-check heads |
| 400-line budget Medium | Med | FE = existing `numero_factura` inputs |

## Rollback Plan

Downgrade Alembic (drop two columns). Revert extract/match/acta/worker, pedido schemas/edit/clone, and the three modal fields. `numero_factura` and enqueue untouched.

## Dependencies

- Parent `feat-compras-oc-match`. PR #1312 is not the base.

## Success Criteria

- [ ] `factura` writes `nro_documento` to Factura/s and `nro_pedido` to Pedido/s; never `numero_factura`.
- [ ] `pedido|proforma|nota_venta` write both numbers to Pedido/s only; `comprobante_pago|otro` enqueue with no write-back.
- [ ] Append-only `; ` unique tokens; duplicate job is no-op; excel-error-with-extract still writes.
- [ ] Operator PUT edits both fields like `observaciones`; `/corregir` inherits; no list columns.
