# Gestión Full — envío workflow: decided vs open

Document for product lock-in before building close → Excel → assign `inbound_id` → reconcile.

Related research: [`inbound-creation-research.md`](./inbound-creation-research.md).

---

## Quick answer: what does “en Full” mean?

**Having Código ML (`inventory_id`) does *not* mean “en Full”.**

Evidence (Metabase + smoke Excel + API, 2026-10-30/31):

| SKU / case | Código ML (`inventory_id`) | Stock Full API | Reading |
|------------|----------------------------|----------------|---------|
| Extensor TP-Link (XZXU40135) | yes | ~357 aptas | Operatively **en Full** |
| Cartucho HP 667 (NPAN61264) | **yes** (`NPAN61264` in `ml_items`) | **0** | Had Código ML while treated as “sin Full” in smoke — Excel still works |
| Pure MLAU only (no Código ML) | no | n/a | **Cannot** use the official Full Excel (SC rejects); out of this filter universe |

### D1 — decided (Gabe, 2026-10-31)

**Fuera de Full** (both must hold; nulls count as 0):

```text
COALESCE(stock_full, 0) = 0
AND COALESCE(ventas_full_30d, 0) = 0
```

**En Full** = not fuera:

```text
COALESCE(stock_full, 0) > 0
OR COALESCE(ventas_full_30d, 0) > 0
```

Rationale: not only on-hand Full stock — a SKU that sold in Full in the last 30 days stays **en Full** even at 0 stock (sold out / awaiting replenish). Only cold SKUs (no stock **and** no Full sales 30d) are **fuera**.

| Example | stock_full | ventas Full 30d | Filter |
|---------|------------|-----------------|--------|
| XZXU with stock | 357 | >0 or 0 | en Full |
| Sold out but selling | 0 | >0 | en Full |
| NPAN-like cold | 0 | 0 | fuera de Full |
| Has Código ML only | 0 | 0 | fuera de Full |

**Listing universe:** still rows with `inventory_id IS NOT NULL` (Código ML). Filter en/fuera applies inside that set. No-Código-ML stays out of Gestión export (see D10).

---

## Decided (locked from research + this thread)

### API / ML reality

