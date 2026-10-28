# PARA GANAR P4 — Advisor revision states

Objective: Persist and expose Pendiente de revisión / Sin novedades on Advisor cola (badge + filter). No Perdiendo/Ganando. P5 writes states later.
Branch: `feat/promo-local-refresh-mirror`
Delivery: ask-on-risk · tests: pytest unit cola

## Specs

- S1: D24 / P4: "Cola: Pendiente de revisión / Sin novedades (badge + filtro). No Perdiendo/Ganando en cola"
- S2: User: "pendiente y novedades es del advisor, estamos de acuerdo?" + "dale arranquemos"
- S3: Persist per MLA; cola returns estado; filter chips on Advisor; empty until P5 evaluates

## Tasks

- T1 S1-S3 — model + migration + cola field/filter — inline — done
- T2 S1-S2 — FE chips + queue badges — inline — done
- T3 — tests docs commit — inline — done

## Log

- L1: User confirmed Advisor (not Periodicidad); "dale arranquemos"
- L2: Shipped table para_ganar_revision_mla + cola revision_estado + chips; pytest cola 13 pass
