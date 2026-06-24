# Spec Delta — Recepción en Dos Pasos: estado `recibido` (llegó) + `controlado` (chequeado)

**Change:** compras-recepcion-estado-controlado
**Capability:** recepcion-estados (state machine, arrival, control, migration, UI tabs, badge)
**Status:** draft
**Date:** 2026-06-24
**Supersedes:** REQ-RD-002 and REQ-RD-007 of `compras-recepcion-deposito` (D4 reversal — `recibido` is no longer terminal)
**Depends on:** `compras-recepcion-deposito` (fully merged)

---

## Purpose

Extend the deposit reception flow from a single terminal step into two explicit
steps: **arrival** (goods physically present → `recibido`) and **control**
(goods counted and verified → `controlado`). The former terminal state `recibido`
is renamed `controlado`. A new intermediate state `recibido` (arrived, not
controlled) is introduced. No new permissions, tables, or saldo formulas are added.

---

## REQ-EC-001 — State Machine: updated transitions

**Priority:** must
**Type:** functional

The `pedidos_compra` reception state machine MUST enforce exactly these
transitions. Any transition not listed here MUST be rejected (HTTP 409).

| From | Action | To | Terminal |
|---|---|---|---|
| `pagado` | arrival marked (CON OC or SIN OC) | `recibido` | no |
| `recibido` | control marked complete | `controlado` | yes |
| `recibido` | control marked with missing items | `con_faltantes` | no |
| `con_faltantes` | control marked complete | `controlado` | yes |
| `controlado` | any reception attempt | 409 | — |
| any other state | any reception endpoint | 409 | — |

Notes:
- `recibido` is now INTERMEDIATE (not terminal). It accepts further reception
  actions (control step).
- `controlado` is the NEW terminal state. It replaces the role of the old
  `recibido` terminal.
- `con_faltantes` is no longer a self-loop: it resolves to `controlado` only.
- How SIN-OC actions trigger `recibido` vs `controlado` is per design decision
  D-SINOC (mechanism unspecified at spec level; behavior is specified here).

#### Scenario: pagado → recibido (arrival, not yet controlled)

- GIVEN a pedido P1 with `estado = pagado`
- WHEN the arrival action is executed (CON OC or SIN OC path)
- THEN P1.estado MUST become `recibido`
- AND the pedido MUST still be accessible for subsequent control actions

#### Scenario: recibido → controlado (control OK)

- GIVEN a pedido P1 with `estado = recibido`
- WHEN the control action is executed marking it complete
- THEN P1.estado MUST become `controlado`
- AND no further ingreso or control action MUST be accepted on P1

#### Scenario: recibido → con_faltantes (control finds missing items)

- GIVEN a pedido P1 with `estado = recibido`
- WHEN the control action is executed marking it with missing items
- THEN P1.estado MUST become `con_faltantes`
- AND the pedido MUST still accept a subsequent control action

#### Scenario: con_faltantes → controlado (missing items resolved)

- GIVEN a pedido P1 with `estado = con_faltantes`
- WHEN the control action is executed marking it complete
- THEN P1.estado MUST become `controlado`

#### Scenario: controlado rejects further ingresos — CON OC path (409)

- GIVEN a pedido P1 with `estado = controlado`
- WHEN `POST /pedidos/P1/recepcion/ingresos` is called
- THEN the response MUST be HTTP 409
- AND P1.estado MUST remain `controlado`
- AND no row MUST be inserted in `pedido_compra_ingresos`

#### Scenario: controlado rejects further confirmations — SIN OC path (409)

- GIVEN a pedido P1 with `estado = controlado`
- WHEN `POST /pedidos/P1/recepcion/confirmar-pedido` is called
- THEN the response MUST be HTTP 409
- AND P1.estado MUST remain `controlado`

#### Scenario: Invalid source state is rejected

- GIVEN a pedido P1 with `estado = borrador` (or `aprobado`, `cancelado`, etc.)
- WHEN any reception endpoint is called
- THEN the response MUST be HTTP 409 `"Pedido not in a receivable state"`

