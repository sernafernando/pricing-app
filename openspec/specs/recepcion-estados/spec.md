# Delta for recepcion-estados

## ADDED Requirements

### Requirement: Undo recibido

An operator with `deposito.recibir_mercaderia` MUST be able to undo `recibido` back to waiting-for-goods (`pagado` / procesal `por_recibir`). `controlado` MUST remain terminal (no undo). Undo MUST write an audit event.

#### Scenario: Undo recibido returns to por recibir

- GIVEN P1.estado = `recibido`
- WHEN depósito undoes recibido
- THEN P1 MUST return to a receivable waiting state (`pagado`)
- AND procesal MUST be `por_recibir`
- AND a subsequent arrival action MUST be accepted

#### Scenario: Undo controlado rejected

- GIVEN P1.estado = `controlado`
- WHEN depósito undoes recibido
- THEN the system MUST reject (HTTP 409)
- AND P1 MUST stay `controlado`

### Requirement: Servicio uses n_a_servicio

Pedidos with `tipo=servicio` MUST take procesal `n_a_servicio` and MUST NOT enter OC reception. Arrival/control endpoints MUST reject servicio (HTTP 409).

#### Scenario: Servicio skipped by recepción

- GIVEN P1.tipo = `servicio`
- WHEN any recepción ingreso or confirmar-pedido is called
- THEN HTTP 409
- AND procesal MUST remain `n_a_servicio`

### Requirement: Controlado iff all OCs done

A pedido with N linked OCs MUST become `controlado` only when every linked OC has completed control. Controlling a subset MUST leave the pedido non-terminal (`recibido` or `faltantes_*`).

#### Scenario: One of two OCs controlled

- GIVEN P1 linked to OC-A and OC-B; OC-A control is complete; OC-B is not
- WHEN control is saved for OC-A
- THEN P1 MUST NOT be `controlado`

#### Scenario: Last OC completes control

- GIVEN the same P1 with OC-A already controlled
- WHEN OC-B control completes
- THEN P1 MUST become `controlado`

## MODIFIED Requirements

### Requirement: REQ-EC-001 — State Machine: updated transitions

The `pedidos_compra` reception state machine MUST enforce exactly these transitions. Any transition not listed here MUST be rejected (HTTP 409).

| From | Action | To | Terminal |
|---|---|---|---|
| `pagado` | arrival marked (CON OC or SIN OC) | `recibido` | no |
| `recibido` | control marked complete (and all linked OCs controlled) | `controlado` | yes |
| `recibido` | control marked complete (other OCs still open) | `recibido` | no |
| `recibido` | control marked with missing items | `con_faltantes` | no |
| `recibido` | undo recibido | `pagado` | no |
| `con_faltantes` | control marked complete (and all linked OCs controlled) | `controlado` | yes |
| `controlado` | any reception attempt | 409 | — |
| any other state | any reception endpoint | 409 | — |

Notes:
- `recibido` is INTERMEDIATE. It accepts control and undo-recibido.
- `controlado` is terminal and requires every linked OC controlled (zero OCs: SIN OC path unchanged).
- `con_faltantes` resolves to `controlado` only when all OCs are done.
- Servicio does not use this machine (`n_a_servicio`).
- How SIN-OC actions trigger `recibido` vs `controlado` remains per design D-SINOC.

(Previously: no undo from `recibido`; controlado as soon as the single-OC/SIN-OC control completed.)

#### Scenario: pagado → recibido (arrival, not yet controlled)

- GIVEN a pedido P1 with `estado = pagado`
- WHEN the arrival action is executed (CON OC or SIN OC path)
- THEN P1.estado MUST become `recibido`
- AND the pedido MUST still be accessible for subsequent control actions

#### Scenario: recibido → controlado (control OK)

- GIVEN a pedido P1 with `estado = recibido` and all linked OCs (or SIN OC) ready to close
- WHEN the control action is executed marking it complete
- THEN P1.estado MUST become `controlado`
- AND no further ingreso or control action MUST be accepted on P1

#### Scenario: recibido → con_faltantes (control finds missing items)

- GIVEN a pedido P1 with `estado = recibido`
- WHEN the control action is executed marking it with missing items
- THEN P1.estado MUST become `con_faltantes`
- AND the pedido MUST still accept a subsequent control action

#### Scenario: con_faltantes → controlado (missing items resolved)

- GIVEN a pedido P1 with `estado = con_faltantes` and all OCs ready to close
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

#### Scenario: Undo recibido from intermediate

- GIVEN P1.estado = `recibido`
- WHEN undo recibido is executed
- THEN P1.estado MUST become `pagado`

### Requirement: REQ-EC-003 — SIN OC path: arrival and control steps

The SIN OC path (`POST /recepcion/confirmar-pedido`) MUST support two distinct
actions: marking arrival (`pagado → recibido`) and marking control
(`recibido → controlado` or `recibido → con_faltantes`).

The exact mechanism by which the endpoint distinguishes arrival from control
(state-aware routing, explicit action field, or flag reinterpretation) is per
design decision **D-SINOC**. This spec states only the required observable outcomes.

Observation text and photo on control MUST be optional. Marking faltantes still
requires free text for the alert (`compras-pipeline-alerts`).

(Previously: control-with-missing without observaciones returned HTTP 422.)

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
- WHEN the control-with-missing action is executed (alert free text provided)
- THEN P1.estado MUST become `con_faltantes`
- AND an event of type `recepcion_con_faltantes` MUST be emitted with `modo=sin_oc`

#### Scenario: SIN OC — control-with-missing without observaciones still succeeds

- GIVEN a pedido P1 with `estado = recibido` and no linked OC
- WHEN the control-with-missing action is executed WITHOUT observaciones or photo
- AND required faltantes free text is present
- THEN the response MUST succeed
- AND P1.estado MUST become `con_faltantes`

#### Scenario: SIN OC — controlado rejects further action → 409

- GIVEN a pedido P1 with `estado = controlado` and no linked OC
- WHEN `POST /recepcion/confirmar-pedido` is called
- THEN the response MUST be HTTP 409

### Requirement: REQ-EC-005 — Filter tabs: 4 tabs mapping to correct states

The deposit reception UI MUST display exactly four filter tabs, each mapping to
the listed `?estado=` query parameter value:

| Tab label | Estado filter |
|---|---|
| Por recibir | `pagado` by default; optional toggle includes cuenta corriente |
| Recibidos sin controlar | `recibido` |
| Controlados | `controlado` |
| Con faltantes | `con_faltantes` |

The previous two-tab layout (or any layout that groups `recibido` and
`controlado` together) MUST NOT appear after this change.

(Previously: Por recibir showed only `pagado` with no CC toggle.)

#### Scenario: "Por recibir" tab shows only pagado pedidos

- GIVEN pedidos P1 (pagado), P2 (recibido), P3 (controlado), P4 (con_faltantes)
- WHEN the user activates the "Por recibir" tab with CC toggle off
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

#### Scenario: Por recibir CC toggle includes cuenta corriente

- GIVEN P1 (pagado) and P-cc (cuenta corriente, not pagado)
- WHEN Por recibir is active and the CC toggle is on
- THEN P1 and P-cc MUST appear
