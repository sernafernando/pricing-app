# Design: Acciones masivas markup 0 and negative

## Technical Approach

Lift the three self-imposed gates (`markup <= 0` + onBlur reset, `Field(gt=0)`, schema test expecting 0 to fail). Calculator already goalseeks negative. Spec: `productos-acciones-masivas-markup-objetivo`. Confirm stays **client-only** (same as today’s >50). Ship on `fix/markup-masivo-02-wiring-desync` after rebase onto `main`; do not regress PR2 resolve/desync.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|----------|---------|----------|--------|
| Confirm stacking | Negative then >50 vs >50 then negative vs parallel | Dual only when both fire; order is product-recommended, not Chicho-locked | **Negative pane first, then >50 if count > 50** |
| Volver / Escape on stacked >50 | Wizard-back to negative vs abort to form | Wizard needs a confirm stack; current >50 Volver already returns to form | **Abort to form** (clear `confirmacion`); input value stays |
| Negative UX vehicle | Nested Productos overlay vs reuse modal Tesla pane vs `window.confirm` | Spec: CS-4 copy, never `window.confirm`; Productos overlay is out of scope | **Reuse existing in-modal `confirmacion` pane** with `gate` discriminator |
| Finite numbers | Drop `gt=0` only vs also reject inf/NaN | Spec requires finite; Pydantic `float` accepts inf | **`Field(..., allow_inf_nan=False)`**; frontend `Number.isFinite` |
| Server confirm flag | Require `confirmed_negative` vs UI-only | >50 is already UI-only; extra field is new contract | **UI-only**; API accepts finite 0/negative once schema allows |
| PR2 files | Touch resolve/desync vs leave | This change is validation/UX only | **Leave** `resolveFilteredItemIds.js` and `useProductosData.js` |

### Stacking rationale (locked)

Negative is the unusual economic choice. Show it first while attention is on Aplicar, then the familiar volume gate. >50-first trains click-through, then a surprise MarkUp Negativo. Zero never uses the negative pane; 0+>50 is a single volume pane. Gates after successful resolve (need count). Fail-closed mismatch/empty → toast, no panes.

```
form → validate finite markup → resolve IDs
  → markup < 0?  confirmacion.gate='negative'
       → proceed → count>50? gate='threshold' → Confirmar → write
       → proceed → count≤50 → write
  → markup ≥ 0 && count>50? gate='threshold' → write
  → else write
Volver / Escape / X: clear confirmacion; no write; field unchanged
```

## Data Flow

```
AplicarMarkupMasivoModal
  parseFloat → Number.isFinite? else toast, no write
  resolveFilteredItemIds (unchanged PR2 helper)
       │
       ├─ markup < 0 ──► Tesla pane "MarkUp Negativo" / "Guardar de todas formas"
       │                      │ proceed
       │                      ▼
       └─ count > 50 ──► Tesla pane "Confirmar acciones masivas" / "Confirmar"
                              │
                              ▼
                    ejecutarAplicacion → POST /precios/aplicar-markup-masivo
                    (schema: finite float, including 0 and negative)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/components/AplicarMarkupMasivoModal.jsx` | Modify | `Number.isFinite`; allow 0/negative; onBlur only resets non-finite to `5.0`; `confirmacion.gate`; no `window.confirm` |
| `frontend/src/components/AplicarMarkupMasivoModal.module.css` | Modify | Optional danger title token on negative pane; reuse `.confirmacion`; no emoji; no Productos overlay clone |
| `frontend/src/components/AplicarMarkupMasivoModal.test.jsx` | Modify | 0 no negative pane; blur preserve; NaN reject; CS-4 copy; stack negative then >50; 0+>50 only volume |
| `backend/app/api/endpoints/pricing.py` | Modify | `AplicarMarkupMasivoRequest.markup_objetivo`: drop `gt=0`, set `allow_inf_nan=False` |
| `backend/tests/unit/test_acciones_masivas_schemas.py` | Modify | Invert positive-only; accept 0 and negative; reject inf/NaN |
| `frontend/src/pages/Productos.jsx` | Unchanged | CS-4 copy/actions reference only |
| `frontend/src/components/resolveFilteredItemIds.js` | Unchanged | PR2 desync/resolve guard |
| `frontend/src/hooks/useProductosData.js` | Unchanged | PR2 request-generation guard |
| `backend/app/services/pricing_calculator.py` | Unchanged | Already supports negative |

## Interfaces / Contracts

```python
class AplicarMarkupMasivoRequest(BaseModel):
    markup_objetivo: float = Field(..., allow_inf_nan=False)  # 0 and negative OK
    # item_ids min_length=1, max_length=100 unchanged
```

```js
// confirmacion: null | { itemIds, markup, configBodyBase, gate: 'negative' | 'threshold' }
// apply reject: !Number.isFinite(markup) → toast "Ingresá un markup válido" (drop "mayor a 0")
// negative CTA: "Guardar de todas formas"; volume CTA: "Confirmar"; both Volver
```

Negative pane title **MarkUp Negativo**; body may say prices sit below cost + commissions (CS-4 sense, pluralized). No ⚠️ emoji (`frontend/AGENTS.md`).

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit (schema) | 0, -5 succeed; inf/NaN fail; item_ids bounds unchanged | pytest `test_acciones_masivas_schemas.py` |
| Unit (modal) | 0 ≤50 no negative pane; NaN toast; blur keeps 0/−3; negative CS-4 then write; Volver aborts; negative+>51 stacks; 0+>51 volume only; no `window.confirm` | vitest + existing listar mocks |
| Regression | PR2 >50, chunk ≤100, fail-closed mismatch/empty still pass | keep current modal tests |
| E2E | Optional operator smoke after rebase | manual |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No DB migration. Land on PR2 branch (`fix/markup-masivo-02-wiring-desync`) rebased onto `main`. Rollback: restore `gt=0`, `<= 0` reject + onBlur `5.0`, and the positive-only schema test. Applied lots need data repair, not code rollback.

## Open Questions

- None. Stacking order and Volver-abort-to-form are locked here.