---

## REQ-EC-002 — CON OC path: arrival step (pagado → recibido)

**Priority:** must
**Type:** functional

When a CON OC pedido in `estado = pagado` receives a valid tanda via
`POST /recepcion/ingresos`, the outcome of the state transition changes:

- **Previous behavior** (compras-recepcion-deposito): `pagado` + saldos=0 → `recibido` (terminal).
- **New behavior**: `pagado` + any non-zero tanda → `recibido` (intermediate, regardless of
  whether all saldos are now zero). The saldo completeness check no longer gates the
  `pagado→recibido` transition; it only determines whether the subsequent control
  step results in `controlado` or `con_faltantes`.

Note: The exact mapping of saldo completeness to the control-step outcome is per
design D-CONOC. This spec constrains the observable behavior.

#### Scenario: CON OC — first tanda from pagado always → recibido

- GIVEN a pedido P1 with `estado = pagado` linked to OC
- WHEN `POST /recepcion/ingresos` is called with a valid tanda (all saldos zeroed out)
- THEN P1.estado MUST be `recibido` (not `controlado`)
- AND the response MUST indicate `estado_nuevo = "recibido"`
- AND a `recepcion_registrada` event MUST be emitted

#### Scenario: CON OC — partial first tanda from pagado → recibido (not con_faltantes)

- GIVEN a pedido P1 with `estado = pagado` linked to OC, pod_id=1 saldo=100
- WHEN `POST /recepcion/ingresos` with pod_id=1 cantidad_recibida=60
- THEN P1.estado MUST be `recibido`
- AND the response MUST indicate `estado_nuevo = "recibido"`

#### Scenario: CON OC — second tanda from recibido (control) zeroes saldos → controlado

- GIVEN a pedido P1 with `estado = recibido`, pod_id=1 saldo_pendiente=40
- WHEN `POST /recepcion/ingresos` is called with pod_id=1 cantidad_recibida=40
- THEN P1.estado MUST be `controlado`
- AND the response MUST indicate `estado_nuevo = "controlado"`

#### Scenario: CON OC — second tanda from recibido still has saldo → con_faltantes

- GIVEN a pedido P1 with `estado = recibido`, pod_id=1 saldo=40, pod_id=2 saldo=50
- WHEN `POST /recepcion/ingresos` with pod_id=1 cantidad_recibida=40 only
- THEN P1.estado MUST be `con_faltantes`

---

## REQ-EC-003 — SIN OC path: arrival and control steps

**Priority:** must
**Type:** functional

The SIN OC path (`POST /recepcion/confirmar-pedido`) MUST support two distinct
actions: marking arrival (`pagado → recibido`) and marking control
(`recibido → controlado` or `recibido → con_faltantes`).

The exact mechanism by which the endpoint distinguishes arrival from control
(state-aware routing, explicit action field, or flag reinterpretation) is per
design decision **D-SINOC**. This spec states only the required observable outcomes.

#### Scenario: SIN OC — marking arrival on a pagado pedido → recibido

- GIVEN a pedido P1 with `estado = pagado` and no linked OC
- WHEN the arrival action is executed via `POST /recepcion/confirmar-pedido`
- THEN P1.estado MUST become `recibido`
- AND an event of type `recepcion_registrada` MUST be emitted with `modo=sin_oc`
- AND no row MUST be created in `pedido_compra_ingresos`

#### Scenario: SIN OC — marking control complete on a recibido pedido → controlado

- GIVEN a pedido P1 with `estado = recibido` and no linked OC
- WHEN the control-complete action is executed via `POST /recepcion/confirmar-pedido`
- THEN P1.estado MUST become `controlado`
- AND an event of type `recepcion_registrada` MUST be emitted with `modo=sin_oc`

#### Scenario: SIN OC — marking control with missing items on a recibido pedido → con_faltantes

