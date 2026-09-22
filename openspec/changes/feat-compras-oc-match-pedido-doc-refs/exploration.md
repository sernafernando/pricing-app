# Exploration: feat-compras-oc-match-pedido-doc-refs

After OC Match extract/match on a **pedido adjunto**, persist documentary numbers on `PedidoCompra` into two new operator-editable Text fields (labels **Factura/s** and **Pedido/s**). Add Gemini `tipo_documento` so each number is routed correctly. Do **not** write `numero_factura` (ERP matching). Heavy list UX stays in a later compras-ux change.

New branch from `upstream/main`: `feat/compras-oc-match-pedido-doc-refs`. Current workspace tip `feat/compras-oc-match-renglones-ean` (PR #1312, FE-only) is **not** the base.

---

## Exploration: Persist OC-match document numbers on PedidoCompra

### Current State

**Pedido header.** `pedidos_compra` already has:

| Column | Role |
|---|---|
| `numero` | Internal Pricing correlative (`P-01-2026-00001`). Unique. **Not** a supplier document. |
| `numero_factura` | `String(50)`, optional. Triggers `erp_matching_service.match_forward` on edit. Partial index `(proveedor_id, numero_factura)`. Operator label today: “Número de factura (opcional)” / “N° Factura”. |
| `observaciones` | `Text`, metadata. Same edit matrix as `numero_factura` (borrador + aprobado/pagado_parcial/pagado). |

There is **no** column for supplier pedido / proforma / NV numbers.

**Edit rules.** `pedidos_service.CAMPOS_EDITABLES_BORRADOR` and `CAMPOS_EDITABLES_APROBADO` whitelist fields. Unknown keys with non-null values → HTTP 409. `editar_pedido` ignores `None` (cannot clear via null today). Cosmetic `/corregir` clone copies `numero_factura` and `observaciones`; those names are also in `CorreccionPedidoRequest`.

**Extract today** (`oc_match/extract.py` PROMPT):

- `nro_documento` — mixed: factura **or** proforma **or** NV. No type discriminator.
- `nro_pedido` — supplier order number when printed (`PED-…`, Solution Box `1379491/01`). Distinct from `nro_documento`. If the paper **is** only a pedido, that number goes here.

`match.py` copies both into the matched dict. `acta.py` prints them; Excel filename slugs `nro_pedido` or `nro_documento`. **Neither is written to `pedidos_compra`.** `OcMatchJob` does not store extract header JSON.

**Worker persist.** `_persist` updates job status + renglones only. `_claim_and_load` already `db.get(PedidoCompra, job.pedido_id)` but the persist session never mutates the pedido. Failed extract → empty `matched` `{}`. `RechazoExcel` still has extract/match numbers in `matched` while job status is `error`.

**Enqueue.** MIME-only (`pdf/jpg/jpeg/png/webp` → queued). Original OC-match lock: trigger on **any** adjunto `tipo`. `CompraAdjunto.tipo` CHECK is `'factura' | 'presupuesto' | 'comprobante' | 'otro'` (nullable). There is **no** `comprobante_pago` string in the repo. `AdjuntosPanel` only **displays** `tipo`; upload hint is optional. Payment-receipt PDFs that are Gemini-eligible **already enqueue** and run extract/match/excel.

**Frontend numero_factura pattern.**

- `ModalPedidoCompra.jsx` — optional text input; included in create + metadata-only PUT.
- `ModalCorregirPedido.jsx` — cosmetic clone field.
- `ModalPedidoDetalle.jsx` — read-only “N° Factura” plus ERP “Factura del ERP” block (`ct_transaction_id`).
- `TabRecepcionDeposito.jsx` — chip from `numero_factura` (ERP/recepcion, **out of scope**).
- Pedidos **list** does not show `numero_factura` (compras-ux later).

**Alembic on `upstream/main`.** Compras line tip is `compras_041_oc_match_progress_phase` (revises `compras_040_oc_match`). `upstream/main` has **multiple Alembic heads** (ML/TN/tickets leftover branches). New migration MUST hang off `compras_041_oc_match_progress_phase` (same pattern as 041: rehang if the compras line advanced). Do not merge unrelated heads in this change. Precedent for nullable Text metadata: `compras_026_pedido_observaciones`.

### Affected Areas

- `backend/app/models/pedido_compra.py` — two nullable `Text` columns.
- `backend/alembic/versions/` — `compras_042_…` (or next) adding the columns; `down_revision = compras_041_oc_match_progress_phase`.
- `backend/app/schemas/pedido_compra.py` — `PedidoCompraBase`, `PedidoCompraUpdate`, `CorreccionPedidoRequest`.
- `backend/app/services/pedidos_service.py` — both `CAMPOS_EDITABLES_*`; clone constructor + `cambios_persistidos` whitelist (cosmetic, not `CAMPOS_FINANCIEROS_CORRECCION`).
- `backend/app/services/oc_match/extract.py` — add `tipo_documento` to JSON schema + prompt rules.
- `backend/app/services/oc_match/match.py` — pass `tipo_documento` through.
- `backend/app/services/oc_match/acta.py` — optional one-line `Tipo documento:` (cheap; not required for write-back).
- `backend/app/services/oc_match/worker.py` — after successful extract numbers exist, append-only write-back on `PedidoCompra` in the persist session (`SELECT FOR UPDATE`).
- `backend/tests/unit/test_pedidos_service.py`, `test_pedidos_corregir.py` — editable + clone inherit.
- `backend/tests/integration/test_oc_match_worker.py` — `GOLDEN_EXTRACT` + assert pedido columns.
- `frontend/src/components/compras/ModalPedidoCompra.jsx` (+ CSS if needed) — Factura/s and Pedido/s inputs.
- `frontend/src/components/compras/ModalPedidoDetalle.jsx` — display the two fields (same header pattern as N° Factura).
- `frontend/src/components/compras/ModalCorregirPedido.jsx` — cosmetic fields so a clone can edit them; backend inherit is mandatory even if FE is deferred.

**Out of scope:** `numero_factura` / ERP `match_forward`; TabPedidos list columns; TabRecepcionDeposito chip; adjunto `tipo` CHECK change; job-table extract JSON column; enqueue MIME rules.

### Approaches

#### 1. Column names

1. **`facturas_documento` / `pedidos_documento` (recommended)** — snake_case, documental, no collision with `numero` or `numero_factura`.
   - Pros: Gabe’s example; greppable; FE labels stay Spanish (“Factura/s”, “Pedido/s”).
   - Cons: slightly long.
   - Effort: Low

2. **`numeros_factura` / `numeros_pedido`** — closer to operator language.
   - Pros: short.
   - Cons: easy to confuse with `numero_factura` (ERP) and `numero` (internal).
   - Effort: Low

3. **Reuse / widen `numero_factura`** — **rejected** (Gabe locked). ERP matching + `String(50)` + `match_forward` side effect.

#### 2. `tipo_documento` enum (extract JSON)

Closed snake_case set. Prompt MUST force one of these; worker lowercases/strips and maps aliases.

| Value | Paper | Write-back |
|---|---|---|
| `factura` | Invoice (FA/FB/FC, 0004-…) | `nro_documento` → Factura/s; `nro_pedido` if present → Pedido/s |
| `pedido` | Supplier order | both numbers → Pedido/s |
| `proforma` | Proforma / quote | both numbers → Pedido/s |
| `nota_venta` | NV / nota de venta | both numbers → Pedido/s |
| `comprobante_pago` | Transfer receipt / constancia | **no write-back** (adjunto stays; job still runs) |
| `otro` | Remito, packing list, unknown commercial paper | **no write-back** (safe out) |

Aliases (worker only, not stored): `nv` / `nota de venta` / `nota_de_venta` → `nota_venta`; `comprobante` / `constancia` / `recibo` / `transferencia` → `comprobante_pago`. Unknown / null → treat as `otro` (skip write-back).

Keep existing `nro_documento` + `nro_pedido`. `tipo_documento` classifies the **paper**; `nro_pedido` remains the cross-ref when a factura cites a supplier PO.

#### 3. Write-back policy (minimal, recommended)

- **Append-only unique tokens.** Never replace, never wipe, never reorder existing tokens.
- Join stored value with **`; `** (semicolon + space). Parse on `;` then strip (tolerate missing space).
- Dedupe: case-insensitive compare after strip; keep first-seen casing (operator text wins over AI if already present).
- Do **not** normalize number formats (`0001-99` ≠ `1-99`).
- Empty / null extract numbers → no-op.
- `comprobante_pago` / `otro` / unknown tipo → no-op even if numbers exist.
- Write when extract produced routeable numbers, **including** job `error` after `RechazoExcel` (identity is independent of Excel). Do **not** write if extract never ran (missing keys, missing file).
- Worker writes columns **directly** (not via `editar_pedido`) so AI does not emit `EDITADO` or call `match_forward`.
- Persist session: `SELECT … FOR UPDATE` on `pedidos_compra.id` to serialize concurrent jobs on the same pedido.
- Multiple PDFs: each eligible done (or excel-error-with-extract) job appends its new tokens.
- No “AI-sourced vs operator-touched” flag (Gabe: prefer minimal).

Operator PUT may send a full replacement string (same as `observaciones`). That is the only wipe path — human, not AI.

#### 4. Enqueue vs skip for `comprobante_pago`

1. **Skip write-back only (recommended)** — leave MIME enqueue unchanged.
   - Pros: cheap; matches Gabe preference; adjunto `tipo` is optional/unreliable (`comprobante` ≠ Gemini `comprobante_pago`); original lock is “any tipo”; payment PDFs still get renglones/acta if they accidentally contain SKUs.
   - Cons: Gemini spend on constancias that will not write pedido fields.
   - Effort: Low

2. **Skip enqueue when `adj.tipo == 'comprobante'`**
   - Pros: saves Gemini.
   - Cons: **not safe** — tipo is operator hint, often null; mis-tagged facturas would never match; does not see Gemini `tipo_documento`.
   - Effort: Low (wrong)

3. **Two-phase: cheap classify then skip** — extra Gemini or heuristic before full extract.
   - Pros: save tokens.
   - Cons: new pipeline; not cheap/safe enough for this PR.
   - Effort: Medium (out of scope)

### Recommendation

**Columns:** `facturas_documento` Text NULL, `pedidos_documento` Text NULL on `pedidos_compra`. No index in this change (list search is compras-ux).

**Extract:** add required-or-null `tipo_documento` enum above; keep `nro_documento` / `nro_pedido`; pass through `match.py`.

**Write-back:** helper in `oc_match` (pure function + worker persist). Append-only unique tokens; FOR UPDATE; never touch `numero_factura`.

**API/FE:** expose on create/update/response; add to both editable frozensets; inherit on `/corregir`. Minimal FE: `ModalPedidoCompra` inputs (labels Factura/s, Pedido/s) + `ModalPedidoDetalle` display. Include `ModalCorregirPedido` if the form already lists `numero_factura` (same pattern). No list columns.

**Enqueue:** do not skip jobs for payment receipts.

**Migration:** `down_revision = compras_041_oc_match_progress_phase`. Re-check `alembic heads` on the new branch.

### Risks

- Gemini still lumps proforma numbers into `nro_documento`; without a well-prompted `tipo_documento`, Factura/s gets polluted. Mitigate with enum + skip-unknown.
- Concurrent jobs on one pedido race without `FOR UPDATE`.
- Operator PUT of the full string can drop AI tokens; document as intentional (human override).
- `editar_pedido` `v is not None` filter: empty-string clear vs null-ignored — match `observaciones` behavior; do not invent a new clear protocol.
- Clone without inheriting the new columns silently drops refs on corrección.
- `upstream/main` multi-head Alembic: hanging off the wrong head forks compras.
- 400-line budget: model + prompt + worker helper + schemas + edit/clone + tests + three FE forms may land **Medium/High**. Gabe locked **single PR**; propose should keep FE to the existing `numero_factura` inputs only (no CSS redesign).
- Payment-receipt jobs still create noisy OC-match rows (accepted).

### Test plan sketch

**Unit (write-back helper):**

- Empty field + `factura` + `nro_documento=A` → `facturas_documento="A"`.
- Existing `"A; B"` + append `A` / `a` → unchanged; append `C` → `"A; B; C"`.
- `proforma` + both numbers → only `pedidos_documento`; Factura/s untouched.
- `factura` + `nro_documento` + `nro_pedido` → both columns.
- `comprobante_pago` / `otro` / null tipo → both columns unchanged.
- Never writes `numero_factura`.

**Worker integration:** extend `GOLDEN_EXTRACT` with `tipo_documento="factura"`; after `process_oc_match_job`, pedido has `0001-99` on Factura/s and `PED-184465` on Pedido/s. Second job with the same numbers is a no-op. Excel `RechazoExcel` still appends numbers.

**Pedidos service:** new fields in `CAMPOS_EDITABLES_APROBADO`; PUT updates them without `match_forward`; clone inherits; financial correccion unchanged.

**FE (Vitest, existing modal tests if any):** form send/receive the two keys; detalle shows joined string or "—".

### Open questions (pending, not blockers)

1. Confirm dual-number routing on `factura` (`nro_pedido` → Pedido/s). Recommended **yes**.
2. Write-back on excel-error-with-extract. Recommended **yes**.
3. Persist `tipo_documento` on acta line. Recommended **yes** (one line); no new job column.
4. `ModalCorregirPedido` in this PR vs inherit-only. Recommended **include** (already has `numero_factura`).

### Ready for Proposal

Yes — product locks plus recommended names/enum/write-back/enqueue are enough to propose. Orchestrator should run **propose** next. Implementation waits for design/tasks; no production code in this phase.
