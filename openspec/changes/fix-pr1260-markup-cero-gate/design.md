# Design: PR #1260 zero confirm + schema floor

## Approach

1. Modal: change gate predicate from `markup < 0` to `markup <= 0`; keep `gate: 'negative'` and CS-4 copy (Chicho: same pane).
2. Schema: `markup_objetivo: float = Field(..., ge=-100, allow_inf_nan=False)` with description noting floor; tests accept −100, reject −100.1.
3. PR body: replace `filtrosActivos` with `listarParams` in #1260 description.

## Tests

- Invert zero ≤50 test → requires MarkUp Negativo then write.
- Invert zero+>50 → stack non-positive then threshold.
- Schema: `ge=-100` boundaries.
