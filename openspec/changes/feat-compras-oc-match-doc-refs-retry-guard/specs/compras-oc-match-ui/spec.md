# Delta for compras-oc-match-ui

## ADDED Requirements

### Requirement: Retry checkbox for Factura/s and Pedido/s

When Reintentar is shown, TabOcMatch MUST show a checkbox labeled exactly `También actualizar Factura/s y Pedido/s`. The checkbox MUST default unchecked and MUST reset when the selected job changes. Checking it MUST send `refrescar_doc_refs=true` with retry. Unchecked MUST send false or omit as false. The checkbox MUST NOT appear when Reintentar is hidden (view-only or non-retryable). Retry visibility and permisos MUST stay unchanged.

#### Scenario: Checkbox shown only with Reintentar

- GIVEN a retryable `error` job and a user who can gestionar
- WHEN they open the job
- THEN Reintentar and the locked-label checkbox are shown
- AND the checkbox is unchecked

#### Scenario: View-only hides checkbox

- GIVEN a retryable `error` job and a view-only user
- WHEN they open the job
- THEN neither Reintentar nor the checkbox is shown

#### Scenario: Checked retry forwards the flag

- GIVEN the checkbox is checked
- WHEN the operator clicks Reintentar
- THEN retry is called with `refrescar_doc_refs` true

#### Scenario: Unchecked retry stays false

- GIVEN the checkbox is left unchecked
- WHEN the operator clicks Reintentar
- THEN retry is called with `refrescar_doc_refs` false
