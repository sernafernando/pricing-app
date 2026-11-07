# Tacticals — alcance por tienda oficial

Objective: tacticals choose official-store / channel scope; consumos and markups respect it; cap toggle + live preview; store-aware markup UX.
Branch: `feat/tacticals-tienda` (from `upstream/main`)
Delivery: feature-branch-chain to `sernafernando/pricing-app:main`, each PR ≤400 add+del
Test runner: `pytest` (backend), `pnpm test` (frontend focused)

## Specs

- S1: Al crear un tactical se elige multi-select de tiendas **o** todas; fuente `ml_tiendas_oficiales` + sintéticos Por fuera y Tienda Nube.
- S2: Chip por `clave` expande todos los `store_id` (TP-Link).
- S3: Selector y toggle de cupo son independientes; toggle off = mismo tope contador por target; on = pool compartido sobre la selección.
- S4: Preview en vivo del tope por target (grupo/clave) en create/edit.
- S5: Caps distintos por tienda = dos tacticals (no UI de tope por store).
- S6: Históricos `todas_tiendas=true`; cambiar alcance en vivo = Anular + Renovar.
- S7: Sell-out / sell-in sobre ventas solo consumen si la operación matchea un target del tactical.
- S8: Markup store-aware en Publicaciones; Productos con mismos selectores de contexto; filtro/toggle de qué markups ver.

## Tasks

- T1 S1,S3,S6 — Schema + API contract (`todas_tiendas`, `tope_compartido`, `tactical_tiendas`) — route: inline — status: done — commits: `5a8806daa` (DB), `01d270cdd` (API); chain as two PRs ≤400
- T2 S1,S2,S3,S4 — Create/list UI selector + toggle + preview — route: inline — status: done — commit: `e3d9e3912`

- T3 S7 — Sell-out engine + tests — route: inline — status: pending
- T4 S7 — Sell-in engine + tests — route: inline — status: pending
- T5 S8 — Markup API store/canal-aware — route: inline — status: pending
- T6 S8 — Markup UI Productos + Publicaciones — route: inline — status: pending
- T7 — Ayuda + novedad — route: inline — status: pending

## Log

- L1: User seed + design closure 2026-11-07 (multi-select o todas; clave expand; Fuera/TN sintéticos; toggle cupo independiente; preview; markup filter/toggle; OK go slice 1).
- L2: Slice 1 implemented as two work-unit commits (DB then API). Router tests 16 passed; postgres migration/service tests skipped (DB unreachable). GGA hook skipped with --no-verify (Claude CLI missing, prior Gabe auth).
- L3: Slice 2 UI done (`e3d9e3912`): picker + toggle + preview; 50 FE unit tests passed.