| # | Decision |
|---|----------|
| R1 | Public MLA API does **not** create Full inbounds — Seller Center (+ Excel upload) only. |
| R2 | Official Excel template must be filled (SKU + Código ML + # publicación digits + qty). Invented workbooks fail. |
| R3 | Draft / open SC envío (e.g. `81061502`) is **not** readable via public GET; no shipment dossier API. |
| R4 | After warehouse reception, ops expose `INBOUND_RECEPTION` rows with `external_references.inbound_id`. |
| R5 | Received qty for an envío/SKU = **Σ `detail.available_quantity`** filtered by that `inbound_id` (+ `inventory_id`). Sales do not mix into that `detail`. |
| R6 | SC “Procesamiento finalizado / declaradas / procesadas / diferencias” is **not** available via API. Pricing can only approximate diffs with local declared + R5. |
| R7 | Completion is **inferred** (no more events for that `inbound_id` for a dwell window). No official closed status on the inbound resource. |
| R8 | `available + not_available == enviado` is **not** a completion signal. |
| R9 | ML may split one uploaded workbook into several SC envíos (small/medium vs large/extra-large). Pricing will not predict size class; user assigns N `inbound_id`s after SC creates them. |
| R10 | `ml_fulfillment_last_inbound` stays **Target** (newest reception qty per SKU). Do **not** overload it as outbound plan / multi-inbound reconcile store. |

### Product workflow (agreed direction)

| # | Decision |
|---|----------|
| P1 | One **general** Excel with all chosen lines (not pre-split by size). |
| P2 | After SC returns envío number(s), Pricing stores `inbound_id` on line subsets (assign UI). |
| P3 | **Roles split:** PM decides/overrides and **closes their part** → lines lock for that PM. **Gestor Full** unlocks PM if needed, prepares Excel / closes the Full package (not PMs). |
| P4 | Shipments consultation as a **tab** inside Gestión Full (declared vs received). |
| P5 | Gestión list filters **en Full** vs **fuera de Full** per D1; default open = **en Full**. Universe = rows with Código ML (needed for ML Excel). |
| P5b | **Row key** = **producto ERP + MLAU** (`producto_item_id` + `user_product_id`), not ERP + `inventory_id`. Código ML remains a column (export). Override / ready / package lines key off that pair (or MLAU if 1:1 with inventory in practice). |
| P5c | **Stock ERP filter:** by default show only rows with `stock_erp > 0`. Checkbox in filters “mostrar sin stock” **default off**. Independent of en/fuera Full. |
| P5d | **Second Excel** (ops/depósito): EAN + descripción + cantidad (`qty_export`). In addition to official ML Full Excel. Same package / gestor gates. |
| P6 | Column **Unidades por caja cerrada** on Gestión list (read from master data). |
| P7 | **Depósito tab** inside Gestión Full to maintain unidades/caja (bulk Sheet import + ongoing manual). |
| P8 | Gestor Full **cannot** close/export the Full envío package until every included line has `unidades_por_caja` loaded. |
| P9 | Cap send qty: `min(override ?? sugerido, stock_erp)` — never ship more than Stock ERP. |
| P10 | First bulk of unidades/caja already exists in a Sheet → one-shot import into Pricing table, then UI for gaps. |

### Roles (working model)

| Actor | Does |
|-------|------|
| **PM** | Sets override / leaves Sugerido; marks product decision ready (scope marca/categoría). |
| **Gestor Full** | Builds Excel, assigns `inbound_id`s, closes send package; may need to adjust qty at export time (see D11). |
| **Depósito** | Maintains **unidades por caja cerrada** (import + panel). |

### Reuse as-is

| Piece | Role |
|-------|------|
| `GET /gestion-full` listing | Planning grid (override, Target, Sugerido, stocks, ventas) |
| `gestion_full_override` | Live PM qty intent (pre-freeze) |
| `ml_fulfillment_last_inbound` + weekend drip | Target only |
| Official xlsx under `docs/design/gestion-full/samples/` | Export bake/fill source |
| `stock_erp` on listing | Candidate for physical stock cap (P9) |
| Webhook `/api/ml/render` | Ops probe path; Pricing will use its own ML token like other workers |

---

## Open — need your definition

Answer each id (or “defer”). Defaults in italics are proposals only until you confirm.

### D1 — Meaning of filter “en Full” / “fuera de Full” — **DECIDED**

See Quick answer.

**D1b — default on open — DECIDED:** filter **en Full** (not todos / fuera).

**D1c — stock ERP visibility — DECIDED (Gabe 2026-10-31):** default **hide** `stock_erp = 0` (and null). Optional filter checkbox “mostrar sin stock”, default **unchecked**. Orthogonal to D1 en/fuera Full.

**D1d — list row identity — DECIDED:** natural key **ERP + MLAU** (`producto_item_id` + `user_product_id`). Today’s listing uses ERP + `inventory_id` — migrate. `inventory_id` stays displayed/exported (ML Excel col C). Target join remains via `inventory_id` on the row.

**D1e — dual Excel — DECIDED:** (1) official ML Full template; (2) simple workbook EAN / descripción / cantidad for depósito.

### D2 — Who can close vs who can export — **DECIDED (reopen)**

| Step | Actor |
|------|-------|
| Mark lines ready (“cerrar su parte”) | PM (marca/categoría scope) |
| After PM close | **Lock:** PM **cannot** edit those lines anymore |
| Re-enable PM edit | **Gestor Full only** (unlock / devolver al PM) |
| Maintain unidades/caja | Depósito |
| Export Excel / close Full package | Gestor Full |
| Assign inbound_id | Gestor Full |

Perm key names still open under D9.

### D3 — Freeze / export / hard lock lifecycle — **DECIDED** (Gabe 2026-10-31)

| Phase | What happens |
|-------|----------------|
| **1. PM cierra su parte** | Se decide y congela `qty_pm` = `override ?? sugerido` (con tope stock físico). PM queda locked (D2). |
| **2. Gestor revisa pre-Excel** | Puede setear `qty_export` (override del override/sugerido congelado). Motivo optativo (D11b). Documentado **antes** de armar el Excel. Requiere unidades/caja (P8). |
| **3. Export Excel** | Gestor exports (PMs need not all be closed). `qty_export` defaults from PM/`sugerido`. Regenerate only after clearing any assigned `inbound_id`s. |
| **4. Asignar `inbound_id`s (post-SC)** | After upload, ML splits into envíos; Gestor fills slots and assigns lines (D5). |
| **5. Hard lock** | When **every** exported line has `inbound_id`. Partial ≠ locked. After full assign, package immutable; later PM edits apply to **next week**. |

**D3b — DECIDED:** lock is **all-or-nothing** on the exported package (full assignment of inbound ids), not per-line progressive lock.

**D3c — DECIDED:** all of this lives as **tabs inside Gestión Full** (no separate top-level pages for depósito caja, assign inbound, or envíos consult). Incl. depósito **unidades por caja**.

### D11 — Override editable after PM ready, but traceable? **DECIDED: A**

Keep `qty_pm` (frozen at PM ready). Gestor edits `qty_export` (defaults to capped `qty_pm`). Excel uses `qty_export`. UI shows both + “ajustado por gestor”. Audit on `qty_export`. Cap vs stock físico still applies.

**D11b — DECIDED:** reason on gestor `qty_export` adjust is **optional** (field exists, not required).

### D12 — Grain of “unidades por caja” + “stock físico”

**D12a — DECIDED:** unidades por caja keyed by **producto ERP** (`producto_item_id`). Same caja for all `inventory_id` rows of that product.

**D12b — DECIDED:** send cap uses listing **`stock_erp`** (`min(qty, stock_erp)`).

### D13 — Depósito: cola de prioridad U/caja (anti-lock export) — **DECIDED (backlog)**

Today the Depósito tab is a flat ERP catalog (`full_mode=todos`, no pending queue). That does not surface what will block P8 export.

**D13 — DECIDED (Gabe 2026-10-31):** Depósito should prioritize products **missing `unidades_por_caja`** that are already on the **current week’s active package** (`open`/`exported`, lines with `qty_export ≥ 1`) and/or **PM-ready**, so Gestor is not blocked at Excel time. Full catalog / search remains available via a **Todos** mode; **Pendientes** is the default. API: `GET /gestion-full/unidades-caja/pendientes`.

### D4 — Plan naming / granularity — **DECIDED** (human ids)

- No free-text SC-style titles (`FULL_OCTUBRE_…`) required.
- Group by **week**. Human id for each ML envío after assign:

```text
{YYYYMMDD}_{inbound_id}
```

where `YYYYMMDD` = **Monday** of the week of the **gestor definitive close** (all lines have `inbound_id`).

- Working package **before** assign still needs an internal id (DB); display can show week Monday until inbounds exist.

**D4b — DECIDED:** Until inbound numbers are assigned, PMs work on a **single shared listado** (one open planning surface / package). Multiple envíos in the same week appear **only after** SC split + `inbound_id` assignment (`{lunes}_{inbound_id}` each). Not multiple parallel PM packages.

### D5 — Assign `inbound_id` UX — **DECIDED**

Tab in Gestión Full. **Manual assign** (no auto-import match of SC table required for v1):

1. Gestor enters the `inbound_id`s ML returned into slots (fields **A / B / C…** or equivalent).  
2. Alternatively: ingest inbound ids in one step → UI builds **assign buttons** for each entered id.  
3. Multi-select `inventory_id` rows from the exported package → assign to one filled slot / button.  
4. Filters: **todos / asignado / sin asignar**.

**D5b — DECIDED (v1 assumption):** **1 línea → 1 inbound**. Same `inventory_id` split across two envíos should not happen; out of scope until it appears in production.

### D6 — Excel export / regenerate — **DECIDED**

| Rule | Detail |
|------|--------|
| Default `qty_export` | Equals PM decision (`override ?? sugerido`, capped by stock). All export fields pre-populated; **only** changes when Gestor edits `qty_export`. |
| First export gate | Gestor can export **without** every PM having closed their part. Still needs unidades/caja on included lines (P8). |
| Regenerate | Allowed only if **no** `inbound_id`s assigned on the package. If any exist, Gestor must **clear them** before regenerate. |
| After export + **all** lines have `inbound_id` | Package hard-locked (D3). If a PM later edits qty (on unlocked / next-cycle lines), that change is for **next week** — does not mutate the locked package. |

### D7 — Shipments tab — **DECIDED** (minimal)

- **List** of local envíos (`inbound_id`, human id `{lunes}_{inbound_id}`) — not full ML history.
- **Detail** drill-down per envío: lines with declared vs received (and diff).
- No extra chrome required for v1 (optional later: status chip, SC deep-link). Keep list → detalle.

### D8 — Reconcile worker — **DECIDED**

| Knob | Value |
|------|-------|
| Poll interval | **every 3 hours** for open (not locally closed) `inbound_id`s |
| Local “recepción cerrada” | **3 days** with **no new** `INBOUND_RECEPTION` for that `inbound_id` |

Rationale: Target/stock Full still come from live stock + Target drip — a premature local close only hurts **envío detail** (declared vs received), not operational Full stock. Acceptable risk if ML is slow.

**D8b — DECIDED:** **Persist** each seen `INBOUND_RECEPTION` credit (inbound_id, inventory_id, operation_id, qty delta, occurred_at) in our DB. Poll upserts new ops; received sum reads locally.

### D9 — Permissions — **DECIDED**

| Permiso | Quién / qué |
|---------|-------------|
| Ver Gestión / pestañas | Existing view: `productos.ver` **or** `ml_ops.ver` |
| Override + ready check (PM) | Existing marca/categoría scope (same as today’s override) |
| `gestion_full.gestor` | Export Excel, edit `qty_export`, unlock PM lines, assign `inbound_id`, hard-lock flow |
| `gestion_full.depositos` | Tab unidades por caja (import + edit) |

Tabs without the matching write perm stay read-only / hidden actions as appropriate.

### D10 — “Alta a Full” / ready check — **DECIDED**

- **Ready check** = PM finished deciding qty (“ya decidí cuánto mandar”). **Not** related to Código ML.
- **Alta operativa** into the send package = qty decided + ready check (for rows the PM can see in the listado).
- **Código ML** is a separate listing/Excel constraint: rows without `inventory_id` are not in Gestión / cannot use official Excel. Unrelated to what the check means.
- Cold **fuera de Full** rows (with Código ML): PM can filter fuera/todos, set qty, check → included.

---



## Build gap (once opens are closed)

| Area | New work |
|------|----------|
| Tables | `unidades_por_caja` master (+ import); plan + plan lines; shipments; **inbound ops history** (D8b). Not Target table. |
| APIs | listing + filter; caja CRUD/import; PM ready; gestor export/close; assign inbound; list/detail envíos; qty_export adjust + audit |
| Workers | Reconcile poller for open inbound ids; one-shot Sheet→DB import (script or admin) |
| UI | Single `/gestion-full` with tabs: listado, unidades/caja, export/assign, envíos |
| Docs | Ayuda + novedad when UI ships |

## Effort estimate (2026-10-31)

Baseline already shipped (listado + override + Target drip): **~1.5k LOC** (app+tests).

**New work for the decided workflow** — authored lines (code + tests + migrations + CSS + ayuda), mid estimates:

| Slice | What | LOC mid | PRs @ ≤400 |
|-------|------|---------|------------|
| S1 | Filter en/fuera + stock ERP checkbox + key ERP+MLAU + col caja + cap | 450 | 1–2 |
| S2 | Tabla + tab depósito caja + import Sheet | 700 | 2 |
| S3 | Perms + ready check + PM lock / gestor unlock | 550 | 2 |
| S4 | Package/lines + `qty_pm` / `qty_export` + audit | 750 | 2 |
| S5 | Excel ML + Excel EAN/desc/qty | 500 | 1–2 |
| S6 | Tab assign inbound (slots/botones + multi-select) | 750 | 2 |
| S7 | Tab envíos + worker 3h + persist ops + cierre 3d | 950 | 3 |
| S8 | Shell tabs + wiring + polish | 250 | 1 |
| | **Total mid** | **~4.9k** | **~14–15** |
| | Band (pessimistic / optimistic) | **4.0k – 6.0k** | **12 – 16** |

Scope creep check: yes — this is ~**3×** the size of what Gestión Full is today, and it’s a small replenishment workflow product (plan → Excel → assign → reconcile), not “one more column”.

**Delivery (Gabe 2026-10-31):** build the **full** scheme; do **not** gut features. Use **stacked PRs to `main`** (Pricing change model), each ≤ ~400 authored lines. Mid estimate remains **~14 PRs** (band 10–16).

### Proposed stack order (dependencies)

| PR# | Slice | Depends on | Notes |
|-----|-------|------------|-------|
| 1 | S1a filter en/fuera + default + stock_erp checkbox | — | listing query params |
| 2 | S1b row key ERP+MLAU + col caja read + cap `stock_erp` | 1 | migrate override key; needs caja stub |
| 3–4 | S2 caja table + depósito tab + import | 2 | may split model/API vs UI/import |
| 5–6 | S3 perms + ready check + PM lock/unlock | 1 | can parallel after 1 if careful |
| 7–8 | S4 package/lines + qty_pm/qty_export + audit | 5–6 | core state machine |
| 9 | S5 Excel export (ML + EAN/desc/qty) | 7–8 + caja | bake official xlsx + simple ops xlsx |
| 10–11 | S6 assign inbound tab | 9 | slots/buttons; hard-lock when complete |
| 12–14 | S7 envíos list/detail + ops table + worker 3h/3d | 10–11 | reconcile |
| (+1) | S8 tabs shell / ayuda / polish | as needed | may absorb into last slices |

Re-estimate after S4 (state model): if slices run heavy, expect **15–16**; if lean, **12–13**. **~14 remains the planning number.**

---

## Checklist for Gabe

- [x] D1 en/fuera Full definition (`stock>0 OR ventas_30d>0` / both 0)
- [x] D1b default filter on open = **en Full**
- [x] D1c default hide `stock_erp=0`; checkbox “mostrar sin stock” off
- [x] D1d row key **ERP + MLAU** (not ERP + inventory_id)
- [x] D1e dual Excel: ML official + EAN/desc/qty
- [x] P6–P10 unidades/caja, panel depósito, cap vs stock físico, gestor cierra Excel
- [x] D2 PM lock on close; only Gestor unlocks PM again
- [x] D9 perms: view existing; PM scope; `gestion_full.gestor`; `gestion_full.depositos`
- [x] D3 lifecycle: PM freeze `qty_pm` → gestor `qty_export` → export (re-export OK) → hard lock when **all** lines have inbound_id
- [x] D3b all-or-nothing lock (partial assign ≠ locked)
- [x] D3c shell: **all tabs inside Gestión Full**
- [x] D11 = **A** (`qty_pm` + `qty_export` + audit)
- [x] D11b reason on gestor adjust = **optional**
- [x] D12a unidades/caja por **producto ERP**
- [x] D12b stock físico = **`stock_erp`**
- [x] D4 human id = `{YYYYMMDD_monday}_{inbound_id}` at definitive close; no SC-style name
- [x] D4b one shared PM listado until inbound assign; N envíos only after ids
- [x] D5 slots A/B/C or buttons from entered inbound_ids + multi-select assign
- [x] D5b 1:1 inventory→inbound (no split qty in v1)
- [x] D6 qty_export default; export sin todos los PM closed; regen limpia inbounds; post-lock → próxima semana
- [x] D7 listado inbound_ids + detalle (declarado vs recibido); minimal v1
- [x] D8 poll 3h; close recepción after 3d sin cambios
- [x] D8b persist recepción ops in DB
- [x] D10 ready check = “ya decidí qty”; alta = qty + check; Código ML aparte

---

## Log

- **2026-10-31** — Drafted from Excel/API research + workflow asks (close, single Excel, assign inbound, envíos view, Full filter). Clarified NPAN61264: has Código ML with stock Full 0 → “sin Full” ≠ missing `inventory_id`.
- **2026-10-31** — D1 locked: **fuera** = `stock_full=0 AND ventas_full_30d=0`; **en Full** = otherwise (stock or recent Full sales). Nulls as 0.
- **2026-10-31** — D1b: default filter on open = **en Full**.
- **2026-10-31** — P6–P10: columna + panel depósito **unidades por caja**; gate cierre/export gestor; cap qty ≤ stock físico; roles PM vs Gestor Full vs Depósito.
- **2026-10-31** — D11 = A (`qty_pm` + `qty_export`). Walking remaining opens one-by-one with Gabe.
- **2026-10-31** — D11b: motivo de ajuste gestor **optativo**.
- **2026-10-31** — D2: PM lock al cerrar su parte; solo Gestor Full rehabilita edición al PM.
- **2026-10-31** — D3: qty_pm al cierre PM; qty_export pre-Excel; re-export solo gestor; hard lock when **all** inbound_ids assigned (ML splits at once). Partial ≠ locked.
- **2026-10-31** — D3c: todo en pestañas de Gestión Full (incl. depósito caja).
- **2026-10-31** — D4: id humano `{lunesYYYYMMDD}_{inbound_id}`; sin nombre SC.
- **2026-10-31** — D4b: listado PM único hasta asignar inbound; varios envíos recién con los nros.
- **2026-10-31** — D5: cargar inbound_ids en slots/botones; multi-select inventory → asignar.
- **2026-10-31** — D5b: 1:1; split qty deferred.
- **2026-10-31** — D6: qty_export default=PM/sugerido; export sin esperar todos los PM; regen requiere borrar inbounds; hard lock → edits PM a próxima semana.
- **2026-10-31** — D7: lista de inbound_ids + detalle; sin extras obligatorios en v1.
- **2026-10-31** — D8: poll 3h; cierre local recepción tras 3d sin eventos (stock Full no depende de esto).
- **2026-10-31** — D8b: persistir créditos INBOUND_RECEPTION en DB.
- **2026-10-31** — D12a: unidades/caja por producto ERP.
- **2026-10-31** — D12b: tope = `stock_erp`.
- **2026-10-31** — D10: ready check = “ya decidí cuánto mandar” (no es Código ML); alta = qty + check.
- **2026-10-31** — D9: perms locked (`gestion_full.gestor`, `gestion_full.depositos`).
- **2026-10-31** — Decision pass complete for v1 workflow opens (checklist all checked).
- **2026-10-31** — D1c/D1d/D1e: default solo `stock_erp>0` (+ checkbox sin stock); row key **ERP+MLAU**; segundo Excel EAN/desc/cantidad.
- **2026-10-31** — D13: Depósito prioriza faltantes U/caja en **paquete de la semana** y/o **ready** (anti-lock export); shipped as follow-up PR on tip #1982.
