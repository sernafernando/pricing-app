# PARA GANAR A1 — Consultar filtrados

Objective: On-demand P5 evaluation for MLAs in the current Advisor scope filters (not only Periodicidad subscriptions).
Branch: `feat/promo-local-refresh-mirror`
Delivery: ask-on-risk · tests: pytest + vitest

## Specs

- S1: Docs: "Advisor **Consultar filtrados**: misma pipeline que el periódico, pero a demanda sobre el alcance del filtro (manual; lo no suscripto a Periodicidad)".
- S2: Docs: "from Advisor, run the evaluation pipeline on-demand for MLAs in the current filter (manual path for non–Periodicidad subscriptions). Button stub in toolbar until P5 exists."
- S3: User: "bueno sigamos entonces por favor" (start A1 after P5).
- S4: Assumption: reuse P5 core (`evaluar_mlas` / R1–R4); list MLAs via existing cola alcance (`_list_scope_mlas` + same query params as aplicar-masivo). Does **not** include `revision_estado` chip.
- S5: Assumption: permission `productos.editar_precios` (same as `POST /periodicidad/evaluar`). Empty scope → 422 like mass apply.
- S6: FE: enable stub button; call new endpoint with `scopeQueryParams`; show counts; reload cola.

## Tasks

- T1 S1-S5 — extract `evaluar_mlas` + `POST /para-ganar/evaluar-filtrados` — inline — done
- T2 S2,S6 — wire Advisor button + feedback — inline — done
- T3 S1-S6 — tests + docs — inline — done

## Log

- L1: User: "bueno sigamos entonces por favor"
- L2: Implemented `evaluar_mlas` shared core; `POST /para-ganar/evaluar-filtrados`; Advisor button + counts; docs/tests.
