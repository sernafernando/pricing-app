# PARA GANAR — consultation jobs (A1 final / P6 / P7)

Objective: Shared async pipeline — refresh catalog competition then P5 — for manual (PM) and periodic triggers; revision queue stays per-MLA.
Branch: `feat/promo-local-refresh-mirror`
Delivery: ask-on-risk · source of truth: `docs/para-ganar.md` § Contrato A1/P6/P7

## Specs

- S1: User: button on filtered scope should create a group of publications to consult (takes time); feed same “por revisar” queue as periodic; P7 is a view of that queue.
- S2: User: several PMs enqueue independently; periodic may interleave; results group by owning PM for “mis consultas”; shared ML worker pool with fairness.
- S3: Agent proposal accepted: docs contract → job model+worker (P6 core) → rewire A1 button → P7 UI.
- S4: Interim `POST /evaluar-filtrados` (P5-only sync) remains motor until rewire; not the product button forever.

## Tasks

- T1 S1-S3 — lock contract in `docs/para-ganar.md` — inline — done
- T2 S1-S2 — job model + worker (refresh → P5) — pending
- T3 S1 — P6 periodic trigger using worker — pending
- T4 S1,S4 — rewire Consultar filtrados → enqueue — pending
- T5 S1 — P7 floating queue UI — pending (later)

## Log

- L1: User clarified A1 needs refresh+enqueue; accepted parallel PM jobs + shared ML pool.
- L2: User: "dale por favor arranquemos con el punto 1" (docs contract).
