# Exploration: Acciones masivas 0 / negative markup

Grounding for `feat-markup-masivo-cero-negativo`. Product decisions locked (Chicho). No production edits in this phase.

## Current blockers (self-imposed)

| Layer | File | Behavior |
|-------|------|----------|
| Frontend | `AplicarMarkupMasivoModal.jsx` | `handleAplicar`: `isNaN(markup) \|\| markup <= 0` → toast “mayor a 0”. `onBlur`: `isNaN(v) \|\| v <= 0` → `'5.0'`. |
| Backend | `pricing.py` `AplicarMarkupMasivoRequest` | `markup_objetivo: float = Field(..., gt=0)`. |
| Test | `test_acciones_masivas_schemas.py` | `test_aplicar_markup_masivo_requiere_markup_positivo` expects 0 → `ValidationError`. |

Modal tests (`AplicarMarkupMasivoModal.test.jsx`) cover filter scope / >50 Tesla `confirmacion`; they do **not** cover 0/negative. Default field is `'5.0'`.

## Already allowed elsewhere

- `precio_por_markup_goalseek` documents “Funciona con markups positivos y negativos”; negative uses a bounded search (`costo * 0.5` … `costo * 5`).
- `calcular_precio_producto(..., markup_objetivo: float = 0)` default is 0.
- Single-item pricing request schemas use unbounded `markup_objetivo: float`.
- Productos inline edit CS-4: Tesla overlay “MarkUp Negativo” + “Guardar de todas formas”; holds write until confirm (`Productos.test.jsx`).

## Locked rules

- **0**: allowed; no extra confirm beyond existing >50.
- **Negative**: allowed; Tesla in-modal confirm (CS-4 copy/actions). Not `window.confirm`.
- Keep >50 Tesla confirm. Stack independently (order: design).
- Ship with PR2 desync-guard on `fix/markup-masivo-02-wiring-desync`, rebased to `main`. #1245 merged; #1244 closed.

## Out of scope (do not reopen)

Individual-row edit implementation, cuotas `markup_adicional` 0–100, formula rewrite, #1244 tracker chain.
