# Design: Controlados OC read-only exhibit

## Decisions

1. **Gate on `pedido.estado === 'controlado'`** inside `AccordionBodyConOc` only. Do not invent a second accordion component unless the JSX gets unreadable; a branch is enough.
2. **Display source:** `lineasErp` (unfiltered) when controlado; keep `lineas = lineasErp.filter(saldo !== 0)` for recibido / con_faltantes.
3. **Read-only table:** no checkbox column, no tanda column. Columns: Ítem, Depósito, Cant. pedida, Recibido prev., Saldo (display only). Mirror arribo caption “solo lectura”.
4. **Hide control chrome when controlado:** faltantes textarea, responsable picker, `ControlEvidenceFields`, action bar. Docs on the row header stays (existing).
5. **No backend change.** GET saldos already returns all lines for controlado.
6. **Tests** in `TabRecepcionDeposito.test.jsx` only. Focused vitest; no full suite on this WSL machine.

## Risks

| Risk | Mitigation |
|------|------------|
| Break faltantes hide | Keep existing filter + existing test |
| Operators try to re-control | Hide buttons; backend already 409 |
