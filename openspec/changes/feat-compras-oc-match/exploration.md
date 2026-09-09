# Exploration: feat-compras-oc-match

Port the Gauss Automations OC (proforma → match → Excel) pipeline into Pricing Compras. Product decisions below are **locked** and are not reopened here.

## Locked product decisions

- Port the Automations OC pipeline **into Pricing**. No Coolify external app for this path. Chicho: "move everything into Pricing".
- Trigger: **on pedido adjunto upload** (any `tipo`); do **not** trigger on pedido create alone.
- MIME gate: enqueue only PDF / JPG / JPEG / PNG / WEBP; otherwise skipped/error **without Gemini**.
- Source of truth for results: **Pricing DB**.
- UI: new Compras tab (Cheques pattern) — poll job status, show renglones + acta, download Excel.
- Mail to Belén: **OFF** for this path. Coolify mail Automations stays until this ships, then Gabe shuts it down.
- Sync: poll (`BackgroundTasks` + job table; **no Celery** in repo).
- Excel storage: local disk like `COMPRAS_UPLOADS_DIR`.
- Maestro: prefer `tb_item` (+ brand/cat joins); EAN = `item_code`; `productos_erp` is a filtered subset — adapter from Automations `matching/maestro.py`.
- Empresa map: `empresas.id` 1 Pastoriza → `"PASTORIZA"`; id 2 Grupo Gauss → `"GRUPO GAUSS"` (normalize from `pedido.empresa_id`).
- Gemini: 3 API keys rotation in Pricing `.env` (Chicho loads vars Gabe provides).
- Port core: `extractor/`, `matching/`, `excel/`, `host/acta.py`. Deprecate mail / Sheet / Coolify API for this path.

---

### Current State

**Pricing Compras today has no OC-match pipeline.** Pedido create is JSON-only (header amount, no SKU lines). The PDF/image arrives later via `AdjuntosPanel` in `ModalPedidoDetalle` (`POST /administracion/compras/pedidos/{id}/adjuntos`). That upload is the real trigger.

| Surface | Behavior today |
|---|---|
| `ModalPedidoCompra.jsx` | Alta/edición JSON. No file. Fields: empresa, proveedor, moneda, monto, TC, fechas, factura, observaciones. |
| `AdjuntosPanel.jsx` | Drag-drop after the pedido exists. Accepts PDF/JPG/PNG/WebP **and** DOC(X)/XLS(X). Sequential multipart POST. Used from pedido / OP / NC detalle. |
| `AdministracionCompras.jsx` `TABS` | Pedidos, OPs, NCs, CC, Reconciliación, Catálogo SD, Depósito, **Cheques**, Papelera. Each tab has its own `tienePermiso()`. Cheques is the newest list-tab pattern (hook + CSS Module + Tesla), **not** a poller. |
| `compras_adjuntos_service.py` | Magic-bytes whitelist (PDF/JPEG/PNG/WebP + Office ZIP/OLE2). Writes `{COMPRAS_UPLOADS_DIR}/{entidad}/{id}/{uuid}_{name}`. Flush only; router commits. **No post-commit hook.** |
| `PedidoCompra` | Header-only (`monto` único). No renglones SKU. OCR was historically out of scope (`modulo-compras` v2). |
| Jobs | No Celery. Closest async patterns: `BackgroundTasks` in tickets triage and proveedores ERP sync (202 + SSE). Locked decision for this path is **poll + job table**, not SSE. |
| Gemini | **Not in Pricing.** `requirements.txt` has `openpyxl==3.1.2`; no `google-genai`. |
| Maestro | `tb_item` (`item_code`, `item_desc`, `brand_id`, `cat_id`, `subcat_id`) + `tb_brand` / `tb_category` / `tb_subcategory`. `productos_erp` is a **filtered** sync (`prli_id=4`, skip cats 1/67/72, stor ≠ 17). Locked: do not use `productos_erp` as maestro. |
| Empresas | Seed `empresas.id` 1=`Pastoriza`, 2=`Grupo Gauss` (`20260406_empresas.py`). ERP map already exists (`compras_empresa_erp_map.py`) but maps to `(comp_id, bra_id)`, not Automations sucursal strings. |

**Automations today (read-only `/home/user/proyectos/gauss-automations`):** mail → Sheet/Drive cola → `host/procesar_cola.py::procesar_job`:

