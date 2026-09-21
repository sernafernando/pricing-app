# Delta for compras-oc-match-jobs

## ADDED Requirements

### Requirement: progress_phase and pedido_numero on job API

The job row MUST store nullable `progress_phase` with values `extracting`, `matching`, or `excel` only. The status CHECK MUST remain `queued|running|done|error|skipped`. List and detail MUST `joinedload` `OcMatchJob.pedido`, expose `pedido_numero` from `PedidoCompra.numero`, and MUST keep `pedido_id`. A missing pedido MUST yield `pedido_numero` null without failing the response. Retry and reclaim MUST clear `progress_phase` to null.

#### Scenario: Running job exposes phase without new status

- GIVEN a `running` job between extract and match
- WHEN list or detail is requested
- THEN `progress_phase` is `extracting`, `matching`, or `excel`
- AND `status` is still `running`

#### Scenario: List and detail include pedido_numero and pedido_id

- GIVEN a job whose pedido has `numero` `OC-100`
- WHEN list or detail is requested
- THEN the payload includes `pedido_numero` `OC-100`
- AND includes `pedido_id`

#### Scenario: Missing pedido yields null numero

- GIVEN a job whose pedido cannot be loaded
- WHEN list or detail is requested
- THEN `pedido_numero` is null
- AND the response still succeeds with `pedido_id`

## MODIFIED Requirements

### Requirement: Idempotency and 45-minute reclaim

Jobs MUST be unique on `(pedido_id, attachment_id)`. A new adjunto MUST create a new job. The same adjunto with an existing `done` or `running` job MUST reuse or skip that job. Reclaim MUST use a `started_at` clock with `RECLAIM_AFTER = 45 minutes`. List and detail MUST present a job `running` longer than 45 minutes as retryable `error`. A job `running` for 15 minutes on `started_at` MUST remain `running`. Reclaim MUST NOT use `updated_at`. Reclaim MUST NOT depend on a gemini_pool heartbeat.
(Previously: Stale reclaim was 15 minutes on `started_at`; live 15-minute jobs were presented as retryable `error`.)

#### Scenario: Same adjunto reuses; new file is a new job

- GIVEN a `done` job for `(pedido_id, attachment_id)`
- WHEN the same adjunto is processed again
- THEN no second job is created and the existing job is returned
- WHEN a different adjunto is uploaded on the same pedido
- THEN a distinct job is created

#### Scenario: Stale running becomes retryable error

- GIVEN a job has been `running` for more than 45 minutes on `started_at`
- WHEN list or detail is requested
- THEN the job is presented as retryable `error`

#### Scenario: Live 15-minute job is not reclaimed

- GIVEN a job has been `running` for 15 minutes on `started_at`
- WHEN list, detail, or the reclaim sweep runs
- THEN the job remains `running`
- AND is not presented as retryable `error`

## RENAMED Requirements

### Requirement: Idempotency and 15-minute reclaim → Idempotency and 45-minute reclaim

(Reason: Locked reclaim window is 45 minutes on `started_at`; the heading must match the contract.)
(Migration: Update parent jobs spec heading, `STALE_MESSAGE`, reclaim tests, and docs that cite 15-minute reclaim.)
