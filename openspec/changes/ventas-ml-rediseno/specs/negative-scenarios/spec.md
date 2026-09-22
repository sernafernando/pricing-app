# Spec: Ventas ML redesign (delta spec, revision 1)

Source: proposal #2104 (rev 2) + explore #2103, with binding decisions Q1-Q3 resolved by the user. Spec describes WHAT must be true after the change; no implementation mechanics.

## Explicit negative scenarios (no invented data)

1. Given no product thumbnail image field exists in the ingested order-item payload, when the listing/panel render the Producto section, then they show a placeholder/category icon — never a fabricated or mismatched image URL.
2. Given no CUIT string is obtainable from the current payload shape (only an opaque billing-info id), when the panel renders Comprador, then it does NOT display a CUIT field.
3. Given no card brand/last-4 field exists anywhere in the captured payment payload, when the panel renders Pago, then it does NOT display masked card digits or a brand name.
4. Given no trend/target data source exists ("+12,4% vs mes anterior", "Objetivo: 25%"), when the KPI strip renders, then it does NOT display those or any other unsourced comparative/target figures.
5. Given no invoice-type/invoice-download data is wired to this screen, when the panel renders, then it does NOT show "Factura A emitida" or a download action.
6. Given the multi-account switcher, top nav, and notification bell have no backing product surface in this app, when the listing/panel render, then none of that chrome appears.

## Key Learnings

- Q1-Q3 close the gap the proposal explicitly flagged as blocking KPI/toggle spec detail: toggles now filter both table and KPI symmetrically via one shared filter builder (R10), removing the risk of table/KPI drift called out in the proposal's risk table.
- The extensibility instruction (reusable filter/aggregation contract for future sell-in/sell-out metrics) is captured as a requirement (R15) and a scenario, not a feature — spec intentionally does not describe that future screen, only that this contract must not close the door on it.
- Several explore-flagged (d)-classified data points (card brand/last-4, CUIT, invoice actions, trend/target percentages, multi-account nav) are captured as explicit negative "do not invent" scenarios so verify-phase has concrete assertions against scope creep, not just an absence.
- The `status=unresolved` → NULL contract (never zero, never silently omitted) is spread across three capabilities (stored-metrics, listing, panel) because each reader must independently honor it — a single central requirement would risk one reader falling back to a default.
- Design phase (running in parallel) owns: the recompute trigger enumeration, backfill/divergence mechanics, toggle/pack interaction algorithm details, and panel layout/CSS — this spec only fixes the observable behavior those must satisfy (e.g. R3, R6/R33, R10).
