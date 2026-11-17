# hay-mejores-criterios

Objective: Criterios de aplicación + auditoría lean + Auto-aplicación on top of canonical hay_mejores (A).  
Branch: `feat/hay-mejores-criterios-aplicacion` (stack to `main`, slices ≤400).  
Delivery: stacked PRs to `main` per PLAN P0–P5.  
Tests: pytest (backend) + vitest where FE; ruff + `npm run lint` before each PR.

## Specs

S1. Keep canonical `es_mejor_oferta` (A); Criterios add limitations / alternate paths — quote owner: living design in `docs/design/pubs-ml-competencia-hay-mejores/CRITERIOS-APLICACION.md` + `PLAN.md`.

S2. UI: button **Criterios de aplicación** beside **Ver competencia**; same col2; mutual exclusion.

S3. C1: markup band uses same markup as status-quo comparison; when active, markup must sit inside band.

S4. C2: catalog-win path; toggle ON = markup > 0 only; OFF = allow negative.

S5. Competitor **table** is sole source of who counts (checked default; PM unchecks); C2/C6/R-AUTO use checked set.

S6. C6: same flag, different lead; gap ≥ configurable (default 5000); distancia configurable (default 100); dual UI candidatas above monopolio.

S7. R-AUTO: enroll same suggestion instead of flagging; ON shows text under toggle; fail → suggestion + “Autoapply falló” + reason; audit auto vs manual.

S8. `hay_mejores_excluido` → fully out of circuit.

S9. Non-catalog ignored unless associated to catalog MLA (treat as catalog).

S10. Criteria changes apply to **new runs only**; bulk may opt-in discard open suggestions (default No); skip Auto-fail suggestions.

S11. Lean audit on flag transition + enroll enrich + Auto toggle log (no per-tick audit).

S12. Persistence: `ml_hay_mejores_criterios` per item_id upsert.

## Tasks

| ID | Specs | Route | Status | Commit / PR |
| --- | --- | --- | --- | --- |
| T0 | S1 | inline | done | docs PR #2309 |
| T1a | S3,S12 | inline | done | P0a #16 · P0b #17 · P0c #18 |
| T1b | S2 | inline | done | P0d UI #19 |
| T2 | S11 | inline | done | P1 audit #20 |
| T3 | S4,S5 | inline | done | P2a #21 · P2b #22 |
| T4 | S6 | inline | done | P3a #23 · P3b #24 |
| T5 | S7,S8 | inline | done | P4a #25 · P4b #26 |
| T6 | S9,S10 | inline | in progress | P5a #27 · P5b bulk UI |

## Log

L1. User: continue criterios stack without waiting for #2308 merge; all Pricing PR rules (≤400, ruff/lint).

L2. Persistence decision: `ml_hay_mejores_criterios` (not offset_grupo_filtros).

L3. 2026-11-17: P0d UI — Guardian blocked hand-styled `.field input`; compose `forms-tesla` `.input`/`.inputSm` + `.field`/`.label`. Stack stays on GabeADemarco only.

L4. 2026-11-17: P1 — `ml_hay_mejores_audit` for flag_transition + auto_toggle; enroll enrich via `ml_write_log.payload` (`auto_aplicacion`, `hay_mejores_flag_snapshot`).

L5. 2026-11-17: Owner — smoke al final de todo el stack; seguir abriendo PRs personales. P2 split: P2a motor C2, P2b checkboxes col2.

L6. 2026-11-17: P3a — `evaluar_monopolio_c6` + synthetic fingerprint `c6:{precio_objetivo}`; `solo_via_promo` skips C6-only flag.

L7. 2026-11-17: P4a — R-AUTO enroll-instead-of-flag (`pick_mejor_candidata_auto` / `resolve_auto_enroll_target` / `_try_auto_enroll`); fail → re-flag + `Autoapply falló` in audit; C6 never auto-enrolls. Enroll on `after_commit` (ADR-5).

L8. 2026-11-17: P4b — `auto_fail_message` on GET promociones/item when flag on + latest audit auto_fail; banner in MejoresCandidatasBlock.

L9. 2026-11-17: P5a — POST `/hay-mejores-criterios-bulk` (≤20) + optional discard skipping Auto-fail; `alcance=bulk` on auto_toggle.

L10. 2026-11-17: P5b — view resolver criterios-item-ids + BulkCriteriosAplicacion in Acciones masivas; ayuda + novedad.
