# Delta for recepcion-deposito

## ADDED Requirements

### Requirement: Depósito tabs filter by eje and exclude servicio

Con faltantes MUST list only `eje_procesal=faltantes_sin_res`. Recibidos MUST include `recibido` AND `faltantes_con_res`. Por recibir MUST exclude `tipo=servicio`.

#### Scenario: Con faltantes hides resolved

- GIVEN P-sin (`faltantes_sin_res`) and P-con (`faltantes_con_res`)
- WHEN Con faltantes loads
- THEN only P-sin MUST appear

#### Scenario: Recibidos includes resolved faltantes

- GIVEN P-rec (`recibido`) and P-con (`faltantes_con_res`)
- WHEN Recibidos loads
- THEN both MUST appear

#### Scenario: Servicio excluded from Por recibir

- GIVEN P-svc (`tipo=servicio`) and P-mer (`tipo=mercaderia`, `por_recibir`)
- WHEN Por recibir loads
- THEN P-mer MUST appear
- AND P-svc MUST NOT

### Requirement: Factura cargada badge in Depósito

When `factura_cargada` is true, Depósito MUST show a “Factura cargada” badge in the Controlado visual family. Mere factura numbers without cargada MUST NOT show that badge.

#### Scenario: Badge follows cargada flag

- GIVEN P with `factura_cargada=true`
- WHEN the Depósito row renders
- THEN a Controlado-like “Factura cargada” badge MUST be visible

#### Scenario: Numbers without cargada show no badge

- GIVEN P with factura numbers and `factura_cargada=false`
- WHEN the Depósito row renders
- THEN the “Factura cargada” badge MUST NOT appear

### Requirement: Ident chips on all Depósito rows

Every Depósito row, including CON-OC, MUST show factura number and `pedidos_documento` chips. The system MUST NOT hide these chips because `oc_poh_id` is set.

#### Scenario: CON-OC shows factura and pedidos_documento

- GIVEN P with `oc_poh_id` set, numero_factura `FA-1`, and `pedidos_documento` `AD-9`
- WHEN the row renders
- THEN both `FA-1` and `AD-9` MUST be visible as chips

#### Scenario: SIN-OC still shows ident chips

- GIVEN P with no OC, numero_factura `FA-2`, and `pedidos_documento` `AD-3`
- WHEN the row renders
- THEN both chips MUST be visible

## MODIFIED Requirements

### Requirement: Control observation and photo optional

On Depósito control, including control OK (complete), observation text and photo MUST be optional. Photo MUST use existing adjuntos `tipo=otro`. Completing control MUST succeed without them. Faltantes free text remains required by `compras-pipeline-alerts`.

(Previously: optional obs/photo stated for control generally; control-OK and `tipo=otro` were unstated.)

#### Scenario: Control complete without obs or photo

- GIVEN a `recibido` pedido
- WHEN the operator marks control complete with empty obs and no photo
- THEN the action MUST succeed

#### Scenario: Control OK accepts obs and photo

- GIVEN a `recibido` pedido
- WHEN the operator marks control complete with observaciones and an adjunto `tipo=otro`
- THEN the action MUST succeed
- AND that adjunto MUST be stored on the pedido

### Requirement: TabRecepcionDeposito.jsx — Pedido list

The component MUST:
- Render each pedido as a collapsible accordion.
- Show a visual indicator for `requiere_envio=true`.
- Support filter by `requiere_envio` (all / solo retiro / solo entrega).
- On **Por recibir**, default to `pagado` only and exclude `tipo=servicio`.
- Offer a CC toggle on Por recibir.
- Apply the AND contains filters from this change.
- Filter **Con faltantes** by `eje_procesal=faltantes_sin_res` only.
- Filter **Recibidos** by `recibido` AND `faltantes_con_res`.
- Show factura number and `pedidos_documento` chips on every row, including CON-OC.

(Previously: one list of `pagado`+`con_faltantes`; no CC toggle; Con faltantes used financial `estado`; ident chips SIN-OC only.)

#### Scenario: List shows pagado and con_faltantes pedidos

- GIVEN 3 pedidos: P1 (pagado), P2 (con_faltantes, `faltantes_sin_res`), P3 (recibido)
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
