# Spec: Ventas ML redesign (delta spec, revision 1)

Source: proposal #2104 (rev 2) + explore #2103, with binding decisions Q1-Q3 resolved by the user. Spec describes WHAT must be true after the change; no implementation mechanics.

## Capability: ml-order-resync

### Requirements
- R22 A per-order resync action re-fetches the order (and dependent payment/shipment data) via the existing ingestion path and is gated by permission.
- R23 A successful resync triggers a recompute of the order's stored metrics record (ties to ml-order-stored-metrics R3).
- R24 Resync failures are surfaced to the user with an explicit error state; no partial/silent success.

### Scenarios
1. Given a user without the resync permission, when they attempt to trigger resync, then the action is rejected with a clear permission-denied response and no data changes.
2. Given a user with permission triggers resync on order X, when ingestion succeeds, then order X's fields (payment, shipment, stored metrics) reflect the freshly fetched data.
3. Given ingestion fails (e.g. ML API error) during a resync, when the failure occurs, then the user sees an explicit error state and the order's previously stored data is left unchanged (no partial overwrite).
4. Given a resync is triggered repeatedly in quick succession on the same order, when the second request is made, then the system does not corrupt state (defined, safe behavior — e.g. reject/no-op/queue, not a race that produces inconsistent stored metrics).
