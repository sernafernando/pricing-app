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
  - **R4 Promo superadora ahora:** sin fingerprint histórico; candidato disponible hoy vs promo **activa**: (a) mayor margen; (b) mismo margen pero **más barato** por cofinanciación ML; (c) mayor margen a menor precio. Ej. activa Premium + SMART cofinanciada.
  - **R5 catch-all:** fuera de v1.
- S6: User (L5): **primera evaluación → todos `pendiente`**; después estado vs estado. Missing snapshot → skip (null) hasta tener competencia (P6 refresh). No promo history store.
- S7: Assumption: catalog-only (D13); enabled Periodicidad `all|mlas|rules`; skip `enabled=false`.
- S8: Persist **competition baseline** (rank, price, suggestion_status, in_top / catalog-win, snap `fecha_consulta`) for R1–R3; R4 uses current promos vs active only.
- S9: Delivery (agent choice, user OK): **phased inside P5** — Slice A R1–R3 + baseline + first-run; Slice B R4.

## Tasks

- T1 S1-S8 — map decision rule + surfaces — delegated explore — done (agent 6b70bad1)
- T2 S5-S9 — lock subcriteria + phasing — inline — done
- T3 S1-S4,S6-S8,R1-R3 — extract sugerencia + baseline + evaluar Periodicidad — inline — done
- T4 S1-S2 — unit tests + docs Slice A — inline — done
- T5 S5-R4 — promo superadora (margen / mismo margen más barato) — inline — pending

## Log

- L1: User: "dale arranquemos"
- L2: Explore handoff: upsert exists; sugerencia assembly still in router `obtener_sugerencia_mla`; no periodicidad MLA expander; recommend service-only + extract; ask parent for optimization predicate / missing-snapshot / overwrite.
- L3: Asked user: Pendiente = solo perdiendo, o también holgura subir / promo aplicable? Waiting.
- L4: User: "los pendientes de revisar son aquellos que por cambios en el catalogo respecto del snapshot anterior, perdimos la posicion en la que estabamos, o pasamos a perder el catalogo, o por cambios en los precios de los competidores podemos subir el precio y mantener la posicion, o la aparicion de promociones que antes no estaban o el cambio de sus condiciones, por ejemplo estaba en premium y aparece una con cofinanciacion de mercadolibre, que nos da el mayor margen al mismo precio o mayor margen a menor precio, o una condicion favorable que amerite, si lo consideras necesario los explayamos como subcriterios bien definidos"
- L5: User: "las promos no hace falta fingerprintearla, porque es el estado de la competencia actual vs el anterior, la primera vez obviamente son todos por revisar, pero de ahi en mas es estado contra estado, las promociones que habia antes no importan, lo que importa es que no existan promociones en el ahora que sean superadoras de la activa en el momento de la consulta, por ejemplo incluso si no hay cambio de precio y por ende no hay cambio de posicion, si la activa es una premium y hay una smart con cofinanciacion, es suficiente como para ameritar revision, sin necesidad de saber que promociones estaban disponibles en el pasado, tiene sentido?"
- L6: User: "respecto de R4 te agrego algo , no solo que hay amejora en margen, si el margen se mantiene pero sale mas barato por la cofinanciacion de mercadolibre eso tambien es superador / esta bien r1 a r4 juntos o por separado como lo creas mas conveniente"
- L7: Agent: R4 includes same-margin cheaper via ML cofinancing; deliver Slice A R1–R3 then Slice B R4.
- L8: Slice A implemented: `compute_sugerencia_mla` extracted; `competition_baseline` JSONB + migration `20261231_para_ganar_revision_baseline`; `evaluar_mla` / `evaluar_periodicidad`; `POST /api/para-ganar/periodicidad/evaluar`. First eval → `pendiente` + baseline; later R1–R3 vs baseline; skip on missing snapshot / refresh / no catalog; re-run overwrites estado. Tests: `backend/tests/unit/test_para_ganar_evaluacion.py`. R4 not in this slice.
- L9: pytest `tests/unit/test_para_ganar_evaluacion.py tests/unit/test_para_ganar_cola.py tests/unit/test_para_ganar_sugerencia.py` → 27 passed. Scope `mlas` must read `para_ganar_periodicidad_ean_mla` (not a stale `subscription.mlas` collection).
