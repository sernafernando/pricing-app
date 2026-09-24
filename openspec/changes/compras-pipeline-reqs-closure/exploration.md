# Exploration: compras-pipeline-reqs-closure

Close remaining Gabe operator gaps 15+17, 6, 16, 9, 7/12, 3, 19 after `compras-ops-pipeline-ux` (archived) and without amending `compras-pipeline-chicho-review-fixes`. English technical artifact. No production code.

Baseline locks (do not reopen / do not regress) — cumulative product law:
- DONE reqs: 1, 2, 4, 5, 8, 10, 11, 13, 14, 18, 20 (and shipped pipeline behaviors).
- Chicho law: constancia ≠ cargada; no alert on Match/persist; `cargada` check → 5m pending then alert; uncheck cancels; chip Factura = cargada; permiso `administracion.ver_alertas_factura`; two distinct 5m windows; UNIQUE factura rows.
- All landed branch changes above are assumed correct; this change only closes residual gaps.

---

## Current State

Financial `estado` and derived `eje_procesal` already exist. `calcular_eje_procesal` maps `con_faltantes` + null `faltantes_resuelto_en` → `faltantes_sin_res`, stamp set → `faltantes_con_res`. Pedidos list shows those ejes as “Faltantes” / “Faltantes resueltos”. Depósito tabs still filter **financial** `estado` only.

`POST /pedidos/{id}/faltantes/resolver` exists (`recepcion_service.resolver_faltantes`). It stamps `faltantes_resuelto_en`, emits `faltantes_resuelto`, fans out G31 `compras.faltantes_resuelto` to `deposito.recibir_mercaderia`. It does **not** require `texto`, does **not** retract `compras.faltantes`, and G31 copy is `"Faltantes resueltos en {P} ({proveedor})."` with no PM instructions. Schema: `ResolverFaltantesRequest.texto: str | None`. Permission: `administracion.gestionar_ordenes_compra` **or** `deposito.recibir_mercaderia`. **No FE caller** (`useRecepcionDeposito` has no resolver; `ModalPedidoDetalle` observaciones are read-only).

`AppLayout` treats all `compras.*` banners as dismissible. OK → `PATCH /notificaciones/{id}/ok` → `marcar_ok` → `DESCARTADA`. A PM can clear `compras.faltantes` without resolving. Spec text (“until resolved or OK rules apply”) left this ambiguous; Gabe #15 is not.

Depósito “Con faltantes” sends `estado=con_faltantes`, so **sin_res and con_res share the tab**. After a stamp, the row stays `estado=con_faltantes` and remains in that queue.

### Gap table (current vs desired)

| ID | Current | Desired |
|----|---------|---------|
| **#15+#17** | Resolver BE exists, texto optional, no retract, G31 omits texto, FE never calls it, banner OK dismisses `compras.faltantes`, Depósito “Con faltantes” = all `con_faltantes`, Pedidos eje label “Faltantes resueltos” | PM writes required observación → stamp + eje **Faltantes con resolución**; `compras.faltantes` dismisses **only** on that transition; Depósito “Con faltantes” = `faltantes_sin_res` only; FE `POST …/faltantes/resolver` with required `texto`; G31 includes that texto; depósito then executes and may mark `controlado` |
| **#6** | Depósito header badge is financial `estado` only (`badgeControlado` etc.). `factura_cargada` is already on `PedidoCompraResponse` but unused here | When factura is ERP-cargada, show a badge in the same visual family as Controlado |
| **#16** | SIN-OC optional `observaciones` only on the faltantes path. CON-OC control sends qty + `faltantes_texto`, no obs. Photo never attached on control (Docs = generic `AdjuntosPanel`) | After control (including **control OK**), allow optional observación **and** photo. Photo missing today |
| **#9** | BE `tipo` ∈ {mercaderia, servicio}, default mercaderia, admin-only post-create. FE create/edit (`ModalPedidoCompra`) **does not send `tipo`**. Depósito Por recibir does not exclude servicio; arrival/control already 409 servicio | FE mercadería/servicio selector on create (admin edit after). Exclude `tipo=servicio` from Depósito Por recibir |
| **#7/#12** | `identChips` is **SIN-OC only** and only `numero_factura`. CON-OC header shows items badge + `OC #{oc_poh_id}` | Show factura number **and** Admins-OC `pedidos_documento` on **all** Depósito rows, including CON-OC |
| **#3 PARTIAL** | Pedidos OC chip = `oc_vinculada` (header `oc_poh_id` or `ocs[]`). Depósito already says “OC no encontrada en ERP” per block | Decide: extra “exists in GBP” chip vs keep vinculación chip + doc note |
| **#19 PARTIAL** | Single “OC” chip. DTO already has `ocs: [{oc_comp_id, oc_bra_id, oc_poh_id}]` | Optional per-OC label on Pedidos list when N>1 |

