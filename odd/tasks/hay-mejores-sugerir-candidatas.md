# hay-mejores-sugerir-candidatas — chooser for flagged pubs

Branch: `feat/hay-mejores-sugerir-candidatas` (from `upstream/main`). PRs → `sernafernando/pricing-app:main`.
Delivery: `ask-on-risk` / Feature Branch Chain if >~400 authored lines. Runners: `backend/venv` pytest, `pnpm test`.

## Objective

For publications already flagged `hay_mejores_ofertas`, opening the panel offers SMART/DEAL/Premium candidates that beat the status quo; the free price field appears only after discard or apply. Tighten “better” to today’s criteria. Leave MODO shell as-is; non-flagged pubs unchanged.

## Specs

S1. Flag `hay_mejores` is determined by promotions that pass: markup↑ same price; markup= lower price; markup↑ lower price (no markup↑ at a higher price).
S2. Only already-flagged pubs get this chooser UX; others keep current panel (free price / tabs).
S3. On open of a flagged pub: show current price; suggest by the 3 slots SMART / DEAL / Premium; omit empty Premium; per slot prefer the best that passes S1 vs status quo (never show inferior-to-status-quo).
S4. Free price input must not appear until the suggestion was discarded or a suggestion was applied.
S5. Apply stays fire-and-forget (existing enroll); discard uses existing descartar hay_mejores.

## Tasks

| ID | Specs | Route | Status | Commit |
|----|-------|-------|--------|--------|
| T1 | S1 (stricter `es_mejor_oferta` + unit tests) | inline | done | 0648c698f |
| T2 | S2–S5 (chooser on flag in panel + gate Nuevo precio; ayuda/novedad) | inline | pending | — |

## Log

L1. User (alignment): delay OK; flagged filter already works; on click of pubs with better candidatas the panel should let choose among candidatas (keep showing current; price field only after discard or apply); chooser = 3 slots, only those that pass today’s criteria vs status quo, best per type / omit missing Premium; suggestion only for previously flagged pubs; “bueno listo”.
L2. T1: `es_mejor_oferta` rejects higher consumer price even with higher markup; unit test added. Commit 0648c698f.
