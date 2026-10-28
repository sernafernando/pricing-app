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
5. Advisor detail: TOP board (our rank vs N, positions). Suggested price / promo apply still TBD.

---

## Product decisions (agreed)

| ID | Decision | Why | Status |
|----|----------|-----|--------|
| D1 | Work unit = **MLA** (sync pairs), not EAN→Sheet | Pricing-native; promotions apply per publication | Done (cola) |
| D2 | Shell = Advisor + Criterios, same MLA queue | Operator switches view without losing selection | Done |
| D3 | Scope filters = “which MLAs are showable”, not criteria | Same mental model as Productos filters | Done (partial) |
| D4 | System defaults: markup **5–15%**, TOP **5**, prices unset, flags off | Sensible floor until PM/product inheritance | Done |
| D5 | Criteria layers: system → (future product/PM) → MLA override | Inheritance without forcing every MLA | MLA + default done; product/PM TBD |
| D6 | Seller dispositions on catalog roster | **Activo / Excluido** only — excluded = out of ranking, stays on list + discreet notice | Done (simplified) |
| D7 | Faceted `alcance-opciones`: each facet skips **only itself**; tipo↔lista both apply | Cascading options; mutual tipo/lista need each other | Done |
| D8 | Tienda filter via `ml_tiendas_oficiales` + `tb_mercadolibre_items_publicados`; “Sin tienda” = no row | Named stores need seed in empty sandbox | Done (+ seeds) |
| D9 | **Cost USD from–to** = scope filter (not criteria) | Different cost bands need different criteria later | Done (`costo_usd_min` / `costo_usd_max`; ARS→USD via TC venta) |
| D10 | **Mass / system criteria = markup only** (no mass price caps) | No single cost → price caps as mass criteria are meaningless | Done (defaults + `MASS_CRITERIA_NUMBER_KEYS`; mass apply UI still disabled) |
| D11 | **Per MLA:** precio ↔ markup stay in sync (edit either; other derives via Pricing calc) | Same chain as Productos: `POST /precios/calcular-por-markup` (`adicional_markup: 0`) and `GET /precios/calcular-markup` with cola `item_id` + `pricelist_id` | Done (debounced UI sync) |
| D12 | **TOP N = price positions** (ties share a rank), not “N sellers” | Two at #1 + three at #2 = top **2** positions, five sellers | Done (GET `/criterios/{mla}/sugerencia` + Advisor board) |
| D13 | **Cola default = solo catálogo** (`catalog_listing`); opt-in “Incluir tradicionales sincronizadas” | Operators want catalog winners first; sync partners clutter the queue | Done (`incluir_tradicionales_sincronizadas`) |
| D14 | **TOP same_bucket = listing_type \| cuotas**; bare int installments normalize correctly; synthesize our bucket from web pricelist when snapshot omits it | Bare ints used to collapse to `\|0` → “estamos solos” on 6 cuotas while ML shows peers | Done (read-time recompute) |
| D15 | **Precio sugerido** = referent peer in same bucket (cheapest; skip peers with markup &lt; `markup_min` when known); clamp to precio min/max if set. Delta: losing ⇒ sugerido−ours; winning ⇒ air to next peer | Pro algorithm; first Advisor slice without promo apply | Done (compute + UI; apply TBD) |
| D16 | **Criterio aplicado** = fila en `para_ganar_criterios_mla` (defaults o custom). Sin fila = sin aplicado. Cola badge + filtro Sin/Con + `POST …/aplicar-defaults` | PM assignment UX; “defaults en pantalla” ≠ asignado hasta persistir | Done |
| D17 | **Masivo pisa todo el alcance filtrado** (con y sin fila). Cola tint + `POST /criterios/aplicar-masivo` (markup/TOP/flags; precio caps intactos). Modal Tesla en Criterios | Overwrite explícito; D10 mass keys | Done |
| D18 | **Pool promos Advisor:** prefer SMART-like `candidate`; else DEAL/SELLER_CAMPAIGN cuyo rango cubra `precio_sugerido`. `GET /promociones/item/{mla}` (`promos.ver`). Aplicar gris (enroll después) | “Premium” ≠ tipo ML; bridge = rango vs sugerido | Show done; enroll TBD |

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
- **Solo catálogo (default):** cola and facets require `ml_publication_links.catalog_listing = true`. Check **Incluir tradicionales sincronizadas** to also show traditional listings that share a `catalog_product_id` (D13).

