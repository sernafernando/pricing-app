# Delta for compras-oc-match-jobs

## ADDED Requirements

### Requirement: Retry refrescar_doc_refs flag

`POST /oc-match/jobs/{job_id}/retry` MUST accept optional body `OcMatchRetryRequest` with `refrescar_doc_refs: bool = False`. A missing body MUST retry as False (empty POST MUST NOT 422). Retry MUST still require `administracion.gestionar_ordenes_compra` and MUST 409 if the job is not `error` after reclaim. `queue_retry` MUST clear `doc_refs_aplicado_at` only when the flag is True. Default retry MUST leave the stamp unchanged. Background enqueue MUST keep `process_oc_match_job(job_id)` with no extra argument. List/detail MUST NOT be required to expose the stamp.

#### Scenario: Empty POST retries without clearing stamp

- GIVEN an `error` job whose stamp is set
- WHEN retry is POSTed with no body
- THEN the job becomes `queued`
- AND `doc_refs_aplicado_at` stays set

#### Scenario: Flag true clears stamp

- GIVEN an `error` job whose stamp is set
- WHEN retry is POSTed with `refrescar_doc_refs=true`
- THEN the job becomes `queued`
- AND `doc_refs_aplicado_at` is null

#### Scenario: View-only retry still 403

- GIVEN a view-only user and a retryable `error` job
- WHEN they POST retry with or without the flag
- THEN the API returns 403
