# promos-precio-vigente — aplicar una promo al precio que el operador vio

Branch: `fix/promos-precio-vigente-al-aplicar` (from `origin/main`, PR targets `main`).
TDD: Strict TDD (session config "Strict TDD Mode: enabled"). Runners: `backend/venv/bin/pytest`, `pnpm test` (vitest).

## Objective

An ML-priced promotion (SMART, PRE_NEGOTIATED, PRICE_MATCHING) is enrolled only at the
price the operator saw and confirmed. If ML moved the offer since, nothing is sent and the
operator is shown the new price and markup before deciding again. After enrolling, the price
ML says it applied is checked against the confirmed one.

## Incident (production, 2026-10-05, money path)

MLA2385168136, SMART "Ofertas compartidas 10.10" (P-MLA18091086). Panel showed ~$469.xxx with
positive markup; operator applied; after refresh the same SMART showed $372.408,72 with NEGATIVE
markup and the publication was live on ML at $372.408,72. ML recalculates SMART/PRICE_MATCHING
candidates daily ("Co-fondeada automatizada y precios competitivos", updated 2026-06-09); the
enroll POST takes `promotion_id, promotion_type, offer_id` (no price) and returns
`{offer_id, price, original_price}`.

## STEP 0 — what the code did before this change (verified)

Enroll path:
- `backend/app/routers/ml_promotions.py:149-155` `EnrollRequest` = `promotion_id, promotion_type,
  deal_price?, top_deal_price?`. No field for the price the operator saw.
- `backend/app/routers/ml_promotions.py:530-568` `POST /promociones/item/{mla}` -> `enroll_one_item`.
- `backend/app/services/ml_promotions_write_service.py:402-403` kill switch first
  (`PROMOS_WRITE_ENABLED`), `:405` writable-type gate (`WRITABLE_PROMOTION_TYPES`, `:80`).
- `:408` LIVE read `ml_webhook_client.get_item_promotions(mla)` (proxy
  `GET /api/promociones/item/{mla}`, `ml_webhook_client.py:975-994`).
- SMART-like (`SMART_LIKE_PROMOTION_TYPES = {SMART, PRE_NEGOTIATED, PRICE_MATCHING}`, `:89`):
  `:442-443` takes the live `ref_id` as `offer_id` and the live `price`; `:460-469` POSTs
  `offer_id` only (`deal_price=None`). **The live price is never compared with anything the
  operator saw — the backend enrolls at whatever ML's current offer is.** The live entry's
  `status` is not checked either (a non-candidate entry would still be POSTed).
- `:483-485` from ML's 201 body only `offer_id` is read; **ML's returned `price` is ignored**.
  `outcome["price"]` (`:474`, `:664`) is the pre-POST live price, not what ML applied.
- Frontend `PromoApplyControl.jsx:206-211` sends `deal_price` only for range types
  (SELLER_CAMPAIGN/DEAL); for SMART-like it sends just `promotion_id/promotion_type`.

Display path:
- `MlaPromocionesPanel.jsx:107-141` panel data = `GET /promociones/item/{mla}`
  (`ml_promotions.py:408-444`), which reads the MIRROR `ml_item_promotions` (mlwebhook DB, owned
  by the ml-webhook bridge) via `fetch_item_promotions(active_only=True)`
  (`ml_promotions_service.py:226-282`). Never the live proxy.
- Price shown: `MlaPromocionesPanel.jsx:235` `promo.price > 0 ? promo.price :
  promo.suggested_discounted_price` (mirror values).
- Markup shown: `ml_promotions.py:431` `enriquecer_markup_por_promo` ->
  `ml_promotions_pricing.py:255-284`: effective price (`price`>0 else suggested, `:104-115`) +
  ML co-funding (`payload.meli_percentage * original_price`, + boost, `:40-101`), then the
  commission/limpio/markup chain. `/item/{mla}/markup` (`:447-461`) is the plain-price variant
  used only by the SELLER_CAMPAIGN/DEAL price input.
- Mirror freshness: the open-panel pull (`POST /item/{mla}/refresh`, proxy reconcile) only runs
  when the user has `promos.escribir` (`MlaPromocionesPanel.jsx:83-84,139`; endpoint gated at
  `ml_promotions.py:496-499`) and only when the parent passes `pullOnOpen`
  (`TreeNode.jsx:350`: not on "Expandir todo", not right after the manual refresh). The pull is
  fail-soft (`ok:false` -> panel still renders the mirror with a notice). `updated_at` is in the
  response (`ml_promotions.py:95`) but never shown.

Mechanism for a stale $469k: the panel renders the mirror row; ML recalculated the SMART
candidate (daily) to $372.408,72; the backend re-read the live offer at apply time and enrolled
at THAT price without comparing it to what the operator saw. Any path where the mirror row is
older than ML's recalculation produces it: pull not run (read-only user / expand-all /
post-refresh remount), pull failed (fail-soft, notice only), or the bridge's reconcile not
rewriting the candidate's price. The apply itself is the defect regardless of why the mirror
was stale: it never had a "price the operator agreed to" to check against.

Not confirmable from this repo (needs the ml-webhook bridge): why the mirror had NO rows for
MLA2385168136 when queried later while the live proxy returned 9 promos — i.e. whether its
reconcile deletes/skips rows. Our side can only detect and say so (T4).

Scope decision per type (code + ML docs):
- Guarded (ML sets the price, operator only accepts it): SMART, PRE_NEGOTIATED, PRICE_MATCHING
  (= `SMART_LIKE_PROMOTION_TYPES`).
- PRICE_MATCHING_MELI_ALL, LIGHTNING, DOD: not writable in this app (`:75-80`), nothing to guard.
- SELLER_CAMPAIGN / DEAL: out of scope — the operator types `deal_price`, it is sent to ML as
  is and validated against the live [min,max] (`:497-532`). ML cannot move it under them.

## Tasks

- [x] T0 STEP 0 verification recorded (above). Route: inline (read 1-3 files at a time).
- [ ] T1 Backend pre-apply guard for SMART-like: `precio_visto` required; live status must be
      `candidate`; live price must equal `precio_visto` to the cent; else 409 with
      `{precio_visto, precio_actual, markup_actual}` and nothing sent. Fail closed on live-read
      failure / missing / non-candidate. Kill switch unchanged. Route: inline (single writer).
- [ ] T2 UI confirm flow on 409: new price + markup (red if negative), "¿Aplicar igual a $X
      (markup Y%)?", confirming re-sends with the new `precio_visto`.
- [ ] T3 Post-apply check: compare ML's returned `price` with the confirmed one; flag + log;
      panel red alert with one-click "Quitar promo" (existing remove flow).
- [ ] T4 Freshness: "actualizado hace X" per row; open-panel pull for `promos.ver` users;
      empty mirror while ML has promos / refresh failed -> "No se pudo confirmar con ML".

## Acceptance / checks

ruff format + check, targeted pytest, vitest (counts), eslint 0 errors, build, full backend
suite once at the end.

## Evidence

(filled as tasks close)