1. Download adjunto
2. `extractor.extract_proforma.extract_one` (Gemini JSON)
3. `matching.match_proforma.match_renglones` (fabricante exact → Gemini among candidates)
4. `excel.generar_carga_masiva.generar` (GBP carga-masiva xlsx; ARS only; USD needs TC)
5. `host.acta.acta_cierre` + **mail** (deprecate mail for Pricing path)

`extractor/gemini_pool.py` already rotates `GEMINI_API_KEY` / `_2` / `_3` and retries 429/503. MIME map: `.pdf/.jpg/.jpeg/.png/.webp`. Maestro Excel snapshot (~4300 SKUs) includes **Código del Proveedor / Fabricante**, which Pricing `tb_item` **does not store**.

---

### Affected Areas

- `backend/app/routers/administracion_compras.py` — hook after `subir_adjunto_pedido` commit; new job/list/detail/download endpoints.
- `backend/app/services/compras_adjuntos_service.py` — MIME classification for enqueue vs skip (do not reject Office uploads; they stay as adjuntos).
- `backend/app/core/config.py` — `GEMINI_API_KEY{,_2,_3}`, `GEMINI_MODEL`, Excel dir (sibling of `COMPRAS_UPLOADS_DIR`).
- `backend/app/models/` + Alembic — new job + renglones tables (Pricing DB is SoT).
- New services (port, not vendor the Coolify host): extractor, gemini pool, matching + `tb_item` adapter, excel, acta.
- `frontend/src/pages/AdministracionCompras.jsx` — new `TABS` entry (Cheques pattern).
- New `frontend/src/components/compras/TabOcMatch.*` + hook — poll status, renglones, acta, Excel download.
- `backend/requirements.txt` — add `google-genai` (new dep).
- **Do not** change Automations Coolify / mail until Gabe cutover after ship.
- **Do not** trigger from OP/NC adjunto endpoints (locked: pedido only).

---

### Approaches

1. **In-process port into Pricing (locked)** — copy/adapt `extractor/`, `matching/`, `excel/`, `acta.py` as Pricing services. Enqueue from pedido adjunto upload via `BackgroundTasks` + persist job/renglones/acta/excel path in Pricing DB.
   - Pros: one app, one auth, one DB, Belén works in Compras; matches Chicho; Coolify/mail can die after ship.
   - Cons: new Gemini dep; worker-death risk (no Celery); matching adapter must replace Excel maestro; ~400-line PR budget will be exceeded (plan chained slices in tasks).
   - Effort: **High**

2. **Coolify sidecar HTTP** — Pricing uploads, then calls Automations `/host` API and mirrors status.
   - Pros: less Python to port.
   - Cons: **rejected** — "move everything into Pricing"; extra deploy, tokens, Sheet/Drive still in the path.
   - Effort: Medium (wrong product)

3. **Keep mail Automations + Pricing UI mirror** — Belén still gets mail; Pricing only displays.
   - Pros: zero Gemini in Pricing.
   - Cons: **rejected** — mail OFF for this path; SoT must be Pricing DB; dual systems until cutover already accepted only as temporary Coolify stay.
   - Effort: Low (wrong product)

---

### Recommendation

**Approach 1 — in-process port.** Product is locked. Implementation shape:

```
AdjuntosPanel POST pedido adjunto
  → commit compras_adjuntos
  → MIME gate (magic + suffix)
      reject-for-pipeline (Office / unknown): job status skipped|error, no Gemini
      PDF/image: INSERT job pendiente + BackgroundTasks.add_task(run_oc_match, job_id)
  → worker (own DB session): extract → match(tb_item adapter) → excel disk → persist renglones + acta
  → Tab OC Match polls GET job until excel_listo|error|skipped
```

**Recommended MVP phases** (Belén can operate in Pricing before Coolify shutdown):

| Phase | Scope | Done when |
|---|---|---|
| **0 Foundations** | Alembic job + renglones; settings keys; empresa sucursal map; Excel dir; MIME helper | Migration + unit tests for map/MIME; no Gemini calls |
| **1 Trigger** | Hook only on `subir_adjunto_pedido` after commit; enqueue; skip Office without Gemini | Upload PDF → job row; upload XLSX → skipped/error, no Gemini; create pedido → no job |
| **2 Pipeline** | Port extractor + gemini_pool + matching adapter + excel + acta; persist SoT | One golden PDF → renglones + acta + xlsx on disk |
| **3 Tab UI** | Cheques-style tab: list/poll, renglones, acta, download Excel | Operator sees status without mail |
| **4 Cutover (ops)** | Gabe shuts Coolify mail Automations | Dual-run ends; not a code phase |

