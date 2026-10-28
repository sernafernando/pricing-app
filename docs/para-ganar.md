# PARA GANAR — living decisions & manual seed

Single place for **what we built**, **why we decided it**, and the seed of the **operator manual**.  
Extension archaeology (what Pro does today): [`para-ganar-pro-source-map.md`](./para-ganar-pro-source-map.md).

**Branch / PR:** `feat/promo-local-refresh-mirror` → Draft PR #1796 (CI only; no merge).  
**Worktree:** `main-local-snapshot`. Login sandbox: `localadmin` / `localdev123`.

---

## Quick path (what works today)

1. Open `/para-ganar` (permiso `productos.ver`). Tabs: **Advisor** | **Criterios**.
2. Filter the MLA queue with scope chips (tipo, lista, tienda, marca, subcategoría, PM, EAN/código, MLA catálogo). Facets cascade.
3. Select an MLA → **Criterios**: edit override (or see system defaults). Save persists per MLA.
4. **Catalog sellers** (on Criterios): roster from competition snapshot; dispositions active / ignore / hide / exclude_from_top.
5. Advisor detail is still a shell (suggestion engine TBD).

---

## Product decisions (agreed)

| ID | Decision | Why | Status |
|----|----------|-----|--------|
| D1 | Work unit = **MLA** (sync pairs), not EAN→Sheet | Pricing-native; promotions apply per publication | Done (cola) |
| D2 | Shell = Advisor + Criterios, same MLA queue | Operator switches view without losing selection | Done |
| D3 | Scope filters = “which MLAs are showable”, not criteria | Same mental model as Productos filters | Done (partial) |
| D4 | System defaults: markup **5–15%**, TOP **5**, prices unset, flags off | Sensible floor until PM/product inheritance | Done |
| D5 | Criteria layers: system → (future product/PM) → MLA override | Inheritance without forcing every MLA | MLA + default done; product/PM TBD |
| D6 | Seller dispositions on catalog roster | Ignore/hide/exclude without deleting competition data | Done (API + UI) |
| D7 | Faceted `alcance-opciones`: each facet skips **only itself**; tipo↔lista both apply | Cascading options; mutual tipo/lista need each other | Done |
| D8 | Tienda filter via `ml_tiendas_oficiales` + `tb_mercadolibre_items_publicados`; “Sin tienda” = no row | Named stores need seed in empty sandbox | Done (+ seeds) |
| D9 | **Cost USD from–to** = scope filter (not criteria) | Different cost bands need different criteria later | Done (`costo_usd_min` / `costo_usd_max`; ARS→USD via TC venta) |
| D10 | **Mass / system criteria = markup only** (no mass price caps) | No single cost → price caps as mass criteria are meaningless | Done (defaults + `MASS_CRITERIA_NUMBER_KEYS`; mass apply UI still disabled) |
| D11 | **Per MLA:** precio ↔ markup stay in sync (edit either; other derives from that MLA’s cost in ARS) | Deterministic floor: `precio = costo_ars * (1 + markup/100)` — not limpio/comisiones | Done (UI sync + `costo_ars` on GET/PUT) |
| D12 | **TOP N = price positions** (ties share a rank), not “N sellers” | Two at #1 + three at #2 = top **2** positions, five sellers | Label done; engine when TOP logic lands |

---

## Commit trail (this branch, PARA GANAR)

Newest first. Use for “why did we…” archaeology.

| Commit | What |
|--------|------|
| `73874d257` | Sticky “Limpiar” footer in scope dropdowns |
| `325855701` | Clear (X) chip on active multi-selects |
| `c7088413b` | Mutual cascade tipo ↔ lista facets |
| `945e4fc8d` | Seed publicados store links (sandbox) |
| `6e4710396` | Cascade all scope facets + seed official stores |
| `449853158` | Scope filters: tipo, lista, tienda, EAN, catálogo |
| `054583633` | Catalog seller roster + dispositions |
| `b8898cb7d` | System criteria defaults (5–15%, TOP 5) |
| `c47611cae` / `ff0388873` | Per-MLA criteria persist (+ migration rechain) |
| `a42b25d7a` | Sticky detail panel, viewport-capped |
| `03bc15230` | Marca / subcat / PM scope filters |
| `d8bcf2299` | Advisor \| Criterios subviews |
| `6750a277e` | Sandbox MLA queue in advisor |
| `96683afe2` | Empty `/para-ganar` shell |
| `63add4360` | Source map from extension Pro |

---

## Operator notes (manual seed — expand as features ship)

### Alcance (filters)

- Filters restrict the **cola**; they are not saved as criteria.
- Multi-select: open → check options → optional **X** on the chip or **Limpiar** at the bottom of the list.
- Facets refresh from other active filters (e.g. marca narrows EAN options).
- **Costo USD desde/hasta:** ERP `productos_erp.costo` normalized to USD (`moneda_costo=USD` as-is; ARS ÷ tipo de cambio venta). Rows without a convertible cost drop out of the band.

### Criterios

- **Sin override MLA:** UI shows system defaults (`Origen: default`). System defaults are **markup + TOP + flags** only — no mass price caps (D10).
- **Con override:** `Origen: MLA` after save. Precio min/max ↔ markup min/max sync using ERP cost in ARS (D11).
- Mass “apply to filtered” button: still disabled until product/PM layers; when built, only `MASS_CRITERIA_NUMBER_KEYS` + flags.

### TOP (posiciones)

- Field label: **TOP posiciones de precio**. Empates comparten puesto (D12). Suggestion engine must use rank-by-price, not headcount.

### Sellers del catálogo

- Sync pulls members from latest competition snapshot.
- Dispositions: active | ignore_participant | hide | exclude_from_top.

---

## Backlog (ordered for this week)

1. Keep this doc updated on every slice (this file is the source of truth).
2. ~~Fix CI css-guard~~ (`filterGroupActive`).
3. ~~Scope: costo USD desde–hasta~~ (D9).
4. ~~D10–D11 criteria markup/price~~ (mass keys + per-MLA sync).
5. Suggestion/TOP engine: enforce D12 rank-by-price (ties share position).
6. Later: product/PM criteria inheritance; suggestion states; apply via promotions.

---

## Out of scope (for now)

- Literal port of the Chrome extension / Sheet export loop.
- Scraping ML pages as primary data path.
- Merging Draft PR #1796 until product says so.
}
