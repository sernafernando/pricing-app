# Delta for compras-oc-match-pipeline

## ADDED Requirements

### Requirement: Mid-flight progress_phase between stages

The worker MUST persist `progress_phase` in a short background database session between extract, match, and excel. Allowed values MUST be `extracting`, `matching`, and `excel`. The worker MUST NOT hold a database session during Gemini calls. The Gemini pool MUST NOT write job progress or heartbeats. If a phase write fails, the pipeline MUST continue. On successful persist, `progress_phase` MUST be cleared to null. Phase writes MUST NOT change job `status`.

#### Scenario: Phase is written between stages

- GIVEN a claimed `running` job about to extract, then match, then excel
- WHEN the worker enters each stage
- THEN `progress_phase` is persisted as `extracting`, then `matching`, then `excel`
- AND `status` remains `running`

#### Scenario: No session during Gemini and no pool heartbeat

- GIVEN the worker is inside a Gemini generate call
- WHEN that call runs, including 503 backoff sleep
- THEN no database session is held
- AND `gemini_pool` does not write `progress_phase` or any job heartbeat

#### Scenario: Phase write failure is fail-soft

- GIVEN a phase persist fails
- WHEN extract, match, or excel would continue
- THEN the pipeline continues
- AND job correctness does not depend on the phase row

#### Scenario: Persist clears progress_phase

- GIVEN a job finishing excel with a non-null `progress_phase`
- WHEN persist completes successfully
- THEN `progress_phase` is null