Do **not** port: `host/api.py`, `host/cliente_cola.py`, Gmail, Drive, Sheet, Playwright GBP import, mail notify.

**Maestro adapter (locked direction, gap noted):**

- Load `Articulo`-shaped rows from `tb_item` ⨝ `tb_brand` ⨝ `tb_category` ⨝ `tb_subcategory`.
- `Articulo.ean` = `tb_item.item_code`; `item_id` = `str(tb_item.item_id)`; keep `sin_combos_internos`.
- `productos_erp` is wrong (price-list 4 + category/depot filters drop purchasable SKUs).
- **Gap:** Automations exact-fabricante match needs "Código del Proveedor / Fabricante". That column is **not** on `tb_item`. Propose must pick a fallback (see Open Questions). Do not silently drop rule 1.

**Empresa:** new small map (do not overload `compras_empresa_erp_map.py`): `{1: "PASTORIZA", 2: "GRUPO GAUSS"}` from `pedido.empresa_id`. Names in `empresas.nombre` are title-case; Automations body required ALL CAPS.

**Cheques UI pattern:** add a `TABS` item with its own permission, component, hook, CSS Module (CF tokens). Polling is **new** (Cheques does not poll). Reuse list + badge + empty-state habits from `TabCheques`; poll `GET` job while `pendiente|en_curso`.

---

### Risks

- **Worker death:** `BackgroundTasks` dies with the uvicorn worker. Jobs can stick in `en_curso`. Need stale-timeout / reclaim in propose-design (no Celery).
- **Fabricante code missing** on `tb_item` → more Gemini, worse exact-SKU hits (packs/colors). Highest matching-quality risk.
- **New dep `google-genai`** + 3 secrets. Keys must not be logged. Chicho loads Gabe's vars.
- **Quota / 503:** pool rotation exists in Automations; port it. Long PDFs can run minutes — never run Gemini inside the upload request.
- **MIME split:** adjuntos still accept Office; pipeline must skip, not 400 the upload.
- **N files = N jobs** on one pedido (panel allows 10). Concurrency vs Gemini quota.
- **USD without TC:** Automations `RechazoExcel` — persist as job error + acta, no silent empty xlsx.
- **Dual-run window:** Coolify mail stays until ship. Pricing mail is OFF, so Belén may see Coolify mail + Pricing tab until Gabe cuts over. Document; do not send a second mail.
- **400-line review budget:** full port + tab will exceed it. Tasks must forecast chained PRs (foundations/trigger → pipeline → UI).
- **Excel template binary:** Automations uses a GBP carga-masiva xlsx. Copying the template into Pricing vs generating columns is a propose choice.
- **No `openspec/config.yaml`** in this worktree; change folder is the store of record.

---

### Open Questions

Product path is locked. Remaining questions for **propose** (do not block explore):

1. **Fabricante code:** sync a GBP field onto `tb_item` / sidecar table in this change, or degrade to description+EAN matching until a later sync? (Quality vs scope.)
2. **Tab permission:** reuse `administracion.ver_ordenes_compra` / `gestionar_ordenes_compra`, or add `compras.oc_match`?
3. **Idempotency:** one job per `adjunto_id` (re-upload replaces) vs enqueue every upload?
4. **Stuck `en_curso`:** timeout + retry vs mark error? Who can requeue?
5. **Excel template:** vendor the Automations xlsx into the Pricing repo, or rebuild headers in code?
6. **Job visibility:** all pedidos vs only those with an OC-match job? Default filters?

---

### Ready for Proposal

**Yes.** Locked decisions are enough to write proposal + specs. Propose should fix the six open questions (especially fabricante and permission), then design the job schema and chained-PR slices.

Reference (read-only): `/home/user/proyectos/gauss-automations` — `extractor/extract_proforma.py`, `extractor/gemini_pool.py`, `matching/maestro.py`, `matching/match_proforma.py`, `matching/candidatos.py`, `excel/generar_carga_masiva.py`, `host/acta.py`, `host/procesar_cola.py` (`procesar_job` only).
