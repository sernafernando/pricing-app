# Delta for compras-factura-documentos

## ADDED Requirements

### Requirement: OC Match writeback inserts factura rows

When OC Match persists a factura document number, the system MUST insert a `pedido_factura_documentos` row in the same write transaction as the `facturas_documento` token writeback. The insert MUST use the shared factura-alta path (same identity as manual alta). Case-insensitive duplicates MUST be skipped. After a successful insert, factura MUST be cargada and the factura chip MUST be on. The system MUST NOT emit a missing-factura / falta-factura signal solely because Match wrote a token.

#### Scenario: Match writeback turns chip on

- GIVEN a pedido with zero factura rows
- WHEN OC Match writeback persists factura number `FA-10`
- THEN a `pedido_factura_documentos` row for `FA-10` MUST exist on that pedido
- AND factura MUST be cargada and the factura chip MUST be on

#### Scenario: Casefold duplicate is skipped

- GIVEN a pedido already has row `FA-10`
- WHEN OC Match writeback persists `fa-10`
- THEN no second row MUST be inserted
- AND the existing row MUST remain

#### Scenario: False missing-factura is forbidden

- GIVEN OC Match writeback just persisted `FA-10` as a row
- WHEN chips and factura-missing alerts are evaluated
- THEN the factura chip MUST be on
- AND a falta-factura signal MUST NOT appear for that pedido

## MODIFIED Requirements

### Requirement: Seed from facturas_documento tokens

On migrate/backfill the system MUST seed rows by splitting existing `facturas_documento` on `;` tokens, trimming empties. Each seeded `numero` MUST be at most 100 characters. Tokens longer than 100 characters MUST be skipped and MUST be logged; they MUST NOT abort the migration. The system MUST casefold-dedupe tokens per pedido and MUST enforce UNIQUE `(pedido_id, numero)`. The migration MUST complete when overflows or duplicates are present. The raw `facturas_documento` field MUST remain. `pedidos_documento` MUST stay write-once and MUST NOT be used as factura identity.

(Previously: seed inserted raw `;` tokens with no 100-char cap, dedupe, UNIQUE, or skip-on-overflow.)

#### Scenario: Semicolon tokens become rows

- GIVEN `facturas_documento` = `A-1; A-2; ;A-3`
- WHEN seed runs
- THEN three rows MUST exist with numbers `A-1`, `A-2`, `A-3`
- AND `facturas_documento` MUST stay unchanged

#### Scenario: Empty token field seeds nothing

- GIVEN `facturas_documento` is null or only separators
- WHEN seed runs
- THEN the pedido MUST have zero factura rows

#### Scenario: Overflow token is skipped

- GIVEN a token longer than 100 characters among valid tokens
- WHEN seed/migrate runs
- THEN the overflow token MUST NOT become a row
- AND the migration MUST complete
- AND the skip MUST be logged

#### Scenario: Casefold duplicates seed one row

- GIVEN `facturas_documento` = `A-1; a-1; A-1`
- WHEN seed runs
- THEN exactly one row MUST exist for that pedido
- AND UNIQUE `(pedido_id, numero)` MUST hold
