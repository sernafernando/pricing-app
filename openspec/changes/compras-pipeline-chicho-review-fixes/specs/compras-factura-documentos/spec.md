# Delta for compras-factura-documentos

## ADDED Requirements

### Requirement: OC Match writeback inserts factura rows as constancia

When OC Match persists a factura document number, the system MUST insert a `pedido_factura_documentos` row in the same write transaction as the `facturas_documento` token writeback. The insert MUST use the shared factura-alta path (same identity as manual alta). Case-insensitive duplicates MUST be skipped. The row MUST be **constancia only**: `cargada` MUST stay false. The system MUST NOT emit a factura-cargada alert from this insert. The system MUST NOT emit a missing-factura / falta-factura signal solely because Match wrote a token.

(Previously in this change: insert implied “factura MUST be cargada” and the chip MUST be on. Gabe 2026-09-23: that is wrong.)

#### Scenario: Match writeback stores constancia without cargada

- GIVEN a pedido with zero factura rows
- WHEN OC Match writeback persists factura number `FA-10`
- THEN a `pedido_factura_documentos` row for `FA-10` MUST exist on that pedido
- AND that row’s `cargada` MUST be false
- AND the factura-cargada chip MUST be off
- AND no `compras.factura_cargada` notification MUST be created

#### Scenario: Casefold duplicate is skipped

- GIVEN a pedido already has row `FA-10`
- WHEN OC Match writeback persists `fa-10`
- THEN no second row MUST be inserted
- AND the existing row MUST remain
- AND `cargada` MUST NOT change

#### Scenario: False missing-factura is forbidden

- GIVEN OC Match writeback just persisted `FA-10` as a row
- WHEN chips and factura-missing alerts are evaluated
- THEN a falta-factura signal MUST NOT appear for that pedido
- AND the factura-cargada chip MUST stay off until a row is marked cargada

### Requirement: Persist and manual alta do not notify

`persist_factura_documento`, OC Match persist, and manual POST alta MUST NOT call `notificar_factura_cargada`. Seed MUST NOT notify. Document-number identity is constancia.

#### Scenario: Manual alta is constancia only

- GIVEN a pedido with zero factura rows
- WHEN an operator POSTs factura number `FA-10`
- THEN a row MUST exist
- AND `cargada` MUST be false
- AND zero `compras.factura_cargada` notifications MUST exist

### Requirement: Per-factura ERP cargada check

Each factura row MUST support an independent Administración check “cargada al ERP”. The check MAY happen much later than identify/persist. NV / pedido / `pedidos_documento` tokens MUST NOT have this check. ERP `ct_transaction` / `numero_factura` MUST NOT auto-set `cargada`.

#### Scenario: Check marks one factura

- GIVEN a pedido with rows `FA-10` and `FA-11`, both unchecked
- WHEN Administración PATCHes `FA-10` to `cargada=true`
- THEN only `FA-10` MUST have `cargada` true and `cargada_marked_at` set
- AND `FA-11` MUST stay unchecked
- AND the factura-cargada chip MUST be on

#### Scenario: Uncheck clears cargada without deleting the row

- GIVEN row `FA-10` is cargada
- WHEN Administración PATCHes `cargada=false`
- THEN `cargada` MUST be false
- AND the row MUST still exist
- AND the chip MUST turn off if no other row is cargada

### Requirement: PATCH factura cargada

The system MUST expose `PATCH /pedidos/{pedido_id}/factura-documentos/{row_id}` with body `{ "cargada": bool }`. The actor MUST hold `administracion.gestionar_ordenes_compra`. Missing pedido/row MUST be 404. Missing permission MUST be 403.

#### Scenario: Check succeeds

- GIVEN an actor with `administracion.gestionar_ordenes_compra` and row `FA-10` unchecked
- WHEN they PATCH `cargada=true`
- THEN HTTP 200
- AND `cargada` MUST be true
- AND `cargada_marked_at` MUST be set
- AND `alerta_pendiente_hasta` MUST be `cargada_marked_at + 5 minutes`

#### Scenario: PATCH without permission forbidden

- GIVEN an actor without `administracion.gestionar_ordenes_compra`
- WHEN they PATCH `cargada=true`
- THEN HTTP 403
- AND `cargada` MUST stay false

### Requirement: Five-minute pending alert on check (not DELETE undo)

