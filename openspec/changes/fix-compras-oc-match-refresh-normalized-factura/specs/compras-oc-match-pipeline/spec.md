# Delta for compras-oc-match-pipeline

## ADDED Requirements

### Requirement: Refresh persist mirrors worker factura row

After a dedicated refresh persist session calls `apply_writeback` and it returns True, if `normalize_tipo(tipo_documento)` is `factura` and `token_or_none(nro_documento)` is present, the system MUST call `persist_factura_documento` on that same FOR UPDATE session with `pedido` = the locked pedido, `numero` = that token, and `created_by_id` = `int(pedido.creado_por_id)`, then MUST `flush`. The system MUST call this even when append-unique is a no-op (text column already has the token). The system MUST NOT open a second session. The system MUST NOT persist a factura row when `apply_writeback` is False, tipo is not `factura`, or `nro_documento` is empty. Extract-fail and status-left skip MUST stay unchanged. The path MUST NOT write `numero_factura` or emit alerts.

#### Scenario: Factura extract inserts normalized row

- GIVEN a refreshable job and extract `tipo_documento=factura` with nonempty `nro_documento`
- WHEN persist runs and `apply_writeback` returns True
- THEN `pedido_factura_documentos` has that number
- AND `created_by_id` equals `pedido.creado_por_id`
- AND the write used the same FOR UPDATE session

#### Scenario: Re-extract restores a deleted row

- GIVEN the text column already has the factura token and the normalized row was deleted
- WHEN refresh persist runs with the same extract
- THEN `apply_writeback` returns True
- AND the normalized row exists again

#### Scenario: Non-factura or empty number skips row

- GIVEN extract tipo is not `factura`, or `nro_documento` is empty
- WHEN persist runs
- THEN no `persist_factura_documento` write occurs

#### Scenario: Writeback false skips row

- GIVEN extract is not routeable so `apply_writeback` returns False
- WHEN persist runs
- THEN no factura row is inserted
- AND the job is not restamped

#### Scenario: Extract fail and status-left skip unchanged

- GIVEN extract fails, or job status left `done`/`error`
- WHEN refresh would persist
- THEN stamp, job, pedido text, and factura rows stay unchanged
