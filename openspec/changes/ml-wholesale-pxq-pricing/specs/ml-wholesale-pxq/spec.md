# ml-wholesale-pxq Specification

## Purpose

Local storage, quantity-aware markup, and kill-switched ML write path for MercadoLibre B2B
wholesale price-by-quantity (PxQ) tiers. B2C PxQ is out of scope.

## Requirements

### Requirement: Tier CRUD constraints
A publication MUST have at most 5 PxQ tiers. Each tier MUST have `min_purchase_unit > 1` and a
unit price. Tiers are authored per publication (one MLA at a time); bulk authoring across MLAs is
out of scope.

#### Scenario: Sixth tier rejected
- GIVEN a publication already has 5 tiers
- WHEN a user attempts to create a 6th tier
- THEN the request is rejected and no tier is persisted

#### Scenario: Invalid minimum quantity rejected
- GIVEN a new tier with `min_purchase_unit = 1`
- WHEN the tier is submitted
- THEN it is rejected with a validation error

### Requirement: Array-replace write semantics
The system MUST diff the local tier table against the desired state to compute keep
(`{"id": ...}`), create (no id), delete (id omitted), and modify (delete old id + create new)
operations, then send the FULL resulting array to `POST /items/{ITEM_ID}/prices/standard/quantity`.

#### Scenario: Unmirrored live tier is preserved
- GIVEN a live ML tier with no matching local row
- WHEN the local mirror is refreshed and reconciled before the write
- THEN that live tier is included as "keep" and not silently dropped

#### Scenario: Modifying a tier's price
- GIVEN a local tier with an existing `ml_price_id`
- WHEN its unit price changes
- THEN the write replaces it via delete-old-id + create-new-without-id in the same array

### Requirement: Eligibility and kill-switch gating
The system MUST check `PXQ_WRITE_ENABLED` (default OFF) FIRST, then validate seller `business`
tag and item `standard_price_by_quantity` tag BEFORE any POST. Any failure MUST block the write.

#### Scenario: Kill-switch off blocks write
- GIVEN `PXQ_WRITE_ENABLED = False`
- WHEN a user triggers a PxQ sync
- THEN no request reaches MercadoLibre and the tier is not marked synchronized

#### Scenario: Ineligible seller or item blocks write
- GIVEN the seller lacks the `business` tag or the item lacks `standard_price_by_quantity`
- WHEN a sync is attempted with the kill-switch on
- THEN the write is refused before any POST is sent

### Requirement: Fail-closed shipping cost resolution
A tier's cost MUST use the manual `costo_envio_total` if present. If absent, the tier MUST be
marked `incompleto` and MUST NOT be written to ML. The system MUST NOT fall back to the per-unit
`costo_envio`.

#### Scenario: Missing shipping cost blocks sync
- GIVEN a tier with no `costo_envio_total`
- WHEN a sync is attempted
- THEN the tier is marked `incompleto` and excluded from the write, with no fallback to per-unit cost

#### Scenario: Manual cost enables sync
- GIVEN a tier with `costo_envio_total` set
- WHEN eligibility and kill-switch checks pass
- THEN the tier is eligible to be written

### Requirement: Quantity-aware markup
Markup calculation MUST call `calcular_comision_ml_total` / `calcular_limpio` with
`precio * cantidad` as price and the whole-shipment `costo_envio_total` as shipping. It MUST NOT
subtract one unit's shipping from an N-unit order.

#### Scenario: 30-unit tier markup
- GIVEN a tier of 30 units at a given unit price and the verified whole-shipment shipping cost
- WHEN clean markup is computed
- THEN the result matches the reference table value, not the naive per-unit-multiplied figure

### Requirement: No base-price side effects
A PxQ write MUST NOT modify `productos_pricing` and MUST NOT recompute `markup_rebate` or
`markup_oferta`, since those derive from `precio_lista_ml`, which PxQ never changes.

#### Scenario: Base pricing untouched after sync
- GIVEN a product with existing `markup_rebate` and `markup_oferta` values
- WHEN a PxQ tier is created, modified, or synced
- THEN those two columns and `precio_lista_ml` remain byte-identical

### Requirement: Dedicated PxQ permission with default grant
PxQ write actions MUST be gated by a permission distinct from the promotions-write permission.
On rollout, every user already holding promotions-write MUST be granted the new PxQ permission by
default.

#### Scenario: User without PxQ permission blocked
- GIVEN a user lacking the PxQ permission
- WHEN they attempt any PxQ write action
- THEN the request is rejected regardless of promotions-write status

#### Scenario: Existing promotions-write user retains access
- GIVEN a user who held promotions-write before rollout
- WHEN the PxQ permission is introduced
- THEN that user is granted the PxQ permission by default without manual action

### Requirement: Always-visible live ML read before write
Before any tier is created, modified, or deleted, the current live ML tiers MUST be fetched and
displayed to the user, regardless of whether divergence exists. The read MUST use a short-lived
DB session (not one pinned for the request lifetime).

#### Scenario: Live tiers shown on panel open
- GIVEN a user opens the PxQ panel for a publication
- WHEN the panel loads
- THEN live ML tiers are fetched and rendered above the tier input, with loading and error states surfaced

#### Scenario: Live read failure blocks editing
- GIVEN the live ML read fails
- WHEN the user attempts to edit a tier
- THEN editing is blocked and the error state is shown instead of stale or assumed data

### Requirement: Refuse write on local/live divergence
If live ML tiers differ from the local mirror, the system MUST surface the divergence and refuse
to write until the user resolves it. Local state MUST NOT silently win.

#### Scenario: Divergence detected
- GIVEN a live ML tier with a price differing from the local mirror
- WHEN the user attempts a sync
- THEN the write is refused and the divergence is displayed for manual resolution
