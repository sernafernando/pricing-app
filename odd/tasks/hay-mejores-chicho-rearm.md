# hay-mejores Chicho rearm

Objective: honor Chicho review — no stacked Criterios PRs; fix blockers; restore perf invariant (no loosened N+1 test).
Branch: work on tip then reshape to 3 PRs. Delivery: ask-on-risk → 3 PRs to main.
Test runner: pytest (backend unit) + vitest unit for touched FE.

## Specs

- S1: "sin PRs apilados; Criterios en un solo PR; #2313 solo contra main; #2331 Full aparte contra main"
- S2: WhatsApp Chicho: no aflojar test perf; el cambio hace una consulta de más por publicación — arreglar eso, no el test
- S3: Chicho blockers from #2316–#2328 / #2331 comments (C1 front, C2 ya-ganando already in #2332, C6 incomplete, R-AUTO ambiguous, bulk Auto, tests, daemon→worker/pool)

## Tasks

- T1 S2: batch/prefetch get_criterios; restore `ten["SELECT"] == one["SELECT"]` — inline — pending
- T2 S1: reshape to 3 PRs (2313 | criterios unified | Full on main); close superseded stack — pending
- T3 S3: apply remaining Chicho blockers on unified Criterios (+ Full pool) — pending

## Log

- L1: User "go" + WhatsApp Chicho on loosened perf test (SELECT per MLA / get_criterios)
