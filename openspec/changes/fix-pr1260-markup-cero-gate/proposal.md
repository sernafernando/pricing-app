# Proposal: PR #1260 Chicho review — zero confirm + schema floor

## Intent

Address pre-merge review on [#1260](https://github.com/sernafernando/pricing-app/pull/1260): markup `0` must use the same Tesla confirm as negative (`markup <= 0`); schema must expose an explicit floor `ge=-100`; PR body must say `listarParams` not `filtrosActivos`.

## Locked decisions (Chicho review)

- Gate condition: `markup <= 0` (same pane/copy as negative).
- Schema: `Field(..., ge=-100, allow_inf_nan=False)`.
- Docs: PR body wiring prop name = `listarParams`.

## Scope

- Modal confirm gate + tests
- `AplicarMarkupMasivoRequest` + schema unit tests
- PR #1260 body text

## Out of scope

- Goalseek clamp implementation
- Cuotas / calculator / resolve helper
