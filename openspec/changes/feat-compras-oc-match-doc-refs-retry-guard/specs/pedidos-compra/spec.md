# Delta for pedidos-compra

## ADDED Requirements

### Requirement: Documentary fields max_length 500

Create, update, and correccion input schemas MUST constrain `facturas_documento` and `pedidos_documento` with `max_length=500`. The database columns MUST remain nullable Text with no Alembic length change. Pedido create/edit and corregir inputs MUST set HTML `maxLength={500}` and MUST NOT silently slice on submit. Detalle MUST stay read-only. Operator PUT or correccion longer than 500 MUST return 422. `numero_factura` MUST stay `max_length=50`.

#### Scenario: Overlong PUT is 422

- GIVEN an operator PUT or correccion with either documentary field longer than 500
- WHEN the request is validated
- THEN the API returns 422
- AND the stored Text is unchanged

#### Scenario: Forms cap at 500

- GIVEN create/edit or corregir is open
- WHEN the operator types Factura/s or Pedido/s
- THEN each input refuses more than 500 characters
- AND submit does not truncate a value the browser already accepted
