# Delta for recepcion-estados

## ADDED Requirements

### Requirement: Resolve faltantes stamps at most once

`POST /pedidos/{id}/faltantes/resolver` MUST stamp `faltantes_resuelto_en` only when that stamp is still null and `estado` is `con_faltantes`. A concurrent or later resolve MUST be rejected (HTTP 409). Financial `estado` MUST stay `con_faltantes`. Writers, required `texto`, and depósito-only 403 MUST stay unchanged.

#### Scenario: First resolve stamps

- GIVEN P.estado=`con_faltantes` and `faltantes_resuelto_en` is null
- WHEN a writer POSTs resolve with nonempty texto
- THEN `faltantes_resuelto_en` MUST be set
- AND P.estado MUST remain `con_faltantes`

#### Scenario: Lost race or re-resolve rejected

- GIVEN two resolves for the same P while the stamp is still null, or a second POST after a stamp
- WHEN the second persist runs
- THEN the system MUST respond HTTP 409
- AND exactly one stamp MUST exist
- AND a second G31 MUST NOT be emitted
