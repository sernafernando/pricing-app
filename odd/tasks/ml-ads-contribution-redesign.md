# ml-ads-contribution-redesign

Rebuild the "Aportes de marcas (Ads ML)" page (`/ml-ads-aportes`) and its two modals to the Stitch designs, plus the backend figures they need.
Branches off `origin/main`, one PR per task, each merged before the next (stacked-to-main). Runners: backend pytest (`backend/.venv`), frontend `pnpm exec vitest run --project=unit`.

## Specs

- **S1** (user, L1): "diseñá la vista de las páginas con stitch o con open design porque parece que hiciera un nene las páginas que diseñás vos". The designs live in Stitch project "Pricing App - Ventas ML" (563568849436341277), design system "Precision Operations".
- **S2** (user, L2 "dale", answering "¿Lo paso a código, con esa parte del backend incluida?"): the code follows the Stitch screens:
  - page: screen `1daaacea37a1490a8de965c1386b4b78` ("Chips de Aportes Optimizados");
  - add/edit modal: screen `bca471d5626549c1aa319b2d41ba3dba`;
  - delete modal: screen `5de30957dd9d419b9c132bd8bda26903`.
  Built with the app's tokens (`design-tokens.css`), so it also works in dark mode; the Stitch colors are the light theme.
- **S3** (page, from the design): header with title, the description "Lo que una marca paga de una campaña de Product Ads deja de restarse en Métricas ML.", the Desde/Hasta range and "+ Agregar aporte"; 4 KPI tiles "COSTO ADS DEL PERÍODO", "APORTE DE MARCAS" (with "% del costo"), "COSTO NETO", "CAMPAÑAS CON APORTE" ("N de M"); toolbar with "Buscar campaña…", "Todas · Con aporte · Sin aporte" and an advertiser filter; table CAMPAÑA (name, mono id, advertiser tag), ESTADO badge, COSTO DEL PERÍODO, APORTE, NETO, APORTES CARGADOS (one-line chips: value, "TODO"/"DIFERENCIA" badge, range, pencil, trash; "Sin aportes" + "+ Aporte"), a Total row, and the footnote "El aporte de monto fijo se reparte por costo entre los días del rango. 'Devuelve diferencia' cuenta como máximo lo gastado en el rango." Search, segment and advertiser filter work on the loaded rows (no new request).
- **S4** (add/edit modal, from the design): "Campaña", "Tipo de aporte" segmented ("Porcentaje del costo" / "Monto fijo"), "Monto" (or percentage), "Cómo se liquida" as two option cards ("Se recibe todo" — "La marca paga el monto completo aunque la campaña gaste menos."; "Devuelve la diferencia" — "Si la campaña gasta menos, solo cuenta lo gastado."), "Rango de fechas", "Nota (opcional)", and a preview line "Costo de la campaña en el rango: $ X · Aporte que cuenta: $ Y · Neto: $ Z" from the backend. Footer "Cancelar" / "Guardar aporte".
- **S5** (delete modal, from the design): "¿Borrar este aporte?", summary (Campaña, Aporte with its settlement badge, Rango), "El costo que cubría este aporte vuelve a descontarse en Métricas ML.", the error alert when the delete fails, "Cancelar" / "Borrar aporte".
- **S6** (backend, decision by the assistant, stated to the user before L2): APORTE and NETO per campaign and the modal preview are computed by the server, with the same rule and source as the Métricas ML board (ml-ads-brand-contribution S9: item rows of `ml_ads_item_days`; percentage p% of the cost; fixed amount spread by cost over the whole range, `full` all of it, `refund_difference` at most the range's spend), so the page's "Aporte de marcas" equals the board's for the same range. Additive fields only: `GET /ml-ads/campaigns` gains `contribution` per campaign (and `advertiser_name`); a new read `GET /ml-ads/contributions/preview` (the create body as its query) answers the modal line. NETO = COSTO DEL PERÍODO − APORTE; COSTO keeps the campaign rows (`ml_ads_campaign_days`) while APORTE uses the item rows, which match unless a day's item rows are incomplete.

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S6 | inline | merged #1747 | RED 8 failed (KeyError contribution/advertiser_name, preview 404), GREEN 12 passed; preview made a GET after CI's write-route guard |
| T2a | S2, S3 | inline | merged #1749 | table with aporte/neto/one-line chips; css-guard rule 2 fix (range inputs compose inputSm) |
| T2b | S3 | inline | merged #1750 | KPI tiles + toolbar filters; GGA fixes with RED tests (empty filter message, stale advertiser, loading dash) |
| T3a | S4 | inline | merged #1753 | add modal with campaign choice and debounced preview; value input composes forms-tesla input |
| T3b | S5 | inline | this PR | delete summary; visual test aportesAdsMl (1440/1920, light/dark) pins one-line chips and whole pills |

## Log

- **L1** (2026-10-26, user): "diseñá la vista de las páginas con stitch o con open design porque parece que hiciera un nene las páginas que diseñás vos"
- 2026-10-26: OpenPencil MCP refused the connection; designed in Stitch with "Precision Operations" (the Ventas ML / Métricas ML system). Page, add modal and delete modal generated; the page chips edited to stay on one line and the kebab column dropped.
- **L2** (2026-10-26, user, to "¿Lo paso a código, con esa parte del backend incluida?"): "dale"
- 2026-10-26: forecast ~1000 authored lines over 3 PRs (T1 ~300, T2 ~400, T3 ~350). No advertiser name is stored; T1 serves the two known advertisers' names (25713 GAUSS, 714700 TPLINK, from the Ads API access check) and falls back to the id.
- 2026-10-26 (T1): `GET /ml-ads/campaigns` gains `contribution` (window share, Board rule over item rows) and `advertiser_name`; `POST /ml-ads/contributions/preview` takes the same body as create and returns spend, counted, net, writing nothing (a fixed amount on a range with no spend counts 0, as on the Board). RED 8 failed, GREEN figures + existing campaigns tests 12 passed, ruff clean. Risk: none (additive fields and a new read).
- 2026-10-26 (T1, GGA): campaign figures read the item rows in one query (`_daily_spend`) instead of one or two per contribution; `ADVERTISER_NAMES` carries the ponytail marker; S6 fixed to POST and documents the two cost bases. 12 passed, ruff clean.
- 2026-10-26 (T1, CI): `tests/routers/test_ml_ads.py::test_the_only_writes_are_the_brand_contributions` failed: the preview was a POST. It writes nothing, so it became `GET /ml-ads/contributions/preview` with the create body as a query model; the guard stays as it was.
- 2026-10-26: T2 and T3 split to stay under ~400 lines each (T2a/T2b, T3a/T3b). A real-Chromium screenshot against the Stitch PNG caught what unit tests could not: the kit pill wraps one-word labels in narrow columns, `.btn-tesla.sm` outweighs module padding, and `.table td` colour outweighs the money tones; fixed and pinned in the visual test.
- 2026-10-26: CI css-guard rule 2 rejects hand-rolled control boxes; the range, search, advertiser and value controls now compose forms-tesla. Feature closes with T3b.
