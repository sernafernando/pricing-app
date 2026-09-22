# Spec: Ventas ML redesign (delta spec, revision 1)

Source: proposal #2104 (rev 2) + explore #2103, with binding decisions Q1-Q3 resolved by the user. Spec describes WHAT must be true after the change; no implementation mechanics.

## Capability: ml-sales-detail-panel

### Requirements
- R16 The detail view is a FIXED side panel next to the listing table (not a modal, not a focus-trapped overlay).
- R17 While the panel is open, table rows remain independently selectable and their text/data remain copyable (no overlay blocking pointer/selection events on the table).
- R18 The panel closes automatically when no row is selected (deselecting clears the panel; there is no explicit "no order" empty state requirement beyond closing/hiding).
- R19 Panel selection state is reflected in a way consistent with existing filter/selection URL conventions on this screen.
- R20 Keyboard and accessibility behavior appropriate to a non-modal panel replaces the prior modal's focus-trap: panel content is reachable via normal tab order, Escape clears the current selection (closes the panel) without trapping focus, and screen readers are informed of panel content changes without a modal role.
- R21 The panel shows: Producto, Comprador, Envío, Pago sections, the neto waterfall with IVA per rate (+ non-reconcile reasons when applicable), the Total Gauss chain + markup (sourced from the stored value per ml-order-stored-metrics), and actions "Ver en ML" and "Resincronizar".

### Scenarios
1. Given a row is selected, when the panel opens, then it renders beside the table (not over it) and the table remains fully interactive.
2. Given the panel is open and showing order A, when the user selects text in a table row for order B (without deselecting A), then that text is selectable/copyable and the panel does not intercept the selection.
3. Given the panel is open, when the user deselects the current row (e.g. clicks it again or clears selection), then the panel closes.
4. Given the panel is open, when the user presses Escape, then the selection clears and the panel closes without trapping keyboard focus anywhere else on the page.
5. Given the panel is open, when the user tabs through the page, then focus moves through table controls and panel controls in a single logical order, never trapped inside the panel.
6. Given an order has IVA lines that do not reconcile, when the panel renders the neto waterfall, then it displays the specific non-reconcile reasons (not a bare "does not reconcile" message) (per D5).
7. Given the stored Total Gauss for an order is `provisional`, when the panel renders the Total Gauss chain, then it visibly marks the total as provisional and the total shown equals the stored provisional value (ties to ml-order-stored-metrics R6).
8. Given the user clicks "Resincronizar" in the panel, when the resync completes, then the panel refreshes to show the updated stored values without requiring the user to reselect the row.
