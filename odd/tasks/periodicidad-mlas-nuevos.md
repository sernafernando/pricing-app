# Periodicidad MLAs nuevos (P3.3)

Objective: Notify/filter subscribed EANs whose explicit MLA list is missing active MLAs in scope; highlight those MLAs in detail; dismiss alerts without forcing subscribe.
Branch: `feat/promo-local-refresh-mirror`
Delivery: ask-on-risk · tests: pytest unit periodicidad

## Specs

- S1: User: "safeguard que cuando haya mlas nuevos para un ean que esta dentro de la lista de los periodicos avise" + "filtro de mlas nuevos"
- S2: Agent/user: mainly `scope_mode=mlas` (all already includes futures); badge + chip filter; detail highlight
- S3: Deferred from P3.2 decision — implement now as P3.3
- S4: User: "no tenemos que obligarlo a que los agregue, solo notificarlo" + "boton de descartar avisos por nuevos" (detalle EAN) + "boton general de descartar todos los avisos nuevos" (cerca de filtros)

## Tasks

- T1 S1-S2 — backend catalog flag + filter + MLA `es_nuevo` — inline — done
- T2 S1-S2 — FE chip + list/detail badges — inline — done
- T3 S1-S3 — tests docs commit notify — inline — done
- T4 S4 — tabla descartado + POST EAN/bulk + FE botones — inline — done (pytest 10)

## Log

- L1: User: "dale arranquemos p3.3"
- L2: Implemented notify/filter; pytest 9 pass
- L3: User: "es que no tenemos que obligarlo a que los agregue, solo notificarlo, pero esta bien podemos poner en el mismo sector del ean un boton de descartar avisos por nuevos, y de ultima un boton general de descartar todos los avisos nuevos, fuera del sector del ean, capaz en donde estan los filtros??"
- L4: Dismiss via para_ganar_periodicidad_ean_mla_descartado; POST EAN + bulk; FE buttons; local DDL :5433; pytest 10