### Criterios

- **Sin criterio aplicado (D16):** no row in `para_ganar_criterios_mla`. UI still shows system defaults for editing (`Origen: default`), but the queue badge says **Sin criterio aplicado**. Filter chips: Todos / Sin / Con.
- **Con criterio aplicado:** a saved row exists (defaults via **Aplicar defaults**, or custom via **Guardar**). Badge **Con criterio aplicado**; `Origen: MLA`. Queue row uses `cf-bg-card` tint (D17); sin aplicado stays transparent.
- System defaults are **markup + TOP + flags** only — no mass price caps (D10). Precio min/max ↔ markup min/max sync via Pricing endpoints (D11).
- Mass “Aplicar criterios al filtro” (D17): modal → `POST /para-ganar/criterios/aplicar-masivo` with the same scope query as the cola. **Overwrites every MLA in scope** (markup/TOP/flags). Existing `precio_min`/`precio_max` are left alone; new rows get caps unset.

### TOP (posiciones)

- Field label: **TOP posiciones de precio**. Empates comparten puesto (D12).
- Advisor: `GET /para-ganar/criterios/{mla}/sugerencia` ranks competition `price_ars` (dense rank) **only in the same bucket** as this MLA (`listing_type` + cuotas); excluded sellers omitted; ourselves always counted. Snapshot must be for **this MLA** (a clásica sibling of the same catalog is not reused).
- Bucket key is recomputed at read time from competitor `installments` (int/str/dict). If the snapshot lacks `our_bucket_key`, it is synthesized from this MLA’s web pricelist (e.g. lista 14 → `gold_pro|6`) so 6-cuotas peers are not dropped (D14).
- TOP board shows **Competís en** + per-row `listing_label` from the competition API (e.g. `Premium · 3 cuotas`) so it is not confused with the website financing copy (“Mismo precio en 6 cuotas”).
- If the bucket has fewer price positions than TOP N, a discreet notice says the TOP is incomplete (not enough competitors).
- **Precio sugerido (D15):** cheapest same-bucket peer as referent; if `markup_min` is set and peer markups exist, skip peers below that floor. Caps `precio_min`/`precio_max` when set. **Perdiendo:** delta = sugerido − nuestro (negativo = bajar). **Ganando:** holgura hasta el siguiente peer.
- **Pool promos (D18):** under the TOP board, list candidates from `GET /promociones/item/{mla}`. Prefer SMART / PRE_NEGOTIATED / PRICE_MATCHING; else DEAL / SELLER_CAMPAIGN whose `[min,max]` covers `precio_sugerido`. **Aplicar** is disabled until enroll is wired (same `POST /promociones/item/{mla}` as Productos).
- Missing snapshot: `POST /para-ganar/criterios/{mla}/competencia/refresh` (permiso `productos.editar_precios`) fetches via the same `refrescar_competencia_catalogo` path as Promociones — **per MLA only** (ML throttle).

### Sellers del catálogo

- Sync pulls members from latest competition snapshot.
- Dispositions: **Activo** | **Excluido**. Excluido = fuera del ranking (como si no existiera), sigue en la lista; aviso discreto si hay alguno.

---

## Backlog (ordered for this week)

1. Keep this doc updated on every slice (this file is the source of truth).
2. ~~Fix CI css-guard~~ (`filterGroupActive`).
3. ~~Scope: costo USD desde–hasta~~ (D9).
4. ~~D10–D11 criteria markup/price~~ (mass keys + per-MLA sync).
5. ~~Suggestion/TOP engine (rank board D12 + Activo/Excluido)~~.
6. ~~Cola solo catálogo + check tradicionales (D13); fix bucket 6 cuotas (D14)~~.
7. ~~Precio sugerido D15 (referent + delta; no promo apply)~~.
8. ~~Criterio aplicado D16 (badge + filtro + Aplicar defaults)~~.
9. ~~Mass criteria apply to filtered scope (D17)~~.
10. ~~Show promo pool (D18; apply greyed)~~.
11. Wire enroll from Advisor (reuse Productos `POST /promociones/item/{mla}`).
12. Later: product/PM inheritance; suggestion states queue.

---

## Out of scope (for now)

- Literal port of the Chrome extension / Sheet export loop.
- Scraping ML pages as primary data path.
- Merging Draft PR #1796 until product says so.
}
