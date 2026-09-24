# Delta for compras-factura-documentos

## ADDED Requirements

### Requirement: OC-match MUST NOT create factura rows from NC/ND

OC-match persist MUST NOT insert a `pedido_factura_documentos` row when normalized `tipo_documento` is `nota_credito` or `nota_debito`. Only `factura` papers MAY create factura rows via Match. `pedido`, `nota_venta`, and `proforma` MUST remain pedido-token write-back only.

#### Scenario: NC does not create a factura row

- GIVEN a pedido with zero factura rows
- WHEN OC-match persist runs for `tipo_documento=nota_credito` with nonempty `nro_documento`
- THEN no `pedido_factura_documentos` row MUST be created
- AND factura cargada MUST stay false

#### Scenario: ND does not create a factura row

- GIVEN a pedido with zero factura rows
- WHEN OC-match persist runs for `tipo_documento=nota_debito` with nonempty `nro_documento`
- THEN no `pedido_factura_documentos` row MUST be created
- AND `facturas_documento` MUST stay unchanged

#### Scenario: Factura persist still creates constancia

- GIVEN a pedido with zero factura rows
- WHEN OC-match persist runs for `tipo_documento=factura` with number `FA-10`
- THEN a constancia row for `FA-10` MUST exist
- AND `cargada` MUST stay false
