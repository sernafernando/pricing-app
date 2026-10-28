# PARA GANAR Pro — source map (emulate & improve, not a literal port)

**Living decisions, commit trail, and operator manual seed:** [`para-ganar.md`](./para-ganar.md) (update that file as we ship; this map stays extension archaeology).

Source: [catalog-context-collector](https://github.com/GabeADemarco/catalog-context-collector) branch `experimental-endpoint-chicho`  
Primary refs: `extension/MANUAL_USUARIO_PARA_GANAR_PRO.md`, `extension/viewer/app.js`, `extension/background.js`, `DESIGN.md`  
Date: 2026-10-27  

This document captures **what the Chrome extension does today** so Pricing can emulate the *intent* and improve it. It is **not** a port checklist.

---

## Product intent (keep)

An operator walks many products, sees **where we win / lose per publication type**, gets a **reference “price to win”**, optionally adjusts it (rebate / pesos), and leaves with an actionable list. The goal is **maximize margin without giving away more ranking than needed**.

In Pricing this becomes an **advisor**: criteria-driven suggestions per MLA, filterable state, accept → apply via ML promotions (PREMIUM / SMART / etc.), not a Sheet export loop.

---

## What Pro is today (extension)

| Aspect | Behavior |
|--------|----------|
| Surface | Visor mode `?mode=pro` (“PARA GANAR Pro”) |
| Entry | EAN from base (`MLAs.txt`) or personal ERP list |
| Data | `catalogCompetition?format=processed` via ml-webhook; markups via Pricing `calcular-markup` |
| Work grain | **EAN → catalog MLA → publication type** (Clásica / 3C / 6C / 9C / 12C) |
| Output | Check rows → export to Google Sheets + local TSV backup |
| ML writes | **None**. Opens ML URLs; operator applies prices/rebates elsewhere |

Hardcoded “own” seller nicknames: `GAUSSONLINE` / `GAUSS ONLINE`. Paused / offline / no-stock own listings often **missing** from the snapshot → no exportable row.

---

## Core algorithm (extension)

### Ranking per tipo

1. Competitors with valid price for that tipo (tipo from **installments**, not `listing_type_id`).
2. Sort by price ascending (endpoint order as tie-break).
3. Default referent = **cheapest**.
4. Optional **Ganador ≥ umbral**: if cheapest markup &lt; min %, pick first competitor with markup ≥ min % (`*` / `!` markers).
5. Optional **seller de referencia** (session nickname): that seller’s price becomes the referent (overrides umbral).
6. Own price for the tipo = cheapest own listing of that tipo in the catalog.
7. **Precio PARA GANAR** = referent price when own MLA exists for the tipo.

### Delta (UI only, not exported)

- **Winning** (own ≤ referent, umbral off): air to 2nd place (positive = room to raise).
- **Losing** or umbral on: referent − own (negative = how much to drop).

### Export pricing fields

- **Ajuste exp.** (pesos): positive subtracts from PARA GANAR → **PX FINAL**; negative add only when winning and umbral off.
- **Dto Rebate** (%): **PX OFERTA SELLER** = PX FINAL / (1 − dto/100).
- **Markup PX FINAL**: on-demand button, not auto.

---

## Mapping to Pricing IDEA criteria

| IDEA criterion | In extension Pro | Direction for Pricing advisor |
|----------------|------------------|-------------------------------|
| Markup min / max | Min only via optional umbral; no max | First-class criteria per MLA / product / bulk PM |
| Win catalog | Ranking is **per tipo**, ignores `is_winner` | Use catalog competition + win/lose explicitly |
| TOP sellers by tipo | Single nickname ref only | Configurable TOP-N / band |
| Ignore international | No | Filter when data exists |
| Discard residual stock | No (`ventasSeller` unused) | When ML exposes stock signals |
| Discard low reputation | No | When available |
| Monopoly ceiling | Only informal “air to 2nd” delta | Explicit raise-without-losing-#1 rule |
| Price min / max | Floor 0 on PX FINAL only | Hard caps in criteria |
| Apply via promotions | Not automated | **Core improvement**: suggest PREMIUM / SMART and apply through Pricing + ml-webhook |
| SMART meli component | Not modeled in Pro UI | Markup for company vs shopper price (IDEA) |
| Auto / periodic run | Manual Refresh EAN / TODO | Scheduler + competitor price triggers |
| Unit of work | EAN + catalog + tipo | **MLA** (sync pairs as one unit) per IDEA |

---

## What to emulate (must-have UX/logic)

1. Clear **win/lose per listing type** with a single reference price.
2. Optional **markup floor** on the competitor used as referent (avoid +0.01% “winners”).
3. Operator **override** before commit (ajuste / suggested price).
4. Work queue feeling: what I already reviewed / what needs action (Rev./Mar. → filterable suggestion states in Pricing).
5. Trustworthy **own publication** visibility (do not hide paused/offline without saying so).

## What to improve (Pricing-native)

1. **MLA-centric** model + sync pairs, not EAN→Sheet.
2. Persist criteria (PM bulk + per product + per MLA) with permissions.
3. **Suggestion state machine** (pending / accepted / dismissed) + filters.
4. Apply through **promotions API** (already wired in Pricing), considering SMART meli share for markup.
5. Implement IDEA filters the extension never had (international, stock residual, reputation, monopoly ceiling, price caps).
6. Periodic + event-driven evaluation (competitor price change, new ML offers).

## Non-goals (from extension DESIGN)

- Do not scrape ML pages as the primary path (endpoint/catalog data already in Pricing).
- Do not treat Sheet export as the product outcome.

---

## Pricing shell (started)

- Route: `/para-ganar` (`productos.ver`); subvistas `?vista=advisor` (default) y `?vista=criterios`
- Page: `frontend/src/pages/ParaGanarAdvisor.jsx` — tabs Advisor | Criterios; misma cola MLA; detail distinto
- Scope filters (shared): tipo (Clásica/3/6/9/12 cuotas), lista de precios, tienda oficial, marca, subcategoría, PM, EAN/código, MLA catálogo, **costo USD desde/hasta** + search — `ParaGanarScopeFilters`; faceted `GET /api/para-ganar/alcance-opciones` (same params as cola; each facet skips itself); tienda names from `ml_tiendas_oficiales` via `useTiendasOficiales` (seed `backend/scripts/seed_ml_tiendas_oficiales.py`); sandbox MLA→store link via minimal `tb_mercadolibre_items_publicados` rows (`backend/scripts/seed_para_ganar_publicados_stores.py`: TP-LINK→471846, else Gauss 57997); “Sin tienda” also matches MLAs without that row
- API: `GET /api/para-ganar/cola` — active MLAs (precio, catálogo, par sync por `inventory_id`) with Productos-like scope params
- Nav: Sidebar → Productos → PARA GANAR (badge WIP)
- Catalog: `frontend/src/registry/screenCatalog.js`
- Criterios: override por MLA (`GET/PUT /api/para-ganar/criterios/{mla}`); masivo `POST /criterios/aplicar-masivo`; Advisor pool D18 (SMART else DEAL/campaña en rango del sugerido; Aplicar gris); enroll TBD; herencia producto/PM TBD
- System defaults (source=`default`): markup 5–15%, top sellers 5, precio min/max unset, all flags off
- Catalog sellers: `para_ganar_catalog_sellers` + `GET/PUT /criterios/{mla}/sellers` (dispositions: active / ignore_participant / hide / exclude_from_top); members synced from latest `ml_catalog_competition` snapshot

## Suggested next step

See backlog in [`para-ganar.md`](./para-ganar.md): cost USD scope filter; mass criteria = markup only + per-MLA precio↔markup sync; TOP = price positions; then product/PM inheritance and suggestion engine.
