# Delta for compras-oc-match-pipeline

## ADDED Requirements

### Requirement: Extract-only doc-refs refresh persist

A dedicated refresh MUST re-run extract only (`extract_one`) because extract JSON is not stored on the job, and MUST NOT persist extract JSON. Execution MUST use a two-session background path: load adjunto bytes and confirm `status` is still `done` or `error`, close the session, extract with no Session, then persist only if extract succeeded. On successful extract the persist session MUST set `doc_refs_aplicado_at` to null immediately before write-back, `SELECT FOR UPDATE` the pedido, call unchanged `apply_writeback` (append-unique), and restamp if routeable. Failed extract MUST leave stamp, job, and pedido unchanged. Persist MUST no-op if `status` is no longer `done` or `error`. The path MUST NOT rematch, MUST NOT regenerate Excel, MUST NOT mutate job `status`, renglones, acta, `excel_rel_path`, or `progress_phase`, and MUST NOT flip the job to `queued` or `running`. An `error` job MUST stay `error`. The path MUST NEVER write `numero_factura`. The path MUST NOT emit alerts or notifications.

#### Scenario: Successful extract clears stamp then write-back

- GIVEN a `done` or `error` job and extract succeeds with routeable numbers
- WHEN refresh persist runs
- THEN `doc_refs_aplicado_at` is cleared immediately before `apply_writeback`
- AND `apply_writeback` appends unique tokens
- AND the job is restamped if routeable

#### Scenario: Failed extract leaves stamp and pedido

- GIVEN a stamped job and extract fails
- WHEN refresh persist would run
- THEN `doc_refs_aplicado_at` stays set
- AND job and pedido columns are unchanged

#### Scenario: Status left done or error skips persist

- GIVEN extract succeeded but the job is no longer `done` or `error`
- WHEN refresh persist runs
- THEN write-back is skipped
- AND stamp, renglones, and acta are not mutated by this path

#### Scenario: No rematch excel or status mutation

- GIVEN a `done` or `error` job
- WHEN refresh extract and persist complete
- THEN match and Excel do not run
- AND `status`, renglones, acta, `excel_rel_path`, and `progress_phase` are unchanged
- AND the job is not flipped to `queued` or `running`

#### Scenario: Error job stays error after refresh

- GIVEN an `error` job (including Excel/TC rejection that already wrote tokens)
- WHEN refresh extract and persist complete
- THEN Factura/s and Pedido/s MAY append unique tokens
- AND job `status` remains `error`

#### Scenario: Never writes numero_factura

- GIVEN a routeable refresh extract on a pedido that already has `numero_factura`
- WHEN refresh persist runs
- THEN `numero_factura` is unchanged

#### Scenario: No alerts from refresh

- GIVEN a dedicated doc-refs refresh
- WHEN extract and persist complete or fail
- THEN no alert or notification is emitted
