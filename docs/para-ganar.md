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
| D18 | **Pool promos Advisor:** prefer SMART-like `candidate`; else DEAL/SELLER_CAMPAIGN cuyo rango cubra `precio_sugerido`. `GET /promociones/item/{mla}` (`promos.ver`). Aplicar gris (enroll después) | “Premium” ≠ tipo ML; bridge = rango vs sugerido | Superseded by D19 |
| D19 | **Hasta 3 sugeridas** que entren en criterios: Mejor / Intermedia / Tercera. Orden: SMART → otra DEAL/campaña → Premium (nombre contiene `premium`, ej. PREMIUM JULIO) al final. Markup band + rango vs sugerido | Requester: no inundar con el mirror completo | Superseded by D20 |
| D20 | **Un slot por tipo:** 1 SMART + 1 DEAL/campaña no-Premium + 1 Premium (si califican). Premium ya no lo desplazan N campañas A PVP… Deal price = `precio_sugerido` clamp al rango → con enroll | Requester: Premium visible; brand campaigns no llenan el top-3 | Done (enroll D23) |
| D21 | **Premium `started`:** igual se muestra en el slot Premium con badge/botón **Aplicada** (no solo candidates). Min–max label skip — next slice replaces with sugerido | MLA2154276473: PREMIUM OCTUBRE ya enrolada | Done |
| D22 | TOP board: `referent_note` por seller (Referente / Descartado: markup mín. / Sin markup / precio mín|máx.). Excluidos siguen fuera del ranking | Claridad vs sugerido | Done |
| D23 | Pool: DEAL/campaña muestran `aplicar a $sugerido` (clamp); **Aplicar** → confirmar → `POST /promociones/item/{mla}` (mismo enroll que Productos). SMART manda `precio_visto`. Permiso `promos.escribir`. Sin smoke de activación ML en CI | Cerrar bridge sugerido→promo | Done |
| — | Herencia producto/PM | Cubierto por filtro EAN + masivo | Deprecated |
| — | Heurística campañas de marca | No aporta | Deprecated |
| D24 | Cola Advisor: **Pendiente de revisión** / **Sin novedades** (badge + filtro). No Perdiendo/Ganando en cola. Persistido en `para_ganar_revision_mla`; lo escribe el motor (P5) | Work-queue feeling del Pro | Done (P4 UI/API; P5 Slice A escribe) |

### Periodicidad (roadmap — módulos)

Tercera vista junto a Advisor | Criterios. Lista por **EAN**; inclusiones por MLA sueltos y/o por criterios (lista de precios, tipo de publicación, tienda). Solo lo incluido entra en la **revisión periódica** (trigger → datos de catálogo → evaluación → marca por revisar). Lo no incluido se consulta **a mano** desde Advisor con filtros.

| Módulo | Qué | Depende de | Status |
|--------|-----|------------|--------|
| **P1** | Shell: tab **Periodicidad** (`?vista=periodicidad`) | — | Done |
| **P2** | Modelo + API: suscripción periódica por EAN (alcance: todo el EAN / MLAs elegidos / match lista+tipo+tienda) | P1 | Done |
| **P3** | UI gestión: cola por EAN, abrir detalle, elegir MLAs o reglas de alcance, guardar | P2 | Done |
| **P3.1** | Catálogo filtrado: listar **todos** los EAN del alcance (suscriptos y no), chips Todos/Suscriptos/Sin; MLAs por checkbox desde el mismo filtro | P3 | Done |
| **P3.2** | Criterios Sin/Con filtran EANs (≥1 MLA con criterio); detalle = checkboxes MLA + filtros tipo/lista/tienda; Todo el EAN; sin modo rules en UI | P3.1 | Done |
| **P3.3** | Aviso/filtro **MLA nuevos** (`scope_mode=mlas` con MLA activo fuera de la lista); badge en cola + highlight en detalle | P3.2 | Done |
| **P4** | Estados en Advisor: badge + filtro **Pendiente de revisión** / **Sin novedades** (persistidos; sin Perdiendo/Ganando) | puede ir en paralelo tras P2 | Done |
| **P5** | Motor de evaluación (reusa sugerencia/criterios): ¿hay optimización? → Pendiente; si no → Sin novedades | P2 + P4 | Done (R1–R4) |
| **A1** | Advisor **Consultar filtrados**: misma pipeline que el periódico, pero a demanda sobre el alcance del filtro (manual; lo no suscripto a Periodicidad) | P5 | Done |
| **P6** | Trigger periódico: job que pide/refresca competencia de catálogo solo para inclusiones y dispara P5 | P5 | Planned |
| **P7** | Vista flotante de cola “por revisar” (después; por ahora solo Advisor) | P4+P5 | Later |