- GIVEN a pedido P1 with `estado = recibido` and no linked OC
- WHEN the control-with-missing action is executed (with observaciones provided)
- THEN P1.estado MUST become `con_faltantes`
- AND an event of type `recepcion_con_faltantes` MUST be emitted with `modo=sin_oc`

#### Scenario: SIN OC — marking control with missing items without observaciones → 422

- GIVEN a pedido P1 with `estado = recibido` and no linked OC
- WHEN the control-with-missing action is executed WITHOUT observaciones
- THEN the response MUST be HTTP 422
- AND P1.estado MUST remain `recibido`

#### Scenario: SIN OC — controlado rejects further action → 409

- GIVEN a pedido P1 with `estado = controlado` and no linked OC
- WHEN `POST /recepcion/confirmar-pedido` is called
- THEN the response MUST be HTTP 409

---

## REQ-EC-004 — Permission gate: all three actions require `deposito.recibir_mercaderia`

**Priority:** must
**Type:** security

ALL three reception actions (arrival, control-complete, control-with-missing) on
BOTH CON OC and SIN OC paths MUST require the `deposito.recibir_mercaderia`
permission. No new permission is created.

A user without `deposito.recibir_mercaderia` MUST receive HTTP 403 on every
reception endpoint. No DB read or write MUST be performed before the permission
check returns 403.

#### Scenario: User without permission is rejected on arrival action

- GIVEN a user with no permissions (or any permission other than `deposito.recibir_mercaderia`)
- WHEN `POST /recepcion/ingresos` or `POST /recepcion/confirmar-pedido` is called
  on a `pagado` pedido
- THEN the response MUST be HTTP 403
- AND P1.estado MUST remain unchanged

#### Scenario: User without permission is rejected on control action

- GIVEN a user without `deposito.recibir_mercaderia`
- WHEN the control action is called on a `recibido` pedido (CON OC or SIN OC)
- THEN the response MUST be HTTP 403

#### Scenario: `gestionar_ordenes_compra` alone does NOT grant access

- GIVEN a user with `administracion.gestionar_ordenes_compra` but NOT
  `deposito.recibir_mercaderia`
- WHEN any reception endpoint is called
- THEN the response MUST be HTTP 403

---

## REQ-EC-005 — Filter tabs: 4 tabs mapping to correct states

**Priority:** must
**Type:** ui

The deposit reception UI MUST display exactly four filter tabs, each mapping to
the listed `?estado=` query parameter value:

| Tab label | Estado filter |
|---|---|
| Por recibir | `pagado` |
| Recibidos sin controlar | `recibido` |
| Controlados | `controlado` |
| Con faltantes | `con_faltantes` |

The previous two-tab layout (or any layout that groups `recibido` and
`controlado` together) MUST NOT appear after this change.

#### Scenario: "Por recibir" tab shows only pagado pedidos

- GIVEN pedidos P1 (pagado), P2 (recibido), P3 (controlado), P4 (con_faltantes)
- WHEN the user activates the "Por recibir" tab
- THEN only P1 MUST appear in the list

#### Scenario: "Recibidos sin controlar" tab shows only recibido pedidos

- GIVEN the same P1–P4 above
- WHEN the user activates the "Recibidos sin controlar" tab
- THEN only P2 MUST appear

#### Scenario: "Controlados" tab shows only controlado pedidos

- GIVEN the same P1–P4 above
- WHEN the user activates the "Controlados" tab
- THEN only P3 MUST appear

#### Scenario: "Con faltantes" tab shows only con_faltantes pedidos

- GIVEN the same P1–P4 above
- WHEN the user activates the "Con faltantes" tab
- THEN only P4 MUST appear

---

## REQ-EC-006 — Frontend button gating by estado

**Priority:** must
**Type:** ui

The action buttons rendered in the accordion body (both CON OC and SIN OC branches)
MUST be gated by the pedido's current `estado` as follows:

| estado | Buttons shown |
|---|---|
| `pagado` | "Recibido" (marks arrival) |
| `recibido` | "Controlado" + "Con faltantes" |
| `con_faltantes` | "Controlado" |
| `controlado` | no action buttons (read-only view) |

