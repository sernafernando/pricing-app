# Delta for recepcion-deposito

## ADDED Requirements

### Requirement: Pedido chips keep stored leading zeros

Depósito pedido chips MUST render the stored `pedidos_documento` token string. The system MUST NOT coerce chip text to a number. Leading zeros MUST remain visible.

#### Scenario: Leading zeros stay on the chip

- GIVEN a pedido whose stored `pedidos_documento` token is `00184465`
- WHEN the Depósito row renders
- THEN the pedido chip MUST show `00184465`
- AND MUST NOT show `184465`

#### Scenario: Multiple tokens keep each string

- GIVEN `pedidos_documento` is `0012; PED-08`
- WHEN the Depósito row renders
- THEN chips MUST show `0012` and `PED-08`

### Requirement: Incluir cuenta corriente defaults on

On first mount of Depósito (Por recibir), the **Incluir cuenta corriente** toggle MUST default to checked (`true`) so `pagado` and `en_cuenta_corriente` are both requested. The operator MUST still be able to turn it off. The system MUST NOT persist the toggle across sessions unless product later asks for it.

#### Scenario: Default includes cuenta corriente

- GIVEN an operator opens Compras → Depósito with the Por recibir filter active
- WHEN the list loads for the first time in that mount
- THEN the Incluir cuenta corriente control MUST be checked
- AND the list request MUST include `en_cuenta_corriente` together with `pagado`

#### Scenario: Operator can turn the toggle off

- GIVEN the Incluir cuenta corriente toggle is on by default
- WHEN the operator unchecks it
- THEN subsequent list requests for Por recibir MUST request `pagado` only (no `en_cuenta_corriente`)
