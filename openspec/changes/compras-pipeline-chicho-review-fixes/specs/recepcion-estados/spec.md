# Delta for recepcion-estados

## MODIFIED Requirements

### Requirement: Undo recibido

An operator with `deposito.recibir_mercaderia` MUST be able to undo `recibido` back to waiting-for-goods. Reconstruction MUST follow D-UNDO-R: the pedido MUST become `en_cuenta_corriente` if and only if `op_cuenta_corriente_id` is set and `pagado_en` is null; otherwise it MUST become `pagado`. Procesal MUST be `por_recibir`. `controlado` MUST remain terminal (HTTP 409). A second undo MUST be HTTP 409. An actor without `deposito.recibir_mercaderia` MUST receive HTTP 403. Undo MUST write an audit event. D-UNDO-R reconstruction is confirmed correct; this change MUST add the missing tests (double undo, CC+`pagado_en`, 403).

(Previously: undo described as always returning to `pagado`; missing double-undo, CC+`pagado_en` → `pagado`, and 403 coverage.)

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

#### Scenario: D-UNDO-R restores cuenta corriente

- GIVEN P1.estado = `recibido`, `op_cuenta_corriente_id` set, `pagado_en` null
- WHEN depósito undoes recibido
- THEN P1.estado MUST be `en_cuenta_corriente`
- AND procesal MUST be `por_recibir`

#### Scenario: CC with pagado_en reconstructs pagado

- GIVEN P1.estado = `recibido`, `op_cuenta_corriente_id` set, `pagado_en` set
- WHEN depósito undoes recibido
- THEN P1.estado MUST be `pagado`

#### Scenario: Second undo rejected

- GIVEN P1 was undone from `recibido` and is no longer `recibido`
- WHEN depósito undoes recibido again
- THEN HTTP 409

#### Scenario: Undo without permission forbidden

- GIVEN an actor without `deposito.recibir_mercaderia`
- WHEN that actor undoes recibido
- THEN HTTP 403

### Requirement: Controlado iff all OCs done

A pedido with N linked OCs MUST become `controlado` only when every linked OC has completed control. Controlling a subset MUST leave the pedido non-terminal (`recibido` or `faltantes_*`).

(Previously: specified 1-of-2 only; 1-of-3 mid-control was unstated.)

#### Scenario: One of two OCs controlled

- GIVEN P1 linked to OC-A and OC-B; OC-A control is complete; OC-B is not
- WHEN control is saved for OC-A
- THEN P1 MUST NOT be `controlado`

#### Scenario: One of three OCs controlled

- GIVEN P1 linked to OC-A, OC-B, and OC-C; only OC-A control is complete
- WHEN control is saved for OC-A
- THEN P1 MUST NOT be `controlado`
- AND P1 MUST remain `recibido` or `faltantes_*`

#### Scenario: Last OC completes control

- GIVEN the same P1 with OC-A already controlled
- WHEN OC-B control completes
- THEN P1 MUST become `controlado`

### Requirement: REQ-EC-001 — State Machine: updated transitions

The `pedidos_compra` reception state machine MUST enforce exactly these transitions. Any transition not listed here MUST be rejected (HTTP 409).

| From | Action | To | Terminal |
|---|---|---|---|
| `pagado` | arrival marked (CON OC or SIN OC) | `recibido` | no |
| `recibido` | control marked complete (and all linked OCs controlled) | `controlado` | yes |
| `recibido` | control marked complete (other OCs still open) | `recibido` | no |
| `recibido` | control marked with missing items | `con_faltantes` | no |
| `recibido` | undo recibido | `pagado` or `en_cuenta_corriente` (D-UNDO-R) | no |
| `con_faltantes` | control marked complete (and all linked OCs controlled) | `controlado` | yes |
| `controlado` | any reception attempt | 409 | — |
| any other state | any reception endpoint | 409 | — |

Notes:
- `recibido` is INTERMEDIATE. It accepts control and undo-recibido.
- `controlado` is terminal and requires every linked OC controlled (zero OCs: SIN OC path unchanged).
- `con_faltantes` resolves to `controlado` only when all OCs are done.
- Servicio does not use this machine (`n_a_servicio`).
- How SIN-OC actions trigger `recibido` vs `controlado` remains per design D-SINOC.
- Undo reconstructs D-UNDO-R: `en_cuenta_corriente` iff `op_cuenta_corriente_id` is set and `pagado_en` is null; otherwise `pagado`. D-UNDO-R is confirmed correct.

(Previously: undo from `recibido` always listed as `pagado` only.)

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

- GIVEN P1.estado = `recibido` and D-UNDO-R would reconstruct `pagado`
- WHEN undo recibido is executed
- THEN P1.estado MUST become `pagado`
