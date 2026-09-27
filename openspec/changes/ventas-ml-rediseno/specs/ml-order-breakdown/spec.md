# Spec: Ventas ML redesign (delta spec, revision 1)

Source: proposal #2104 (rev 2) + explore #2103, with binding decisions Q1-Q3 resolved by the user. Spec describes WHAT must be true after the change; no implementation mechanics.

## Capability: ml-order-breakdown (modified)

### Requirements
- R32 The breakdown/detail endpoint response is additive: existing `lines`/`item_lines`/`iva_decomposicion`/`cadena_total_gauss` fields are preserved; new optional fields (buyer real name, payment method, installments, shipment substatus) are added.
- R33 The `cadena_total_gauss` total field returned by this endpoint equals the stored `total_gauss` for that order (same invariant as R6/panel R21, enforced at the API level too).
- R34 IVA non-reconcile display includes the specific reasons (`razones`), sourced from existing persisted data, not invented text.

### Scenarios
1. Given an order breakdown is requested, when the response is returned, then every field present in the current (pre-change) response shape is still present with the same meaning (backward compatibility for existing consumers/tests).
2. Given the payment's raw payload has `payment_method_id` and `installments`, when the breakdown includes payment info, then those fields are surfaced without inventing card brand/last-4 (explicitly out of scope — data does not exist, per explore).
3. Given a fresh recompute is run against a stored `cadena_total_gauss` for the same order, when compared, then the two totals are identical (invariant, testable via the divergence check mechanism).

### ADDED Requirements

- R35 `GET /ml-ventas-ops/orders/{order_id}` MUST return an ORDER-scoped response only: `monto_operacion`, the product list explaining it, `total_gauss`, `costo_mercaderia`, `cadena_total_gauss`, and `markup` MUST all refer to the same single requested order, never to any other order in its pack. This applies uniformly whether the order stands alone or is a member of a pack; a standalone order is already its own scope, so its response shape is unchanged.
- R36 A new endpoint `GET /ml-ventas-ops/packs/{pack_id}` MUST exist, returning a PACK-scoped response: `monto_operacion` for the whole pack, the product list aggregated across all member orders, `costo_mercaderia` summed across member orders, `total_gauss` summed across member orders, `markup` for the pack (per R37), and the list of member order ids so the UI can navigate to each member's order-scoped detail.
- R37 The pack `markup` MUST be computed as `total_gauss_pack / costo_mercaderia_pack`, following the same never-invent discipline as order-level markup: it MUST be `None` (never `0`, never fabricated) when `total_gauss_pack` is unknown, when `costo_mercaderia_pack` is unknown, when any member order lacks a stored metrics row, or when `costo_mercaderia_pack` is exactly zero. The sum of member costs and member Total Gauss values MUST be all-or-nothing, consistent with the existing pack-level `total_gauss` aggregation.
- R38 When an order-scoped response (R35) includes a Flex shipping cost line and that order shares a shipment with other pack members, the response MUST identify that shipping figure as prorated across the shipment's orders, so it is never presented as if it were the shipping cost of that order alone.
- R39 `GET /ml-ventas-ops/packs/{pack_id}` MUST return a not-found error when `pack_id` does not correspond to any known pack, and MUST NOT silently fall back to treating it as an order id.
- R40 A pack composed of exactly one order (a single-order "pack") MUST still be servable through `GET /ml-ventas-ops/packs/{pack_id}` with a response whose `monto_operacion`, product list, `costo_mercaderia`, `total_gauss`, and `markup` equal that single member's own values (the pack scope degenerates to the order scope without special-casing the shape).

### Scenarios (ADDED)
4. Given an order that is a member of a multi-order pack, when its order-scoped detail is requested via `GET /ml-ventas-ops/orders/{order_id}`, then `monto_operacion`, the product list, `total_gauss`, `costo_mercaderia`, `cadena_total_gauss`, and `markup` in that single response all describe only that order — none of them include figures from sibling orders in the pack.
5. Given a pack with three member orders each having a stored metrics row, when `GET /ml-ventas-ops/packs/{pack_id}` is requested, then the response returns `monto_operacion`, the aggregated product list, summed `costo_mercaderia`, summed `total_gauss`, the pack `markup`, and the three member order ids.
6. Given a pack where one member order has no stored metrics row, when the pack markup is computed, then the pack response returns `markup: None` (not a partial sum, not zero) because the member sum is all-or-nothing.
7. Given a pack whose summed `costo_mercaderia_pack` is exactly zero, when the pack markup is computed, then the response returns `markup: None` rather than dividing by zero or fabricating a value.
8. Given two orders in the same pack share one shipment, when either order's order-scoped detail is requested, then the Flex shipping line in that response is explicitly labeled as prorated across the shipment's orders.
9. Given a `pack_id` that does not exist, when `GET /ml-ventas-ops/packs/{pack_id}` is requested, then the endpoint returns a not-found error rather than an empty or fabricated pack response.
10. Given a pack containing exactly one order, when `GET /ml-ventas-ops/packs/{pack_id}` is requested for it, then the returned figures equal that single member's own order-scoped values.
