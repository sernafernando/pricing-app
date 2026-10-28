# Periodicidad MLAs nuevos (P3.3)

Objective: Notify/filter subscribed EANs whose explicit MLA list is missing active MLAs in scope; highlight those MLAs in detail.
Branch: `feat/promo-local-refresh-mirror`
Delivery: ask-on-risk · tests: pytest unit periodicidad

## Specs

- S1: User: "safeguard que cuando haya mlas nuevos para un ean que esta dentro de la lista de los periodicos avise" + "filtro de mlas nuevos"
- S2: Agent/user: mainly `scope_mode=mlas` (all already includes futures); badge + chip filter; detail highlight
- S3: Deferred from P3.2 decision — implement now as P3.3

## Tasks

- T1 S1-S2 — backend catalog flag + filter + MLA `es_nuevo` — inline — done
- T2 S1-S2 — FE chip + list/detail badges — inline — done
- T3 — tests docs commit — inline — in progress

## Log

- L1: User: "dale arranquemos p3.3"
- L2: Implemented; pytest 9 pass
