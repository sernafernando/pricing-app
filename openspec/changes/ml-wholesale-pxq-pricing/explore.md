# Exploration: ml-wholesale-pxq-pricing

> Materialized from Engram observation #1225 (`sdd/ml-wholesale-pxq-pricing/explore`).

## Settled calculation contract

No new markup endpoint. Reuse `calcular_comision_ml_total` and `calcular_limpio` in
`backend/app/services/pricing_calculator.py`, passing `precio * cantidad` as the price and
`costo_envio` = shipping cost of the WHOLE wholesale shipment (not the per-unit cost).

### 1. ML fees key off the order total

Source: <https://vendedores.mercadolibre.com.ar/nota/precios-mayoristas-vendes-mas-pagas-menos>
— "si hacés envío con Full o Colecta no pagás costo fijo en ventas mayores a $ 33.000".

The low-price fixed charge is evaluated on the ORDER TOTAL, not the unit price. The bracket
selection at `pricing_calculator.py:276-283` is therefore already arithmetically correct when fed
`precio * cantidad`: the tier is picked on the total and charged once.

An exploration subagent refuted this citing general selling-cost docs ("por unidad vendida") and
was WRONG for the wholesale case — those docs describe ordinary listings, not wholesale orders.

### 2. Shipping is one shipment, and it does not scale linearly

Reference table (1 kg product, green reputation):

| Units | Wholesale shipping | Naive per-unit multiple |
|-------|--------------------|-------------------------|
| 1  | $13.121 | $13.121 |
| 5  | $18.711 | $65.605 |
| 10 | $22.221 | $131.210 |
| 30 | $50.311 | $393.630 |
| 70 | $70.156 | $918.470 |

Savings reach 80%, except for bulky and "Supermercado" products.

## The defect

`pricing_calculator.py:295-337` `calcular_limpio` — the free-shipping gate
`if precio >= MONTOT3_val` then `envio_sin_iva = costo_envio / 1.21`. The gate fires correctly on
the total, but it subtracts ONE unit's shipping for an N-unit order, understating cost and
inflating markup. The fix is passing the right `costo_envio` value, not changing the formula.

## Gotchas found

- There is NO weight field anywhere in `backend/app/models/`. `aporte_meli_pesos` in `oferta_ml.py`
  is money, not kilos. Wholesale shipping cost cannot be derived from product data today.
- PxQ write semantics: `POST /items/{ITEM_ID}/prices/standard/quantity` REPLACES the entire prices
  array — it is not a PATCH. A local tier table must be the source of truth to compute
  keep (`{"id": ...}`) / create (object without id) / delete (omit the id) diffs. Without a local
  mirror, a write silently deletes live tiers that were never mirrored locally.
- No global collapse infrastructure exists on the frontend.
  `frontend/src/components/promociones/TreeNode.jsx` holds `isOpen`/`promosOpen` in local
  `useState`; `frontend/src/store/treeViewStore.js` only holds `showFamilia`.
- Process lesson: do not trust a subagent's refutation of a user's domain claim without checking
  the primary source.

## User decision: shipping cost resolution (hybrid, fail-closed)

1. Manual per-tier value always wins.
2. Else, if product weight is available, compute from weight.
3. Else FAIL CLOSED — mark the tier incomplete and refuse to write it to ML.

Explicitly rejected: silently falling back to the per-unit `costo_envio`. That reproduces the exact
bug above behind a default (~$37.000 understated on a 30-unit order).

## Reference for write-path pattern

`backend/app/services/ml_promotions_write_service.py` — kill-switch first, eligibility validated
before any POST, fresh live read before writing, fail-closed on validation errors.

## Scope signal

3-4 PRs. Does not fit a single 400-line review budget.