Checking `cargada=true` MUST start a pending in-app alert that fires only after `FACTURA_CARGADA_ALERT_DELAY` (5 minutes) if the row is still checked. Unchecking **before** fire MUST cancel the pending alert (no notification). This window MUST be keyed off `cargada_marked_at`. It MUST NOT use `created_at`. It MUST NOT delete the row.

#### Scenario: Alert fires after five minutes if still checked

- GIVEN row `FA-10` was checked at T0
- WHEN the sweep runs at T0 + 5 minutes
- THEN holders of `administracion.ver_alertas_factura` MUST receive `compras.factura_cargada`
- AND `alerta_disparada_at` MUST be set

#### Scenario: Uncheck before fire cancels pending alert

- GIVEN row `FA-10` was checked at T0
- WHEN Administración unchecks at T0 + 4 minutes
- AND the sweep runs at T0 + 6 minutes
- THEN no `compras.factura_cargada` notification MUST exist for that row
- AND the row MUST still exist

#### Scenario: Sweep before five minutes does not fire

- GIVEN row `FA-10` was checked at T0
- WHEN the sweep runs at T0 + 4 minutes 59 seconds
- THEN no notification MUST be created
- AND `alerta_pendiente_hasta` MUST remain

#### Scenario: Idempotent re-check does not reset the timer

- GIVEN row `FA-10` is already cargada with pending until T0 + 5 minutes
- WHEN Administración PATCHes `cargada=true` again at T0 + 1 minute
- THEN `cargada_marked_at` and `alerta_pendiente_hasta` MUST stay the original values

#### Scenario: Re-check after uncheck starts a new timer

- GIVEN a row was checked, unchecked before fire, then checked again at T1
- WHEN the sweep runs at T1 + 5 minutes
- THEN a factura-cargada alert MUST fire
- AND no alert MUST have fired from the first check

### Requirement: DELETE undo window stays distinct from the alert timer

Removing a just-added **constancia** row MUST remain allowed for 5 minutes from the row’s `created_at` (`FACTURA_UNDO_WINDOW`). After that window, DELETE MUST be HTTP 409. DELETE MUST cancel any pending alert for that row and MUST retract already-fired `compras.factura_cargada` notifications for that row. Uncheck MUST NOT be treated as DELETE.

#### Scenario: Undo inside five minutes from created_at

- GIVEN a row created 2 minutes ago, whether or not it is cargada
- WHEN the operator DELETEs that row
- THEN the row MUST be removed
- AND any pending alert for that row MUST be cancelled
- AND that row’s fired alerts MUST be retracted

#### Scenario: Undo after five minutes from created_at rejected

- GIVEN a row created 6 minutes ago
- WHEN the operator DELETEs that row
- THEN the system MUST reject with HTTP 409
- AND the row MUST remain
- AND a later uncheck MUST still be allowed (alert-timer path, not DELETE)

#### Scenario: Uncheck is not DELETE

- GIVEN a row created 2 minutes ago and checked
- WHEN the operator unchecks
- THEN the row MUST remain
- AND DELETE undo MUST still be available until `created_at + 5 minutes`

## MODIFIED Requirements

### Requirement: Seed from facturas_documento tokens

On migrate/backfill the system MUST seed rows by splitting existing `facturas_documento` on `;` tokens, trimming empties. Each seeded `numero` MUST be at most 100 characters. Tokens longer than 100 characters MUST be skipped and MUST be logged; they MUST NOT abort the migration. The system MUST casefold-dedupe tokens per pedido and MUST enforce UNIQUE `(pedido_id, numero)`. The migration MUST complete when overflows or duplicates are present. The raw `facturas_documento` field MUST remain. `pedidos_documento` MUST stay write-once and MUST NOT be used as factura identity. Seeded rows MUST have `cargada` false. Seed MUST NOT notify.

(Previously: seed inserted raw `;` tokens with no 100-char cap, dedupe, UNIQUE, or skip-on-overflow. This change already added those rules; this amend adds “not cargada / no notify”.)

#### Scenario: Semicolon tokens become constancia rows

- GIVEN `facturas_documento` = `A-1; A-2; ;A-3`
- WHEN seed runs
- THEN three rows MUST exist with numbers `A-1`, `A-2`, `A-3`
- AND each row’s `cargada` MUST be false
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
