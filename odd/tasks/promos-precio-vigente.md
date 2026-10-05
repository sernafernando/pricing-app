# promos-precio-vigente — aplicar una promo al precio que el operador vio

Branch: `fix/promos-precio-vigente-al-aplicar` (from `origin/main`, PR targets `main`).
Engram mirror `odd/promos-precio-vigente/tasks`: PENDING (mem_save refused: multiple active
runtime sessions match this directory; resync when available).
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
- [x] T1 Backend pre-apply guard for SMART-like: `precio_visto` required; live status must be
      `candidate`; live price must equal `precio_visto` to the cent; else 409 with
      `{precio_visto, precio_actual, markup_actual}` and nothing sent. Fail closed on live-read
      failure / missing / non-candidate. Kill switch unchanged. Route: inline (single writer).
      Commit `40592151` (with T3 backend).
- [x] T2 UI confirm flow on 409: new price + markup (red if negative), "¿Aplicar igual a $X
      (markup Y%)?", confirming re-sends with the new `precio_visto`. Commit `e6a502d2`.
- [x] T3 Post-apply check: compare ML's returned `price` with the confirmed one; flag + log;
      panel red alert with one-click "Quitar promo" (existing remove flow). Backend `40592151`,
      UI `e6a502d2`.
- [x] T4 Freshness: "actualizado hace X" per row; open-panel pull for `promos.ver` users;
      empty mirror while ML has promos / refresh failed -> "No se pudo confirmar con ML".
      Backend `79ec2b62`, UI `dc1edaac`.

## Contract decisions

- Tolerance: both prices rounded to cents (half-up) must be equal — absorbs JSON float noise
  only (`_to_cents`, `ml_promotions_write_service.py`).
- HTTP: `rejected_price_changed` -> 409, body root `{status, mensaje, precio_visto,
  precio_actual, markup_visto, markup_actual}` (the app-wide handler in
  `app/core/exceptions.py` returns a dict detail as the body root; a string detail becomes
  `{error: {code, message}}`). `rejected_not_candidate` -> 409 (message);
  `rejected_price_unconfirmed` (no `precio_visto`) -> 422; live read failure -> 503 (unchanged).
- `markup_actual` / `markup_aplicado` use `markup_de_oferta_live`: the live proxy entry is fed
  as the `payload` into `enriquecer_markup_por_promo`, i.e. the same chain (price + ML
  co-funding + boost) as the panel's `nuestro_markup`.
- `precio_difiere` is tri-state: True (red alert + Quitar promo, logged at ERROR), False,
  None = ML returned no usable price (amber "no se pudo verificar"), never collapsed to False.
- `POST /promociones/item/{mla}/refresh` is now `promos.ver` (it is a read-reconcile of our
  mirror; no write to ML). The TreeNode manual refresh BUTTON is still gated on
  `promos.escribir` in the UI — left as is (separate UX decision).
- One offer-price rule (review fix): backend `precio_de_oferta` (`ml_promotions_pricing.py`)
  and frontend `promoDisplayPrice` = `price` > 0, else `suggested_discounted_price` > 0, else
  none. Used by the panel display / `precio_visto`, the guard, the 409's `precio_actual` and
  every markup. `price` 0 is legitimate for candidate SELLER_CAMPAIGN/DEAL rows (seller sets
  the price); ML-priced types normally carry ML's offer in `price` even as candidates.
- Empty mirror (review fix): `GET /promociones/item/{mla}` is mirror-only again. The panel
  asks `GET /promociones/item/{mla}/confirmacion-ml` AFTER rendering an empty mirror
  (`{sin_promos_confirmado, promos_en_ml}`): never raises (any error/odd payload -> 200,
  unconfirmed), 2.5s hard deadline (`get_item_promotions(timeout=)` wraps the call in
  `asyncio.wait_for`; httpx only bounds each phase).
- "Quitar promo" (review fix): the red alert clears only on submitted/reconciled_applied;
  any other status or a rejected request keeps it; `onApplied` still fires so the panel
  re-reads the mirror.

Review fixes: `b6adf39c` (backend), `bad3b4a5` (panel confirm), `df14b113` (price rule FE +
Quitar promo). RED before each: backend 21 failed; frontend 7 failed. After: targeted promo
+ client pytest 517 passed; vitest promociones 373, full 1960 (147 files); eslint 0 errors;
build OK.
- Behaviour change for API clients: an enroll of SMART / PRE_NEGOTIATED / PRICE_MATCHING
  without `precio_visto` is now refused (422). The panel is the only client in this repo.

## Acceptance / checks

ruff format + check, targeted pytest, vitest (counts), eslint 0 errors, build, full backend
suite once at the end.

## Evidence

RED observed before each implementation:
- Backend T1/T3: `tests/unit/test_ml_promotions_precio_vigente.py` -> 29 failed, 1 passed (the
  DEAL control) — `enroll_one_item() got an unexpected keyword argument 'precio_visto'`,
  missing `markup_de_oferta_live`.
- Backend T4: 5 failed (refresh 403 for a promos.ver user; no `posiblemente_desactualizado`).
- FE T2/T3: `PromoApplyControl.precioVigente.test.jsx` -> 11 failed, 2 passed (DEAL contract,
  verified-equal no alert).
- FE T4: `MlaPromocionesPanel.freshness.test.jsx` -> 4 failed, 3 passed (controls).

Tests whose expectations changed on purpose (they encoded the old contract):
- `test_ml_promotions_write_service.py`: SMART/PRE_NEGOTIATED/PRICE_MATCHING enroll calls now
  pass `precio_visto`; live fixtures carry `status: "candidate"` (real proxy shape).
- `test_ml_promotions_router_refresh.py`: 403 now checks `promos.ver`.
- `PromoApplyControl.test.jsx`: the three "sends only {promotion_id, promotion_type}" tests now
  expect `precio_visto`.
- `MlaPromocionesPanel.test.jsx`: read-only describe now "without promos.ver never pulls";
  empty + failed refresh expects "No se pudo confirmar"; the plain empty-state test mocks a
  successful pull.

GREEN / checks:
- ruff format --check + ruff check on touched backend files: clean.
- Targeted pytest `-k "promo or promocion"`: 413 passed.
- vitest promociones: 357 passed (15 files); full `pnpm test`: 1919 passed (145 files).
- eslint: 0 errors (8 pre-existing warnings, none in touched files). `pnpm run build`: OK.
- Full backend suite, run once alone (`pytest tests/`): 7826 passed, 16 skipped, 0 failed
  (20m03s). (`pytest` at backend root also collects `test_turbo_simple.py`, a manual script
  that reads stdin — not part of the suite.)

## Known caveat

- "Quitar promo" right after a SMART enroll re-reads the live offer for its current `ref_id`;
  during ML's ~10-18s consistency window that may still be the CANDIDATE id and ML rejects the
  DELETE ("Rechazado por ML"). The red alert stays visible so the operator can retry.

## Needs the external ml-webhook bridge

- Why the mirror had 0 rows for MLA2385168136 while the live proxy had 9 promos (does its
  reconcile drop/skip rows?). This repo now detects and says so; the cause lives there.
- Whether the proxy passes ML's enroll 201 body (`price`) through unchanged. The code already
  relied on `body.offer_id`; if `price` were stripped, every apply would show the amber
  "no se pudo verificar" warning (fail-visible, not fail-silent).
