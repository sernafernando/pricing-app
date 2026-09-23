# Delta for recepcion-estados

## ADDED Requirements

### Requirement: Resolve faltantes keeps financial estado

`POST /pedidos/{id}/faltantes/resolver` MUST require nonempty `texto` and MUST stamp `faltantes_resuelto_en`. Financial `estado` MUST remain `con_faltantes`. The system MUST NOT introduce a new financial estado. Writers MUST be the pedido `responsable` OR a holder of `administracion.gestionar_ordenes_compra`. Holding only `deposito.recibir_mercaderia` MUST NOT authorize resolve.

#### Scenario: Resolve stamps without new estado

- GIVEN P.estado=`con_faltantes` and `faltantes_resuelto_en` is null
- WHEN a writer POSTs resolve with nonempty texto
- THEN `faltantes_resuelto_en` MUST be set
- AND P.estado MUST remain `con_faltantes`

#### Scenario: Empty texto rejected

- GIVEN the same P
- WHEN resolve is called with empty texto
- THEN the request MUST be rejected
- AND the stamp MUST stay null

#### Scenario: Depósito-only writer rejected

- GIVEN actor A holds only `deposito.recibir_mercaderia`, is not responsable, and lacks `administracion.gestionar_ordenes_compra`
- WHEN A POSTs resolve with nonempty texto
- THEN HTTP 403
- AND the stamp MUST stay null

#### Scenario: Responsable or OC-admin may resolve

- GIVEN actor R is responsable or holds `administracion.gestionar_ordenes_compra`
- WHEN R POSTs resolve with nonempty texto
- THEN the request MUST succeed

### Requirement: Eje split for con_faltantes

`eje_procesal` MUST map `estado=con_faltantes` + null `faltantes_resuelto_en` → `faltantes_sin_res`, and stamp set → `faltantes_con_res`. The display label for `faltantes_con_res` MUST be “Faltantes con resolución”.

#### Scenario: Unresolved maps to faltantes_sin_res

- GIVEN estado=`con_faltantes` and null stamp
- WHEN eje is evaluated
- THEN eje MUST be `faltantes_sin_res`

#### Scenario: Stamp maps to faltantes_con_res

- GIVEN estado=`con_faltantes` and stamp set
- WHEN eje is evaluated
- THEN eje MUST be `faltantes_con_res`
- AND the UI label MUST be “Faltantes con resolución”

## MODIFIED Requirements

### Requirement: REQ-EC-005 — Filter tabs: 5 tabs mapping to correct states

The deposit reception UI MUST display five filter tabs. Tab queries MUST use `eje_procesal` (not financial `estado` alone) for faltantes/recibidos/controlados:

| Tab label | Filter |
|---|---|
| Por recibir | `por_recibir` (`pagado` default; optional CC toggle) |
| Recibidos | `recibido` only |
| Con faltantes | `faltantes_sin_res` only |
| Faltantes con resolución | `faltantes_con_res` only |
| Controlados | `controlado` |

(Previously: Recibidos mixed `recibido` + `faltantes_con_res`; no dedicated resolved tab.)

#### Scenario: "Por recibir" tab shows only pagado pedidos

- GIVEN pedidos P1 (pagado), P2 (recibido), P3 (controlado), P4 (con_faltantes)
- WHEN the user activates the "Por recibir" tab with CC toggle off
- THEN only P1 MUST appear in the list

#### Scenario: "Recibidos" tab shows only recibido

- GIVEN P-rec (`recibido`) and P-con (`faltantes_con_res`)
- WHEN the user activates the "Recibidos" tab
- THEN only P-rec MUST appear

#### Scenario: "Faltantes con resolución" tab shows only faltantes_con_res

- GIVEN P-sin (`faltantes_sin_res`) and P-con (`faltantes_con_res`)
- WHEN the user activates the "Faltantes con resolución" tab
- THEN only P-con MUST appear

#### Scenario: "Controlados" tab shows only controlado pedidos

- GIVEN the same P1–P4 above
- WHEN the user activates the "Controlados" tab
- THEN only P3 MUST appear

#### Scenario: "Con faltantes" tab shows only faltantes_sin_res

- GIVEN P-sin (`faltantes_sin_res`) and P-con (`faltantes_con_res`)
- WHEN the user activates the "Con faltantes" tab
- THEN only P-sin MUST appear

#### Scenario: Por recibir CC toggle includes cuenta corriente

- GIVEN P1 (pagado) and P-cc (cuenta corriente, not pagado)
- WHEN Por recibir is active and the CC toggle is on
- THEN P1 and P-cc MUST appear
