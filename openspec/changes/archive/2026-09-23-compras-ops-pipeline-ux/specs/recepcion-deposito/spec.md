# Delta for recepcion-deposito

## ADDED Requirements

### Requirement: AND filters on Depósito

Depósito lists MUST AND-combine contains filters: proveedor, pedido, Pricing `P-…`, factura number, empresa. A row MUST match every non-empty filter.

#### Scenario: AND narrows the list

- GIVEN pedidos matching proveedor Acme only, and one that also has factura `FA-1`
- WHEN the operator filters proveedor `Acme` AND factura `FA-1`
- THEN only the intersection MUST appear

#### Scenario: Empty filter ignored

- GIVEN several receivable pedidos
- WHEN only Pricing `P-01-2026-00012` is filled
- THEN rows that do not contain that `P-…` MUST be hidden

### Requirement: Docs button opens pedido adjuntos

The Depósito docs control MUST open the pedido’s adjuntos. It MUST NOT be a generic documents dump or ERP attachment browser.

#### Scenario: Docs opens adjuntos

- GIVEN a pedido with adjuntos
- WHEN the operator activates Docs
- THEN those pedido adjuntos MUST be shown

### Requirement: Hide complete lines in faltantes

On faltantes, lines with `saldo_pendiente = 0` MUST be hidden. Incomplete lines MUST remain.

#### Scenario: Complete line hidden

- GIVEN pod_id=1 saldo 0 and pod_id=2 saldo 10 on a faltantes pedido
- WHEN faltantes UI renders
- THEN pod_id=1 MUST be hidden
- AND pod_id=2 MUST be visible

### Requirement: Control observation and photo optional

On Depósito control, observation text and photo MUST be optional. Completing control MUST succeed without them. Faltantes free text remains required by `compras-pipeline-alerts`.

#### Scenario: Control complete without obs or photo

- GIVEN a `recibido` pedido
- WHEN the operator marks control complete with empty obs and no photo
- THEN the action MUST succeed

## MODIFIED Requirements

### Requirement: TabRecepcionDeposito.jsx — Pedido list

The component MUST:
- Render each pedido as a collapsible accordion entry.
- Show a visual indicator for pedidos with `requiere_envio=true`.
- Support an optional filter by `requiere_envio` (all / solo retiro / solo entrega).
- On tab **Por recibir**, default the financial filter to `pagado` only.
- Offer a toggle to also include cuenta-corriente pedidos on Por recibir.
- Apply the AND contains filters from this change.

(Previously: fetched all `pagado` and `con_faltantes` in one list; no pagado-only default or CC toggle.)

#### Scenario: List shows pagado and con_faltantes pedidos

- GIVEN 3 pedidos: P1 (pagado), P2 (con_faltantes), P3 (recibido)
- WHEN the deposito tab loads on Por recibir (default)
- THEN P1 MUST appear; P2 MUST appear only on Con faltantes; P3 MUST NOT appear on Por recibir

#### Scenario: Por recibir defaults to pagado only

- GIVEN P-pagado, P-cc (cuenta corriente, not pagado), P-recibido
- WHEN Por recibir loads with the CC toggle off
- THEN only P-pagado MUST appear

#### Scenario: CC toggle includes cuenta corriente

- GIVEN the same three pedidos
- WHEN the operator turns on include cuenta corriente
- THEN P-pagado AND P-cc MUST appear
- AND P-recibido MUST NOT
