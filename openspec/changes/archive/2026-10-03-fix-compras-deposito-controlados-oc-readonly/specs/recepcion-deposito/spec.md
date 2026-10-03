# Delta for recepcion-deposito

## ADDED Requirements

### Requirement: Controlados CON-OC shows OC lines read-only

On Depósito tab **Controlados**, when a pedido has a linked OC (`oc_poh_id` set or `ocs[]`), the accordion body MUST list every ERP OC line returned by saldos, including lines with `saldo_pendiente = 0`. The list MUST be exhibit-only: the UI MUST NOT offer tanda quantity inputs, line checkboxes, **Marcar todo**, **Marcar con faltantes**, or **Marcar como controlado**. Backend estado transitions MUST NOT change.

#### Scenario: Controlados shows lines with saldo 0

- GIVEN a `controlado` CON-OC pedido whose saldos lines all have `saldo_pendiente = 0`
- WHEN the operator expands the pedido on Depósito → Controlados
- THEN each OC line item MUST be visible (name/code)

#### Scenario: Controlados has no control controls

- GIVEN a `controlado` CON-OC pedido
- WHEN the accordion body renders
- THEN **Marcar como controlado** MUST NOT be present
- AND **Marcar con faltantes** MUST NOT be present
- AND tanda quantity inputs MUST NOT be present

#### Scenario: Recibido still hides saldo 0 lines

- GIVEN a `recibido` CON-OC pedido with one line saldo 0 and one line saldo > 0
- WHEN the accordion body renders
- THEN the saldo 0 line MUST stay hidden
- AND the pending line MUST remain visible
