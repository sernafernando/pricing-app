# Design: Recepción en Dos Pasos — `recibido` (llegó) + `controlado` (chequeado)

**Change:** `compras-recepcion-estado-controlado` · **Phase:** design · **Store:** hybrid

## Technical Approach

Convert the single-act reception into a state-gated two-step machine reusing the existing
service/endpoints/permission/ingresos table. The current terminal `recibido` is renamed to
`controlado`; a new intermediate `recibido` (arrived, not controlled) is inserted before it.
The transition is **derived from the pedido's CURRENT `estado`** plus a minimal flag — no new
endpoints, no new permission, no new table. State machine (LOCKED):

```
pagado        --Recibido----> recibido      (arrived, not controlled)
recibido      --Controlado--> controlado    (terminal)
recibido      --Faltantes---> con_faltantes
con_faltantes --Controlado--> controlado
```

## Architecture Decisions

### D-SINOC (BLOCKING) — how SIN-OC distinguishes ARRIVAL from CONTROL

| Option | Tradeoff | Verdict |
|--------|----------|---------|
| A. Derive target from current `estado` + reuse `completo:bool` for the control step only | Zero new fields; backward-compatible body; arrival is unambiguous (only valid from `pagado`); `completo` keeps its existing meaning at the control step | **CHOSEN** |
| B. Add explicit `accion` enum to body | Most explicit, but expands API surface and forces FE to send redundant info the estado already implies | Rejected — redundant |
| C. Reinterpret `completo:bool` globally (completo→controlado) | Skips the intermediate `recibido` entirely for SIN-OC; breaks the two-step requirement | Rejected — violates spec |

**Choice (Option A):** The endpoint interprets the action from `pedido.estado`. `completo:bool`
is **only consumed at the control step** to choose `controlado` vs `con_faltantes`. From `pagado`
the call is ARRIVAL → always `recibido` (the `completo` flag is ignored/irrelevant). The FE keeps
gating which call it sends; `observaciones-required-when-not-completo` validation is unchanged but
only relevant on the control step.

**SIN-OC truth table** (`POST /recepcion/confirmar-pedido`, body `{completo, observaciones?}`):

| current `estado` | payload | new `estado` | event | notes |
|---|---|---|---|---|
| `pagado` | any (`completo` ignored) | `recibido` | `recepcion_arribo` | ARRIVAL; sentinel row written |
| `recibido` | `completo=true` | `controlado` | `recepcion_registrada` | CONTROL OK |
| `recibido` | `completo=false` (+obs) | `con_faltantes` | `recepcion_con_faltantes` | CONTROL with shortages |
| `con_faltantes` | `completo=true` | `controlado` | `recepcion_registrada` | shortage resolved |
| `con_faltantes` | `completo=false` (+obs) | `con_faltantes` | `recepcion_con_faltantes` | still missing (stays) |
| `controlado` | any | — | — | **409 terminal** |
| other | any | — | — | 409 not receptive |

### D-CONOC — relationship between "Recibido" button and `pedido_compra_ingresos`

**Choice:** ARRIVAL is a **state-only** transition (no per-line ingresos). CONTROL is the step that
validates saldos via `registrar_ingresos`. Two distinct endpoints already exist and map cleanly:

- ARRIVAL (`pagado→recibido`): handled by `confirmar_pedido_sin_oc`-style state-only logic. For
  CON-OC we add a lightweight arrival path that flips state WITHOUT writing line ingresos (writes a
  sentinel-free state change + arrival event). It does NOT touch `registrar_ingresos`.
- CONTROL (`recibido→controlado`/`con_faltantes`): `POST /recepcion/ingresos` →
  `registrar_ingresos` → `recalcular_estado`. All-zero saldo → `controlado`; otherwise
  `con_faltantes`. `con_faltantes` remains receptive so a second batch can reach `controlado`.

Rationale: arrival is a logistics fact (camion bajó), independent of counting; forcing ingresos at
arrival would block the early visibility the change exists to provide. Saldo validation belongs to
control. ARRIVAL for CON-OC is triggered by the same `confirmar-pedido` endpoint (state-only),
keeping one arrival entry point for both paths; CONTROL for CON-OC stays on `/ingresos`.

**CON-OC trigger map:** `pagado` → "Recibido" button → `POST /confirmar-pedido` (state-only
arrival). `recibido`/`con_faltantes` → control UI (saldos table) → `POST /ingresos`.

### State guard + `_ESTADOS_RECEPTIVOS`

**Choice:** `_ESTADOS_RECEPTIVOS = {"pagado", "recibido", "con_faltantes"}`. The terminal guard in
`_validar_estado_receptivo` inverts: it now rejects **`controlado`** (was `recibido`) with the
distinct 409 "Pedido already controlled". `recibido` becomes receptive. Allowed transition table:

