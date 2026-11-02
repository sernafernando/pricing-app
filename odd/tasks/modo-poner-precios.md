# modo-poner-precios — flujo rápido de precios + hay mejores ofertas

Branch: `feat/modo-poner-precios` (tracker from `upstream/main`). PRs → `sernafernando/pricing-app:main`.
Delivery: Feature Branch Chain (stacked children ≤400 add+del). Runners: `backend/venv` pytest, `pnpm test`.

## Objective

Parallel workflow in Publicaciones ML so the PM sets prices fast and activates promos, plus a “hay mejores ofertas” filter/flag fed by promo webhook novelty.

## Specs

S1. Publicaciones ML has a **MODO PONER PRECIOS** button that activates this mode.
S2. In mode: hide top metrics/KPIs; allow minimize/collapse of the filters drawer/band; force vista `publicacion` (not agrupado).
S3. In mode: fixed column preset: Estado | Precio | Ventas 7D | Ventas 30D | Markup Actual | Markup real 30D | Última venta | Ageing | Stock Full | Stock ERP | Código | Marca.
S4. Under **Precio**, show ERP list type (Clásica / 3 cuotas / …) from `publicaciones_ml.pricelist_id` / `lista_nombre` (NOT `listing_type_id`). Map: 4=Clásica, 17=3C, 14=6C, 13=9C, 23=12C (+ PVP). Reuse `ML_PUBLICATION_TYPE_LABELS`.
S5. Row click → right panel ~33%. In this mode: **no tabs** — minimal info + price edit field.
S6. Enter on price: (1) load price into Pricing; (2) propose best SMART, best DEAL, and Premium+current month (name match PREMIUM + current month); (3) activate fire-and-forget without staying on the pub; (4) on accept: update **Pricing and MeLi**; (5) suggestion comparison baseline = price the PM put in Pricing.
S7. On promo webhook novelty: compare candidates vs **consumer-facing MeLi price** (`sale_price`). Better = higher markup OR lower price with markup ≥. Persist flag; clear on activate / when no better candidate; Descartar clears flag and next better novelty re-marks (fingerprint so same candidates do not instantly re-flag).
S8. UI filter “Hay mejores ofertas” + Descartar button; flag on existing promo table if it fits. Permissions = current edit-price + activate-promos (`productos.editar_precio_*` / `promos.escribir`).
S9. Reuse `enriquecer_markup_por_promo`, POST enroll, promotions intake, existing columns. Do not mix with `feat/publicaciones-repair`.

Product locks (Gabe 2026-11-02): hay_mejores baseline = MeLi consumer price; same perms as edit+enroll; accept suggested promo updates Pricing AND MeLi.

## Tasks

| ID | Specs | Route | Status | Commit |
|----|-------|-------|--------|--------|
| T1 | S7 (backend compare+flag+discard; list filter deferred to T2) | inline | done | 701388e1a / PR #2026 |
| T2 | S7–S8 (FE filter + discard + promo flag) | inline | done | 1b4aa43be / PR #2027 |
| T3 | S1–S3 (modo shell: button, KPIs, filters, vista, columns) | inline | done | 85ee33bf4 / PR #2029 |
| T4 | S4–S5 (lista under Precio + mode panel) | inline | pending | — |
| T5 | S6 (Enter suggest SMART/DEAL/Premium + enroll) | inline | pending | — |
| T6 | S8–S9 (ayuda Publicaciones ML) | inline | pending | — |

## Chain slices (forecast)

| Slice | Branch | ~lines | Depends |
|-------|--------|--------|---------|
| 01 | `feat/modo-poner-precios-01-hay-mejores-be` | ~300 | tracker |
| 02 | `feat/modo-poner-precios-02-hay-mejores-fe` | ~250 | 01 |
| 03 | `feat/modo-poner-precios-03-modo-shell` | ~300 | 02 |
| 04 | `feat/modo-poner-precios-04-panel-lista` | ~300 | 03 |
| 05 | `feat/modo-poner-precios-05-enter-suggest` | ~350 | 04 |
| 06 | `feat/modo-poner-precios-06-ayuda` | ~120 | 05 |

delivery_strategy: `auto-chain` / Feature Branch Chain. Tracker PR draft/no-merge until children integrate.

## Log

L1. User: Sos el **change agent** de Pricing App para **MODO PONER PRECIOS** en Publicaciones ML. [full brief 2026-11-02]
L2. Explored FE PublicacionesML + BE promos: no `hay_mejores` flag; enroll already `recompute_item` for Pricing; lista labels in `mlPublicationTypes.js`; promo filters via mlwebhook `mla_scope`.
L3. T1 shipped as PR #2026 (370 lines): compare+fingerprint+migration+hook+discard+clear-on-enroll. List filter deferred to T2 with FE. GGA via `GGA_PROVIDER=opencode` (global claude CLI missing).
L4. T2 shipped as PR #2027 (130 lines vs 01): list filter + row flag + PromoFilters + Descartar in panel. Stacked on #2026; PR targets main (fork base branch not on upstream).
L5. Gabe reminder: no AI attribution; each PR ≤400 add+del.
L6. #2026 Postgres CI: mlpub_schema missed 20261102_hay_mejores_ofertas — fixed on 01 (`3879a7164`), merged to 02.
L7. T3 shipped as PR #2029 (392 lines vs 02): local `ponerPreciosMode` flag (not URL `modo`), KPI hide, filter collapse, force publicacion, column overlay. No attribution.
L8. #2026 Postgres CI green after mlpub_schema migration append; #2027 also green.
