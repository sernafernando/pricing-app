# Delta for compras-oc-match-jobs

## ADDED Requirements

### Requirement: Dedicated refresh-doc-refs endpoint

`POST /administracion/compras/oc-match/jobs/{job_id}/refresh-doc-refs` MUST accept an empty body. It MUST require `administracion.gestionar_ordenes_compra` and MUST return 403 without that permiso. After the same reclaim-and-404 helper as retry, the endpoint MUST accept only `done` or `error` and MUST return 409 for any other status, including `queued`, `running`, and `skipped`. The HTTP response MUST return immediately and MUST NOT wait for extract. The endpoint MUST NOT call `queue_retry`, MUST NOT rematch, MUST NOT regenerate Excel, and MUST NOT mutate job `status`, renglones, acta, or `excel_rel_path`. The system MUST NOT send mail or alerts on this POST. Retry `POST …/retry` (empty body or `refrescar_doc_refs`) MUST stay unchanged.

#### Scenario: Done job accepted immediately

- GIVEN a `done` job and a user who can gestionar
- WHEN they POST `refresh-doc-refs` with an empty body
- THEN the API returns immediately without waiting for extract
- AND job `status` remains `done`

#### Scenario: Error job accepted and stays error

- GIVEN an `error` job and a user who can gestionar
- WHEN they POST `refresh-doc-refs` with an empty body
- THEN the API returns immediately
- AND job `status` remains `error`

#### Scenario: 409 when queued running or skipped

- GIVEN a job whose `status` is `queued`, `running`, or `skipped`
- WHEN they POST `refresh-doc-refs`
- THEN the API returns 409
- AND `queue_retry` is not called

#### Scenario: 409 unless done or error after reclaim

- GIVEN a job that is not `done` or `error` after reclaim
- WHEN they POST `refresh-doc-refs`
- THEN the API returns 409

#### Scenario: Missing gestionar is 403

- GIVEN a view-only user and a `done` or `error` job
- WHEN they POST `refresh-doc-refs`
- THEN the API returns 403

#### Scenario: Does not rematch or mutate artifacts

- GIVEN a `done` or `error` job
- WHEN `refresh-doc-refs` is accepted
- THEN `queue_retry` is not called
- AND renglones, acta, and `excel_rel_path` are unchanged
