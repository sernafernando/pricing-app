# Proposal: Generic Empresa two-line wrap

## Intent

Chicho review on #1348: `TabPedidosCompra` hardcodes `/^grupo\s+gauss$/i` with `<br>` and `.empresaCellGrupoGauss`. Other names stay `nowrap` / `overflow: visible` and spill onto **Proveedor** when longer or renamed.

## Scope

### In Scope

- One `.empresaCell` rule (locked CSS below); delete `.empresaCellGrupoGauss`
- Render `empresa_nombre` (fallback `#id`) as text — no regex, no `<br>`, no `data-wrap`
- Update the visual test so it proves generic 2-line clip, not a name branch
- Amend `pedidos-compra` Empresa requirement (drop Gauss/Pastoriza special case)

### Out of Scope

- Acciones 2×2 / how many simultaneous buttons
- Fecha pago `110px` literal asserts
- Backend, permissions, alerta factura docs
- Retuning `COLUMNS` widths
- Opening a new PR (follow-up commit on #1348 only)

## Capabilities

### New Capabilities

None

### Modified Capabilities

- `pedidos-compra`: Empresa wrap/clip is generic (any name, ≤2 centered lines, then clip). Amends archived “Grupo Gauss two lines / Pastoriza width / MUST NOT clip” requirement.

## Approach

Replace both empresa CSS classes with this single rule. JSX renders the name. Keep `COLUMNS.empresa` at `104px`.

```css
.empresaCell {
  display: block;
  text-align: center;
  white-space: normal;
  overflow-wrap: anywhere;
  line-height: 1.25;
  max-height: 2.5em;
  overflow: hidden;
}
```

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `frontend/src/components/compras/TabPedidosCompra.jsx` | Modified | Remove `isGrupoGauss`, `<br>`, `data-wrap` |
| `frontend/src/components/compras/TabPedidosCompra.module.css` | Modified | One `.empresaCell`; delete `.empresaCellGrupoGauss` |
| `frontend/src/test/visual/tabPedidosCompraFechaPago.visual.test.jsx` | Modified | Generic 2-line clip; drop `data-wrap` branch |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Long unbreakable token still overflows horizontally | Low | Locked `overflow-wrap: anywhere` + `overflow: hidden` |
| Visual test still encodes a name branch | Med | Shared computed-style asserts; long-name clip fixture |
| Two-line clip hides part of a legal name | Low | Accepted product lock (clip, no ellipsis) |

## Rollback Plan

Revert the three Pedidos files on `feat/compras-pedidos-layout-y-alerta-factura`. No schema.

## Dependencies

Open PR #1348 (`feat/compras-pedidos-layout-y-alerta-factura` → **main**). One follow-up commit; do not open a new PR.

## Success Criteria

- [ ] Every empresa name uses the same cell rule
- [ ] Two-word names wrap on the space; short names stay one line when they fit
- [ ] Excess text clips after two centered lines; no ellipsis; no spill onto Proveedor
- [ ] No company name hardcoded in JSX or CSS comments as a special case
- [ ] Visual test proves generic clip, not `data-wrap=grupo-gauss`