No button from another estado row MUST appear simultaneously with buttons from a
different row.

#### Scenario: pagado pedido shows only "Recibido" button

- GIVEN P1 with `estado = pagado`
- WHEN the accordion body is rendered
- THEN a "Recibido" button MUST be visible
- AND "Controlado" and "Con faltantes" buttons MUST NOT be visible

#### Scenario: recibido pedido shows "Controlado" and "Con faltantes" buttons

- GIVEN P1 with `estado = recibido`
- WHEN the accordion body is rendered
- THEN "Controlado" AND "Con faltantes" buttons MUST both be visible
- AND "Recibido" button MUST NOT be visible

#### Scenario: con_faltantes pedido shows only "Controlado" button

- GIVEN P1 with `estado = con_faltantes`
- WHEN the accordion body is rendered
- THEN "Controlado" button MUST be visible
- AND "Recibido" and "Con faltantes" buttons MUST NOT be visible

#### Scenario: controlado pedido shows no action buttons

- GIVEN P1 with `estado = controlado`
- WHEN the accordion body is rendered
- THEN no action button (Recibido, Controlado, Con faltantes) MUST be visible
- AND the view MUST indicate the pedido is terminal (read-only)

---

## REQ-EC-007 — Badge mapping: recibido (amber) and controlado (green)

**Priority:** must
**Type:** ui

The `EstadoBadge` component's `MAPPING_PEDIDO` (and any inline `estadoBadge`
function in `TabRecepcionDeposito.jsx`) MUST be updated:

| Estado | Tone/variant | Label |
|---|---|---|
| `recibido` | amber / "parcial" | "Recibido" |
| `controlado` | green / "pagado" | "Controlado" |
| `con_faltantes` | unchanged from prior change | unchanged |

The old entry for `recibido` (which previously had a "received/terminal" green
tone) MUST be replaced with the amber/"parcial" tone.
The new `controlado` entry MUST use the same green tone that `recibido` previously used.

#### Scenario: recibido state renders amber "Recibido" badge

- GIVEN a pedido P1 with `estado = recibido`
- WHEN the badge is rendered (in any component that uses EstadoBadge or estadoBadge)
- THEN the badge MUST display label "Recibido"
- AND MUST use the amber/partial visual tone

#### Scenario: controlado state renders green "Controlado" badge

- GIVEN a pedido P1 with `estado = controlado`
- WHEN the badge is rendered
- THEN the badge MUST display label "Controlado"
- AND MUST use the green/pagado visual tone

#### Scenario: con_faltantes badge is unaffected

- GIVEN a pedido P1 with `estado = con_faltantes`
- WHEN the badge is rendered
- THEN the badge MUST display the same label and tone as before this change

---

## REQ-EC-008 — Data migration: old `recibido` → `controlado`

**Priority:** must
**Type:** data-migration

An Alembic migration MUST be provided that:

1. **DATA step** (before constraint change): executes
   `UPDATE pedidos_compra SET estado='controlado' WHERE estado='recibido'`
2. **DROP** the existing `CheckConstraint` on `pedidos_compra.estado`
3. **ADD** a new `CheckConstraint` that includes all values from the prior change
   PLUS `controlado`. Final full set:
   `borrador, pendiente_aprobacion, aprobado, rechazado, cancelado, pagado_parcial,
   pagado, recibido, con_faltantes, controlado`

The `downgrade()` function MUST:
- Revert the constraint to the prior-change constraint (without `controlado`)
- **NOT** attempt to revert the data (the UPDATE is one-way and irreversible)
- Include a docstring noting that the downgrade does not restore data semantics
  and is documented as a one-way migration

After upgrade:
- `INSERT pedidos_compra (estado='controlado')` MUST succeed
- `INSERT pedidos_compra (estado='recibido')` MUST succeed (new meaning)
- Any row that had `estado='recibido'` before upgrade MUST now have `estado='controlado'`

