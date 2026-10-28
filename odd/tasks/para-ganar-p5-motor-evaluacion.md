# PARA GANAR P5 — motor de evaluación

Objective: Evaluate Periodicidad MLAs with existing suggestion/criteria logic; persist `pendiente` vs `sin_novedades` via `upsert_revision_estado`.
Branch: `feat/promo-local-refresh-mirror`
Delivery: ask-on-risk · tests: pytest unit

## Specs

- S1: Docs/module table: "Motor de evaluación (reusa sugerencia/criterios): ¿hay optimización? → Pendiente; si no → Sin novedades" (depends P2 + P4).
- S2: Docs/D24: "Persistido en `para_ganar_revision_mla`; lo escribe el motor (P5)".
- S3: User: "dale arranquemos" (start P5 after CI green on dismiss slice).
- S4: Assumption: P5 core = service; first callers evaluate **enabled Periodicidad** only. A1 (Consultar filtrados) and P6 (cron+refresh) call the same core later — not in this slice.
- S5: User (L4+L5) — Pendiente = diff de **competencia estado→estado** + oportunidad promo **actual**. Subcriteria:
  - **R1 Posición degradada:** rank/posición empeoró vs baseline de competencia anterior.
  - **R2 Perdimos el catálogo:** pasamos de ganar catálogo a perderlo (vs baseline).
  - **R3 Holgura al alza:** vs baseline de precios, podemos subir manteniendo posición.
  - **R4 Oportunidad promo (estado MLA):** no comparar inventarios de promos. Estado actual `(X precio, Y markup, Z posición)`. Para cada promo **disponible hoy**, proyectar `(X', Y', Z')` si se aplicara. Pendiente si algún candidato mejora **en conjunto o individualmente** X/Y/Z vs el actual (p.ej. más barato a igual/mejor margen, mejor margen, mejor posición). Sin rigor matemático formal en v1: heurística “mejor en al menos una dimensión sin empeorar de forma evidente las otras” — detallar en implementación. Incluye cofinanciación ML (mismo margen + precio menor).
  - **R5 catch-all:** fuera de v1.
- S6: User (L5): **primera evaluación → todos `pendiente`**; después estado vs estado. Missing snapshot → skip (null) hasta tener competencia (P6 refresh). No promo history store.
- S7: Assumption: catalog-only (D13); enabled Periodicidad `all|mlas|rules`; skip `enabled=false`.
- S8: Persist **competition baseline** (rank, price, suggestion_status, in_top / catalog-win, snap `fecha_consulta`) for R1–R3; R4 compares current MLA `(X,Y,Z)` vs projected `(X',Y',Z')` per available promo (no promo inventory baseline).
- S9: Delivery (agent choice, user OK): **phased inside P5** — Slice A R1–R3 + baseline + first-run; Slice B R4.

## Tasks

- T1 S1-S8 — map decision rule + surfaces — delegated explore — done (agent 6b70bad1)
- T2 S5-S9 — lock subcriteria + phasing — inline — done
- T3 S1-S4,S6-S8,R1-R3 — extract sugerencia + baseline + evaluar Periodicidad — inline — done
- T4 S1-S2 — unit tests + docs Slice A — inline — done
- T5 S5-R4 — oportunidad promo: proyectar (X',Y',Z') vs actual (X,Y,Z) — inline — done

## Log

- L1: User: "dale arranquemos"
- L2: Explore handoff: upsert exists; sugerencia assembly still in router `obtener_sugerencia_mla`; no periodicidad MLA expander; recommend service-only + extract; ask parent for optimization predicate / missing-snapshot / overwrite.
- L3: Asked user: Pendiente = solo perdiendo, o también holgura subir / promo aplicable? Waiting.
- L4: User: "los pendientes de revisar son aquellos que por cambios en el catalogo respecto del snapshot anterior, perdimos la posicion en la que estabamos, o pasamos a perder el catalogo, o por cambios en los precios de los competidores podemos subir el precio y mantener la posicion, o la aparicion de promociones que antes no estaban o el cambio de sus condiciones, por ejemplo estaba en premium y aparece una con cofinanciacion de mercadolibre, que nos da el mayor margen al mismo precio o mayor margen a menor precio, o una condicion favorable que amerite, si lo consideras necesario los explayamos como subcriterios bien definidos"
- L5: User: "las promos no hace falta fingerprintearla, porque es el estado de la competencia actual vs el anterior, la primera vez obviamente son todos por revisar, pero de ahi en mas es estado contra estado, las promociones que habia antes no importan, lo que importa es que no existan promociones en el ahora que sean superadoras de la activa en el momento de la consulta, por ejemplo incluso si no hay cambio de precio y por ende no hay cambio de posicion, si la activa es una premium y hay una smart con cofinanciacion, es suficiente como para ameritar revision, sin necesidad de saber que promociones estaban disponibles en el pasado, tiene sentido?"
- L6: User: "respecto de R4 te agrego algo , no solo que hay amejora en margen, si el margen se mantiene pero sale mas barato por la cofinanciacion de mercadolibre eso tambien es superador / esta bien r1 a r4 juntos o por separado como lo creas mas conveniente"
- L7: Agent: R4 includes same-margin cheaper via ML cofinancing; deliver Slice A R1–R3 then Slice B R4.
- L8: Slice A implemented: `compute_sugerencia_mla` extracted; `competition_baseline` JSONB + migration; `evaluar_*`; `POST /periodicidad/evaluar`. R4 not in this slice.
- L9: pytest evaluacion+cola+sugerencia → 27 passed.
- L10: User: "es que en realidad la promo per se no importa compararla, si no el estado actual del mla, si el precio es X y el markup es Y y la posicion es Z eso hay que compararla contra el nuevo X', Y' y Z' de cada promocion disponible, y las destacables o las que generan el cambio al estado pendiente de revisar son aquellas en las que X', Y' y/o Z' estan mejor en conjunto o individualmente que X, Y, Z, sin ser matematicamente riguroso, pero se entiende?"
- L11: User: "genial gracias" / "gracias, podemos arrancar el slice b"
- L12: Slice B: para_ganar_evaluacion_r4 + fetch_item_promotions_bulk; R4 on sin_novedades after baseline; pytest r4+evaluacion+sugerencia 21 passed
