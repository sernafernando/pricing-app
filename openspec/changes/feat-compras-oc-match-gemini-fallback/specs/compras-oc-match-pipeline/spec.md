# Delta for compras-oc-match-pipeline

## MODIFIED Requirements

### Requirement: Async extract with 3-key Gemini pool

The worker MUST run extract → match → excel → persist in its own database session. Gemini MUST use a three-key pool and MUST NOT run inside the upload request. On 429 the pool MUST rotate unused keys on the current model and MUST NOT sleep. When every key has returned 429, the pool MUST switch once to the configured fallback model, reset the key index, clear cuota/demanda sets, and continue; if fallback is disabled or already active it MUST raise. On 503 the pool MUST mark the key seen, sleep at most twice on that key (5s then 10s), then rotate; when every key has been seen on 503 or the attempt budget is exhausted, it MUST fallback once or raise. `generate_json` MUST default to 12 attempts per call across both models. After strip, empty or primary-equal fallback MUST disable fallback. Fallback MUST persist on the pool instance for later calls in the same job. Logs MUST include model id and key N/M and MUST NOT include key material.

(Previously: single model; 429 and 503 treated alike; 503 used 15×(n+1) sleep on the same key with default 8 attempts.)

#### Scenario: Pipeline runs after enqueue

- GIVEN a `queued` PDF job
- WHEN the background worker starts
- THEN extract, match, excel, and persist run outside the upload request
- AND Gemini uses the 3-key pool (429 rotates; 503 short-sleep-then-rotate)

#### Scenario: 429 exhausts primary then fallback

- GIVEN a pool with multiple keys and a distinct fallback model
- WHEN every key returns 429 on the primary
- THEN the pool switches once to the fallback, resets the key index, and continues
- AND no sleep occurs on 429

#### Scenario: 429 on fallback or disabled raises

- GIVEN the pool is already on fallback, or fallback is empty or equal to primary
- WHEN every key returns 429
- THEN `generate_json` raises
- AND the pool does not switch model again

#### Scenario: 503 short-sleep then rotate

- GIVEN a 503 on the current key
- WHEN that key has used fewer than two demanda sleeps
- THEN the pool sleeps 5s then 10s and retries the same key
- AND after two sleeps it rotates to another key

#### Scenario: 503 exhausts keys then fallback

- GIVEN every key has been seen on 503, or attempts are exhausted
- WHEN fallback is configured and not yet active
- THEN the pool switches once to fallback and continues
- AND if already on fallback or disabled, it raises

#### Scenario: Fallback persists on the pool instance

- GIVEN extract already switched the instance to fallback
- WHEN match calls `generate_json` on the same pool
- THEN the current model remains the fallback
- AND primary RPD is not retried

#### Scenario: Logs omit secrets

- GIVEN rotate, retry, or fallback log lines
- WHEN they are emitted
- THEN each line includes the model id and key N/M
- AND no API key material appears
