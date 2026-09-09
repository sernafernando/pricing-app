# Proposal: Acciones masivas markup 0 and negative

## Intent

Operators need Acciones masivas for break-even (`markup_objetivo` 0) and loss-leader (negative) markups. Blockers are self-imposed: modal `markup <= 0` + onBlur `5.0`; schema `gt=0`; test expects 0 to fail. Calculator already supports negative. Chicho: lift gates.

## Scope

### In Scope
- Allow `markup_objetivo` **0** and **negative** (modal + backend schema).
- **0**: no extra confirm beyond existing >50 Tesla gate.
- **Negative**: Tesla in-modal confirm aligned with Productos CS-4 (“MarkUp Negativo” / “Guardar de todas formas”); never `window.confirm`.
- Keep >50 confirmation (independent of sign).
- Invert/extend schema + modal tests; ship on `fix/markup-masivo-02-wiring-desync` with PR2 (#1245 merged; #1244 stays closed).

### Out of Scope
- Individual-row price edit (CS-4 reference only).
- `markup_adicional` cuotas range (0–100 stays).
- Pricing formula rewrite; reopening #1244.

## Capabilities

> No Acciones masivas spec in `openspec/specs/`. Sibling `productos-acciones-masivas-scope` (write-set / >50) is not rewritten.

### New Capabilities
- `productos-acciones-masivas-markup-objetivo`: accept 0 and negative; NaN/empty invalid; 0 skips extra confirm; negative requires Tesla CS-4 confirm; >50 gate stacks independently.

### Modified Capabilities
- None

## Approach

Drop `gt=0` and frontend `<= 0` reject. onBlur may default non-numeric to `5.0`; must not reset 0 or negative. Reuse the modal Tesla `confirmacion` pane for negative markup; do not change `Productos.jsx`. Stack: negative pane first, then >50 if needed; Volver/Cancelar aborts. Chunking ≤100 and calculator unchanged.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `AplicarMarkupMasivoModal.jsx` | Modified | Allow 0/negative; Tesla negative confirm; onBlur |
| `AplicarMarkupMasivoModal.test.jsx` | Modified | 0, negative, NaN, stacking |
| `backend/.../pricing.py` | Modified | Drop `gt=0` on `AplicarMarkupMasivoRequest` |
| `test_acciones_masivas_schemas.py` | Modified | Invert positive-only; add 0/negative |
| `Productos.jsx` | Unchanged | CS-4 pattern reference only |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Dual confirm (>50 + negative) | Med | Independent gates; sequential Tesla panes |
| Extreme negatives / odd prices | Low | Goalseek already handles negative |
| PR2 rebase vs desync-guard | Med | Same branch; small validation/UX diff |

## Rollback Plan

Restore `gt=0`, frontend `<= 0` reject + onBlur `5.0`, and the positive-only schema test. No migrations. Applied lots need data repair, not code rollback.

## Dependencies

- Locked decisions (Chicho; Engram `markup-masivo-cero-negativo`).
- PR2 `fix/markup-masivo-02-wiring-desync`; #1245 merged; #1244 closed.
- CS-4 in `Productos.jsx` as UX reference only.

## Success Criteria

- [ ] Modal + API accept 0 and negative; NaN still rejected.
- [ ] 0 does not show negative confirm; >50 still required when count > 50.
- [ ] Negative Tesla in-modal confirm (CS-4 copy); no `window.confirm`.
- [ ] Schema test not positive-only; frontend covers 0/negative/stack.
