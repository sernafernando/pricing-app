# para-ganar-top-engine — D12 rank board + Activo/Excluido

Branch: `feat/promo-local-refresh-mirror` (Draft PR #1796 → develop).
Delivery: ask-on-risk. Runner: backend pytest unit; frontend vitest unit.

## Specs

- S1: Seller dispositions are only **Activo** (`active`) and **Excluido** (`excluded`). Quote user: "si no sirven no tienen que estar" / "lo marca como excluido y el sistema no lo considera (como si no existiese) lo unico que se mantiene es que en la lista de seller aparece".
- S2: Excluded sellers stay on the catalog seller list so the PM can re-activate them. Quote: "aparece para volver a incorporarlo".
- S3: When any seller is excluded, show a discreet operator notice. Quote: "avisarle al operador/pm que hay sellers ocultos con un mensaje discreto cuando eso suceda".
- S4: TOP N = **price positions** (ties share a rank), not N sellers. Quote docs D12: "Two at #1 + three at #2 = top **2** positions, five sellers".
- S5: First Advisor slice = rank board (our price, our rank vs TOP N, positions table). No invented “precio PARA GANAR” / promo apply yet.
- S6: Ranking universe = competitors in **this MLA’s** snapshot with valid `price_ars` and **same_bucket** (listing_type + cuotas), minus excluded dispositions; include ourselves with snapshot `our_price` (fallback cola list price). Do not reuse a sibling MLA snapshot from the same catalog.

## Tasks

- T1 S1–S3 — dispositions collapse + notice — inline — done
- T2 S4–S6 — pure rank helper + GET sugerencia + tests — inline — done
- T3 S5 — Advisor UI + docs — inline — done

## Log

- L1: User authorized TOP engine; clarified excluded = out of ranking, stay on list, discreet notice; rejected multi-label dispositions (“si no sirven no tienen que estar”); “probemos a ver” on Activo/Excluido.
- L2: Implemented Activo/Excluido + D12 board endpoint + Advisor UI; tests green (7 unit).
- L3: User: 3-cuotas MLA was ranking against clásicas — fix same_bucket filter + snapshot must be this MLA.
- L4: User: #1 cola solo catálogo + check tradicionales; #2 6 cuotas “solos” vs varias ofertas ML — D13/D14 (normalize bare installments + synthesize our_bucket + default catalog_listing filter).