**Deprecado (confirmado):** herencia producto/PM; heurística campañas de marca.

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
- Facets refresh from other active filters (e.g. marca narrows available tipos). Selections are **never auto-cleared** when a combo has no rows — the chips stay and the cola shows zero; clear manually if you want.
- New picks in a dropdown only list values that still exist under the other active filters (cascade).
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
- **Precio sugerido (D15):** cheapest same-bucket peer as referent; if `markup_min` is set and peer markups exist, skip peers below that floor. Caps `precio_min`/`precio_max` when set. **Perdiendo:** delta = sugerido − nuestro (negativo = bajar). **Ganando:** holgura hasta el siguiente peer. TOP rows show `referent_note` (D22): who is Referente vs discarded by markup/price criteria. Disposition **Excluido** sellers never appear on the board.
- **Pool promos (D20–D23):** under the TOP board, up to **3** slots: **one** SMART-like, **one** other DEAL/campaña, **one** Premium (name contains `premium`). Markup band + DEAL range vs `precio_sugerido` for candidates. If Premium is already `started`, still show it with **Aplicada**. Seller-priced rows show **aplicar a $sugerido** (clamped to min/max). **Aplicar** (permiso `promos.escribir`) → Confirmar → same `POST /promociones/item/{mla}` as Productos (`deal_price` or `precio_visto`).
- Missing snapshot: `POST /para-ganar/criterios/{mla}/competencia/refresh` (permiso `productos.editar_precios`) fetches via the same `refrescar_competencia_catalogo` path as Promociones — **per MLA only** (ML throttle).
- **Consultar filtrados (A1):** from Advisor, `POST /para-ganar/evaluar-filtrados` with the same alcance query as the cola (permiso `productos.editar_precios`). Runs P5 (R1–R4) on every MLA in scope — including those not in Periodicidad. Does not use the Pendiente/Sin novedades chips as input. Empty scope → 422.

### Sellers del catálogo

- Sync pulls members from latest competition snapshot.
- Dispositions: **Activo** | **Excluido**. Excluido = fuera del ranking (como si no existiera), sigue en la lista; aviso discreto si hay alguno.

### Periodicidad (P2 + P3.1)

- Tables: `para_ganar_periodicidad_ean` (+ `…_ean_mla` for explicit MLA lists; `…_ean_mla_descartado` for dismissed new-MLA alerts).
- API (`productos.ver` read / `productos.editar_precios` write):
  - `GET /para-ganar/periodicidad` — list of **subscriptions only** (q, page)
  - `GET /para-ganar/periodicidad/catalogo` — EANs in the **same alcance filters** as Advisor (subscribed + not); optional `suscripto=true|false`; `mlas_nuevos=true` for gaps
  - `GET /para-ganar/periodicidad/catalogo/{ean}/mlas` — MLAs of that EAN inside the current filters (checkbox picker; `es_nuevo`)
  - `POST /para-ganar/periodicidad/catalogo/descartar-mlas-nuevos` — dismiss current new-MLA alerts in alcance (does **not** subscribe)
  - `POST /para-ganar/periodicidad/{ean}/descartar-mlas-nuevos` — same for one EAN
  - `GET/PUT/DELETE /para-ganar/periodicidad/{ean}`
- `scope_mode`: `all` (todo el EAN) | `mlas` (lista explícita) | `rules` (`tipos_publicacion` / `pricelist_ids` / `tienda_oficial_ids`).
- UI (P3.2–P3.3): ScopeFilters (Sin/Con criterio a nivel EAN); catálogo; **Todo el EAN** o checkboxes MLA; chip **Con MLA nuevos**; badge en fila + `es_nuevo` en detalle; **Descartar avisos nuevos** (detalle) y **Descartar todos los avisos nuevos** (toolbar). Aviso ≠ suscribir: solo limpia el badge hasta que aparezcan MLAs nuevos distintos. `rules` legado: migrar al guardar.

### Motor P5 (R1–R4)

- `POST /para-ganar/periodicidad/evaluar` (`productos.editar_precios`) evaluates **enabled** Periodicidad MLAs (`all|mlas|rules`, `catalog_listing=true`).
- `POST /para-ganar/evaluar-filtrados` (A1, same permiso) evaluates MLAs in the **Advisor alcance** filters (same params as cola / aplicar-masivo). Shared core: `evaluar_mlas`.
- First usable snapshot → `pendiente` and stores `competition_baseline` (rank, price, `suggestion_status`, `in_top`, `fecha_consulta`). Later runs: R1 rank/`in_top` worsened; R2 catalog win lost; R3 winning with raise room; **R4** if any **candidate** promo projects better `(X′,Y′,Z′)` (price/markup/rank) than current `(X,Y,Z)` without clearly worsening another dimension (co-funding markup included for SMART-like). Any R → `pendiente`, else `sin_novedades`. Re-run overwrites `estado`. Missing snapshot → skip.

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
10. ~~Show promo pool (D18→D19→D20 one-per-type)~~.
11. ~~Show deal at `precio_sugerido` (clamped) + wire enroll from Advisor (D23)~~.
12. ~~**Periodicidad P1–P3**~~ (shell + API + UI por EAN).
13. ~~**P4** — estados Advisor Pendiente / Sin novedades~~ (tabla + cola + chips; escritura = P5).
14. ~~**P5** — motor de evaluación~~ (R1–R4; `POST /para-ganar/periodicidad/evaluar`).
15. ~~**A1** — Advisor **Consultar filtrados**~~ (`POST /para-ganar/evaluar-filtrados` + botón Advisor).
16. **P6** — trigger periódico de catálogo.
17. **P7** — vista flotante (después).
18. ~~Herencia producto/PM~~ — **deprecado:** filtro EAN + aplicar masivo cubre el caso.
19. ~~Heurística campañas de marca (A PVP…)~~ — **deprecado:** no aporta.

---

## Out of scope (for now)

- Literal port of the Chrome extension / Sheet export loop (innecesario).
- Scraping ML pages as primary data path.
- Merging Draft PR #1796 until product says so (todavía falta mucho trabajo útil antes).