#### Scenario: Migration upgrades — existing recibido rows become controlado

- GIVEN a DB with N rows where `estado='recibido'` (old meaning: terminal)
- WHEN the migration's `upgrade()` is applied
- THEN all N rows MUST have `estado='controlado'`
- AND rows with any other estado MUST be unchanged

#### Scenario: Migration upgrades — new constraint accepts both recibido and controlado

- GIVEN the migration has been applied
- WHEN `INSERT pedidos_compra (estado='recibido')` is attempted (new meaning: arrived)
- THEN the INSERT MUST succeed (constraint accepts it)
- WHEN `INSERT pedidos_compra (estado='controlado')` is attempted
- THEN the INSERT MUST succeed

#### Scenario: Migration upgrades — invalid estado still rejected

- GIVEN the migration has been applied
- WHEN `INSERT pedidos_compra (estado='en_camino')` is attempted
- THEN the DB constraint MUST reject it

#### Scenario: Migration downgrade — constraint reverts, data does NOT revert

- GIVEN a DB in upgraded state (has `controlado` rows and new constraint)
- WHEN `downgrade()` is applied
- THEN the constraint MUST no longer accept `controlado` as a value
- AND existing rows with `estado='controlado'` are NOT restored to `recibido`
  (this is documented behavior — data is one-way)

---

## REQ-EC-009 — Saldo visibility for recibido (arrived, not controlled)

**Priority:** must
**Type:** functional

A pedido with `estado = recibido` (arrived but not yet controlled) MUST remain
accessible via `GET /pedidos/{id}/recepcion/saldos`. The endpoint MUST return
the current saldo breakdown so the control step can reference it.

A pedido with `estado = controlado` (terminal) MUST also be accessible via
`GET /recepcion/saldos` (read-only audit access).

The set of states that allow saldo queries MUST include:
`pagado`, `recibido`, `con_faltantes`, `controlado`.

#### Scenario: recibido pedido saldos are accessible

- GIVEN P1 with `estado = recibido` (arrived, ingresos exist)
- WHEN `GET /pedidos/P1/recepcion/saldos`
- THEN HTTP 200 MUST be returned with correct saldo breakdown
- AND the response MUST NOT be rejected with 409

#### Scenario: controlado pedido saldos are accessible (audit)

- GIVEN P1 with `estado = controlado`
- WHEN `GET /pedidos/P1/recepcion/saldos`
- THEN HTTP 200 MUST be returned (read-only audit view, no action allowed)

#### Scenario: Non-receptive estado still returns 409 on saldos

- GIVEN P1 with `estado = borrador`
- WHEN `GET /pedidos/P1/recepcion/saldos`
- THEN HTTP 409 `"Pedido not in a receivable state"`

---

## REQ-EC-010 — Out-of-scope guard: cheque evento `recibido` is unaffected

**Priority:** must
**Type:** non-functional / boundary

The `'recibido'` string used as an event type in `cheques_service.py` belongs to
the cheques domain and is INDEPENDENT of `pedidos_compra.estado`. This change
MUST NOT modify any logic in `cheques_service.py`.

#### Scenario: Cheque recibido evento is not affected

- GIVEN the migration and service changes of this change are applied
- WHEN a cheque event of type `'recibido'` is processed by `cheques_service.py`
- THEN the behavior MUST be identical to before this change
- AND `cheques_service.py` MUST NOT have been modified

---

## REQ-EC-011 — Schema: `ESTADOS_PEDIDO` extended with `controlado`

**Priority:** must
**Type:** data-model

The `ESTADOS_PEDIDO` tuple (or equivalent constant) in
`backend/app/schemas/pedido_compra.py` MUST include `'controlado'` in addition to
all prior values. This ensures Pydantic validation and any enum-based filters
accept the new terminal state.

#### Scenario: Schema accepts controlado as a valid estado value

- GIVEN a Pydantic model using `ESTADOS_PEDIDO` for validation
- WHEN `estado='controlado'` is provided
- THEN validation MUST pass