| from | action | to |
|---|---|---|
| `pagado` | arrival | `recibido` |
| `recibido` | control complete | `controlado` |
| `recibido` | control w/ shortages | `con_faltantes` |
| `con_faltantes` | resolved | `controlado` |
| `controlado` | * | 409 |

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/alembic/versions/20260624_recepcion_estado_controlado.py` | Create | UPDATE then constraint swap (see Migration) |
| `backend/app/models/pedido_compra.py` L144-148 | Modify | Add `controlado` to CheckConstraint literal |
| `backend/app/schemas/pedido_compra.py` L19-29 | Modify | Add `"controlado"` to `ESTADOS_PEDIDO` |
| `backend/app/services/recepcion_service.py` L50 | Modify | `_ESTADOS_RECEPTIVOS` += `recibido` |
| `…recepcion_service.py` L58-74 | Modify | Terminal guard rejects `controlado`, not `recibido` |
| `…recepcion_service.py` L199-215 | Modify | `recalcular_estado`: all-zero → `controlado` (was `recibido`); else `con_faltantes` |
| `…recepcion_service.py` L336 | Modify | Event branch: `controlado` triggers `recepcion_registrada` |
| `…recepcion_service.py` L399-461 | Modify | `confirmar_pedido_sin_oc`: derive target from `estado` per D-SINOC truth table; add arrival branch (`pagado→recibido`, event `recepcion_arribo`) |
| `…recepcion_service.py` (new) | Create | `confirmar_arribo_con_oc` helper (state-only `pagado→recibido` for CON-OC) OR fold arrival into shared `_transicionar` |
| `backend/app/routers/administracion_compras.py` L4917 | Modify | Saldo-visibility set += `controlado`? NO — `controlado` is terminal, keep `{pagado, recibido, con_faltantes}` (drop nothing; `recibido` already present) |
| `…administracion_compras.py` L4959+ | Modify | `confirmar-pedido` now routes arrival vs control by estado for BOTH paths |
| `backend/app/services/recepcion_service.py` get_eventos L485 | Modify | Add `recepcion_arribo` to event-type filter |
| `frontend/.../TabRecepcionDeposito.jsx` L18-22 | Modify | 4 FILTER_TABS + `?estado=` mapping |
| `…TabRecepcionDeposito.jsx` L24-35,313,346,386 | Modify | Button gating by estado (both bodies) + badge case + success msgs |
| `frontend/.../_shared/EstadoBadge.jsx` L36-48 | Modify | `recibido`→`parcial`/ámbar; add `controlado`→`pagado`/verde |
| `backend/tests/integration/test_recepcion_deposito_endpoints.py` | Modify | Rename + INVERT + new tests (see Testing) |

## Interfaces / Contracts

No schema field changes. `ConfirmarPedidoRequest{completo, observaciones?}` unchanged — semantics
clarified per D-SINOC. New event type literal: `"recepcion_arribo"`. `estado_nuevo` response now
can return `recibido` (arrival), `controlado`, or `con_faltantes`.

## Migration / Rollout

Filename `20260624_recepcion_estado_controlado.py`, `down_revision = "20260623_permiso_reescribir_lh"`.

**upgrade()** — ORDERED:
1. `UPDATE pedidos_compra SET estado='controlado' WHERE estado='recibido';` (BEFORE constraint swap)
2. `ALTER TABLE pedidos_compra DROP CONSTRAINT IF EXISTS ck_pedidos_compra_estado;`
3. `ADD CONSTRAINT … CHECK (estado IN (…,'pagado','recibido','con_faltantes','controlado'));`

**downgrade()** — constraint-only revert to the 9-state set (drops `controlado`). Data is **one-way**:
downgrade does NOT (cannot) reconstruct which rows were old-`recibido`; documented in the docstring.
Rows left as `controlado` would violate the reverted constraint, so downgrade is best-effort and the
docstring must flag manual data handling.

## Testing Strategy (Strict TDD — write/adjust failing tests first)

| Group | Action | Examples |
|---|---|---|
| Migration state tests | RENAME + ADD | `test_migration_new_states_accepted` += `controlado` |
| `recalcular_estado` | **INVERT** | `…todos_cero_da_recibido` → asserts `controlado` |
| Terminal guard | **INVERT** | `test_validar_estado_receptivo_rechaza_recibido` → `…rechaza_controlado`; `recibido` now ACCEPTED |
| `…rechaza_ingreso_409` | **INVERT** | `test_state_recibido_rechaza_ingreso_409` → `…controlado_rechaza…` |
| CON-OC complete batch | INVERT estado_nuevo | `…complete_batch_da_recibido` → `controlado`; `test_ingresos_201_complete` → `controlado` |
| SIN-OC | INVERT/RENAME | `…completo_true_da_recibido` → control step asserts `controlado` |
| NEW | ADD | `pagado→recibido` arrival (SIN-OC & CON-OC, state-only, no ingresos); `recibido→controlado`; `recibido→con_faltantes`; `con_faltantes→controlado`; arrival emits `recepcion_arribo`; arrival writes NO line ingresos |

R2 hot spot: every assertion touching the terminal guard or all-zero transition must be INVERTED,
not merely renamed — review case-by-case to avoid renamed-but-not-inverted false greens.

## Implementation Order (for tasks)

1. Migration (UPDATE→constraint swap) + model constraint + `ESTADOS_PEDIDO`.
2. Service: `_ESTADOS_RECEPTIVOS`, terminal guard inversion, `recalcular_estado`→`controlado`,
   arrival branch, event filter += `recepcion_arribo`.
3. Endpoints: `confirmar-pedido` arrival/control routing by estado; saldo-visibility unchanged.
4. Tests: rename + INVERT + new (TDD red→green).
5. Frontend: FILTER_TABS + `?estado=` mapping, button gating both bodies, badge mapping.

**Slice split (~400-480 lines, >400 flagged):** Slice A = Backend (migration+service+endpoints+tests),
Slice B = Frontend (gating+tabs+badge, depends on A merged). Preferred: 2 slices stacked-to-main.
Alt: single PR with `size:exception` (rename is atomic; split leaves BE/FE state-name skew).

## Open Questions

- [ ] D-MIGRACION-WIPE — confirm with user whether prod has real old-`recibido` rows (UPDATE load-bearing) or data will be wiped (UPDATE defensive). Non-blocking; migration ships safe-by-default.
- [ ] CON-OC arrival entry point: confirm reuse of `/confirmar-pedido` for state-only arrival vs adding a tiny `/recepcion/arribo`. Design recommends reusing `/confirmar-pedido` to keep one arrival door.