---

## Affected Areas

- `backend/app/services/recepcion_service.py` — require nonempty `texto`; retract `compras.faltantes`
- `backend/app/schemas/recepcion.py` — `ResolverFaltantesRequest.texto` required
- `backend/app/services/compras_alertas_service.py` — G31 copy includes `texto`; `retractar_faltantes`; `marcar_ok` rejects / no-ops `compras.faltantes`
- `backend/app/api/endpoints/notificaciones.py` — OK path for `compras.faltantes` → 409
- `backend/app/routers/administracion_compras.py` — resolver perms; `listar_pedidos` eje / `faltantes_resuelto` filter; deposito list excludes servicio
- `backend/app/services/pedidos_service.py` — SQL/helper for `eje_procesal` filter (already has mapper)
- `frontend/src/components/AppLayout.jsx` — `compras.faltantes` not dismissible; Ver/snooze only
- `frontend/src/components/compras/ModalPedidoDetalle.jsx` — resolver UI (required texto) when `eje_procesal=faltantes_sin_res`
- `frontend/src/hooks/useRecepcionDeposito.js` — `resolverFaltantes`
- `frontend/src/components/compras/TabRecepcionDeposito.jsx` — tab queries; Cargada badge; factura + `pedidos_documento` chips on CON-OC; obs+photo on control OK
- `frontend/src/components/compras/TabPedidosCompra.jsx` — eje label “Faltantes con resolución”; optional multi-OC labels
- `frontend/src/components/compras/ModalPedidoCompra.jsx` — tipo selector
- `frontend/src/components/compras/AdjuntosPanel.jsx` — reuse inline on control (`tipo='otro'`)
- Tests: `test_compras_alertas_service.py`, recepcion unit/integration, `TabRecepcionDeposito.test.jsx`, `ModalPedidoDetalle.test.jsx`, `AppLayout.comprasBanners.test.jsx`, `TabPedidosCompra.test.jsx`
- Docs: `docs/modulos/compras-guia-usuario.md` (#3 chip meaning, #15/#17 flow)
- Specs to delta later: `compras-pipeline-alerts`, `recepcion-estados`, `recepcion-deposito`, `pedidos-compra`

Do **not** amend `openspec/changes/compras-pipeline-chicho-review-fixes/`.

---

## Approaches

### A. #15+#17 Faltantes closure (HARD)

1. **Complete the existing resolver (recommended)** — Keep financial `estado=con_faltantes`. PM resolution = stamp + required `texto`. Retract `compras.faltantes` by `item_id=pedido.id`. G31 copy appends `texto`. Banner OK on `compras.faltantes` → HTTP 409 (FE hides dismiss). Con faltantes tab queries `eje_procesal=faltantes_sin_res`. Recibidos queries `eje_procesal=recibido,faltantes_con_res` so depósito can execute after G31. Relabel eje to “Faltantes con resolución”. Restrict resolver to responsable **or** `administracion.gestionar_ordenes_compra` (drop depósito from writers).
   - Pros: Reuses stamp, eje, G31, events; no new estado; matches Gabe sin→con_res
   - Cons: Depósito Recibidos meaning grows (includes “ready to finish after PM instructions”)
   - Effort: Medium

2. **New financial estado `faltantes_con_res`** — Rewrite `estado` on resolve.
   - Pros: Tab filter stays `estado=`
   - Cons: Breaks transitions, events, `_ESTADOS_VISIBLES_DEPOSITO`, chicho/archive specs; high risk
   - Effort: High — **reject**

3. **FE-only hide + honor OK** — Client-filter con_res; keep banner OK.
   - Pros: Tiny
   - Cons: Misses Gabe #15; pagination/totals lie; no G31 texto; no FE resolver
   - Effort: Low — **reject**

**Default (not blocking):** After resolve, con_res lives on **Recibidos** (awaiting depósito execution). G31 deep-link → `/administracion/compras?tab=deposito&pedido={id}` (today G31 has no deep-link; `compras.faltantes` goes to Pedidos + `focus=observaciones`). Snooze stays. `compras.faltantes_resuelto` and factura keep per-user OK.

### B. #6 Cargada badge in Depósito

1. **Reuse Controlado badge tone + “Factura cargada” label when `factura_cargada` (recommended)** — List DTO already has the flag (chicho ERP-check). No BE.
   - Effort: Low

2. **New chip style** — Extra CSS; more drift from “similar to Controlado”.
   - Effort: Low — worse fit

### C. #16 Obs + photo on control

1. **Reuse adjuntos `tipo='otro'` + optional `observaciones` on both CON-OC ingresos and SIN-OC control-OK (recommended)** — Archive design already: “Photo = adjuntos tipo='otro'”. JPG/PNG/WebP already allowed. Inline `AdjuntosPanel` (or a thin photo file input that POSTs the same endpoint) on the control action bar, including completo=true. CON-OC `registrarIngresos` already accepts `observaciones`; FE just never sends it on OK.
   - Pros: No new storage; Docs panel already lists them
   - Cons: Photo is not a dedicated `tipo=foto` unless we add a check constraint value (avoid this change)
   - Effort: Medium (FE) / Low (BE if any)

2. **New `tipo=foto` + binary on recepcion payload** — Multipart control endpoints.
   - Cons: New constraint, two upload paths
   - Effort: High — **reject**

### D. #9 Tipo selector + exclude servicio

1. **Create selector + list exclude (recommended)** — `ModalPedidoCompra` sends `tipo` (default mercaderia). Admin-only PATCH in detalle (BE already). Depósito Por recibir: BE `tipo != servicio` when listing warehouse tabs **or** FE skip + BE `tipo` query. Prefer BE `tipo` query used by Depósito (`tipo=mercaderia`) so servicio never pages in.
   - Effort: Low–Medium

2. **BE-only default, no FE selector** — Operators cannot set servicio.
   - Cons: Fails Gabe #9
   - Effort: Low — **reject as sole fix**

### E. #7/#12 Factura + `pedidos_documento` on CON-OC

1. **Extend `identChips` to all rows; add `pedidos_documento` (recommended)** — Today chips are skipped when `oc_poh_id != null` (items badge wins). Show items badge **and** ident chips. Factura display: `numero_factura` or first token of `facturas_documento` (both already on list DTO). Admins-OC number = `pedidos_documento` (write-once Text). Clipboard should include both.
   - Effort: Low

2. **Join typed `factura_documentos` numeros on list** — More accurate multi-factura; extra payload.
   - Cons: list already has text fields; chicho owns typed rows
   - Effort: Medium — defer unless tokens diverge in QA

### F. #3 OC chip vs GBP exists

1. **Keep chip = vinculación; document GBP as Depósito block copy (recommended)** — `oc_vinculada` is relation/header. “OC no encontrada en ERP” already covers missing GBP header. A second Pedidos chip would duplicate that and confuse “linked vs found”.
   - Effort: Docs only

2. **Independent “en GBP” chip** — Needs ERP existence batch on Pedidos list (N+1 or new batch).
   - Effort: Medium — **not needed** to close #3

### G. #19 Per-OC labels on Pedidos

1. **Optional compact labels from `ocs[]` (recommended)** — Keep “OC” chip; if `ocs.length > 1`, append `#{poh}` list (same `#` convention as Depósito). Single-OC stays chip-only.
   - Effort: Low

2. **Always list every OC** — Noisier on wide tables.
   - Effort: Low

---

## Recommendation

Ship **one change** with **chained PRs**, completing the resolver/eje model already in archive design (do not invent a new estado).

**Locked defaults (propose these; not blocking questions):**

1. **#15+#17 = Approach A1.** Required `texto`; retract `compras.faltantes` on resolve only; G31 includes `texto`; no banner OK on `compras.faltantes`; Con faltantes = `faltantes_sin_res`; Recibidos includes `faltantes_con_res`; eje label “Faltantes con resolución”; resolver writers = responsable or `gestionar_ordenes_compra`; G31 deep-link to Depósito.
2. **#6 = B1.** Cargada badge beside estado, Controlado-like tone, only if `factura_cargada` (not mere numbers).
3. **#16 = C1.** Optional obs on CON-OC and control-OK; photo via existing adjuntos `otro`.
4. **#9 = D1.** FE tipo on create; Depósito lists `tipo=mercaderia`.
5. **#7/#12 = E1.** Ident chips on CON-OC + `pedidos_documento`.
6. **#3 = F1.** Chip stays vinculación; guide note for GBP-missing.
7. **#19 = G1.** Compact multi-OC labels; single chip when N=1.

Do not touch chicho factura-cargada timer/alert model.

---

## Suggested PR split / size

Review budget 400 authored lines. Forecast: **chained PRs, High budget risk if landed as one PR.**

| Slice | Scope | Approx. risk |
|-------|--------|----------------|
| **PR1 BE 15+17** | Required texto, retract, G31 copy, OK 409, eje filter on `listar_pedidos`, resolver perms, tests | Medium–High |
| **PR2 FE 15+17** | Detalle resolver form, hook, AppLayout no-dismiss, Depósito tab params, eje label, G31 deep-link, tests | Medium |
| **PR3 Depósito ID** | #6 badge + #7/#12 chips/clipboard (+ #3 guide sentence) | Low |
| **PR4 Control evidence** | #16 obs + photo on CON-OC and control-OK | Medium |
| **PR5 Tipo + OC labels** | #9 selector/exclude + #19 labels | Low–Medium |

Do not start apply as a single PR. PR1 is the dependency for PR2. PR3–5 can follow PR2 or stack in parallel after PR1 if needed.

---

## Risks

- **Alert OK behavior change:** PMs who today dismiss `compras.faltantes` with OK will see a persistent banner until they resolve with texto. Campanita OK must 409 the same way or banners return on reload.
- **Eje vs estado filtering:** Client-only hide of con_res leaves them stuck on `estado=con_faltantes` with no Depósito home. Recibidos **must** include `faltantes_con_res` or G31-only findability (too easy to miss). Pagination needs a **BE** eje filter, not a post-fetch splice.
- **Photo storage via adjuntos:** Reuse `compras_adjuntos` (`tipo='otro'`, existing MIME/size). Do not add `tipo=foto` or recepcion multipart. Docs panel will show control photos — intended. Persist adjunto **before** control POST so a failed control does not orphan silently (or accept orphan + operator delete; prefer upload-then-control).
- **Resolver permission:** If depósito keeps resolver access, they can stamp without PM instructions and retract the PM alert — recreates the dilution of #15.
- **Chicho overlap:** `factura_cargada` flag is the #6 input. Do not change cargada semantics.
- **CON-OC header density:** Adding factura + `pedidos_documento` chips next to items badge can wrap; truncate like observaciones (60ch + title).

---

## Open questions

None blocking. Defaults above are enough to propose.

Non-blocking (already defaulted): Recibidos as con_res home; no GBP chip; no `tipo=foto`; compact multi-OC labels.

---

## Ready for Proposal

**Yes.** Orchestrator should run `sdd-propose` for `compras-pipeline-reqs-closure` with the locked defaults above. Do not amend chicho. Next artifact: `proposal.md` (then specs for alerts / recepcion-estados / recepcion-deposito / pedidos-compra).
