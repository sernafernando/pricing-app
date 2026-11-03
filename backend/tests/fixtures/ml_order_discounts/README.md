# ML order discounts fixtures (ml-ads-cupones-display T3a)

Real captured bodies of `GET /orders/{order_id}/discounts`. No value was edited, renamed or removed. Do not
hand-write fixtures here: a hand-made shape is an assumption about an API we do not own. Tests that perturb a
body (for example a 429 or 401 inside a 200) deep-copy a real one in the test and say so.

| File | Source | What it is |
|------|--------|------------|
| `discounts_top_coupon_1.json` | `ml-captures/coupons_20261102/orders_discounts_1.json` (outside the repo), captured 2026-11-02 | One ML-funded coupon (`seller` 0, `meli_campaign` P-MLA...) plus the seller's price `discount` (offer). |
| `discounts_top_coupon_2.json` | `ml-captures/coupons_20261102/orders_discounts_2.json` | One seller-funded coupon (`seller == total`, `meli_campaign` null), one ML-funded coupon and the `discount`. |
| `discounts_top_coupon_3.json` | `ml-captures/coupons_20261102/orders_discounts_3.json` | Three coupons (one seller-funded, two with `seller` 0, one of them with no `meli_campaign`) and the `discount`. |
| `discounts_not_found.json` | `tests/fixtures/ml_ventas_bonificacion/flex_loyal_discount_capture_20261007.json`, `order_2000018808335864_discounts.body` | The real 404 body of a sale with no discounts (HTTP 404). |