#### Scenario: Schema still rejects invalid estado values

- GIVEN a Pydantic model using `ESTADOS_PEDIDO`
- WHEN `estado='en_camino'` is provided
- THEN validation MUST fail with a clear error

---

## REQ-EC-012 — Test coverage: Strict TDD requirements

**Priority:** must
**Type:** testing

The existing test file `backend/tests/integration/test_recepcion_deposito_endpoints.py`
MUST be updated as follows:

### Rename (mechanical)
All assertions referencing the OLD `recibido` as a terminal state MUST be updated
to reference `controlado`. This includes response body checks, estado assertions,
and event type checks where `recibido` was used as a terminal.

### Invert (semantic change — highest risk)
Tests that previously asserted `recibido → 409 (terminal block)` MUST be
INVERTED to assert `controlado → 409` AND that `recibido` ACCEPTS further actions.
Specifically:
- The scenario "Pedido is recibido → 409" from REQ-RD-005 of the prior change
  MUST become "Pedido is controlado → 409".
- A new sibling test MUST assert that a `recibido` pedido ACCEPTS `POST /recepcion/ingresos`.

### New tests (required additions)
The following scenarios MUST have corresponding pytest tests:

| Test | Expected outcome |
|---|---|
| `pagado → recibido` via CON OC tanda | estado = recibido, not controlado |
| `pagado → recibido` via SIN OC arrival | estado = recibido |
| `recibido → controlado` via CON OC control | estado = controlado, 409 on next ingreso |
| `recibido → controlado` via SIN OC control | estado = controlado |
| `recibido → con_faltantes` | estado = con_faltantes |
| `con_faltantes → controlado` | estado = controlado, terminal |
| `controlado → any` | HTTP 409 on both endpoints |
| Badge/filter assertions are frontend — covered by manual test or Playwright if available |

#### Scenario: Test inversion — recibido now accepts ingreso

- GIVEN the updated test suite is run
- WHEN the test for "recibido pedido" runs `POST /recepcion/ingresos`
- THEN the test MUST ASSERT HTTP 201 (accepted), NOT HTTP 409

#### Scenario: Test inversion — controlado is the new terminal (409)

- GIVEN the updated test suite is run
- WHEN the test for "controlado pedido" runs `POST /recepcion/ingresos`
- THEN the test MUST ASSERT HTTP 409

---

## Assumptions resolved at spec level

| ID | Open question | Resolution |
|---|---|---|
| S1 | What states can query saldos? | `pagado`, `recibido`, `con_faltantes`, `controlado` (REQ-EC-009) |
| S2 | Is `con_faltantes` → `recibido` a valid transition? | NO. `con_faltantes` resolves to `controlado` only (REQ-EC-001). |
| S3 | Does arrival (pagado→recibido) require all saldos=0? | No. Any valid tanda on a pagado pedido → recibido (REQ-EC-002). |

---

## Open design decisions (NOT resolved in this spec)

| ID | Decision | Blocking |
|---|---|---|
| D-SINOC | How `POST /confirmar-pedido` distinguishes arrival (→recibido) from control (→controlado/con_faltantes) given the current `completo:bool` flag | Blocking for SIN OC implementation |
| D-CONOC | Whether the "Recibido" button on CON OC writes ingresos rows or only changes estado | Blocking for CON OC arrival implementation |
| D-MIGRACION-WIPE | Whether prod has real `recibido` rows or user will wipe data | Non-blocking (migration is a safe default) |

---

## Out of Scope (explicit exclusions — carried from proposal)

1. New permission (none created; all actions use `deposito.recibir_mercaderia`)
2. Cheque domain `'recibido'` evento (`cheques_service.py` — different domain, untouched)
3. Re-opening a `controlado` pedido (downgrade is one-way; no data reversal)
4. Push/notification when estado transitions to `recibido`
5. RMA / devoluciones
6. New tables or saldo formula changes (reuse existing `pedido_compra_ingresos` and formula)
7. Per-item receipt for SIN OC pedidos (no table available)
