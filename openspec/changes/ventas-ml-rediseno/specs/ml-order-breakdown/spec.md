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
