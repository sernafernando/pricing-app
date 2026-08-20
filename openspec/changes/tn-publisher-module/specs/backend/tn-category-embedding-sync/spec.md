# tn-category-embedding-sync Specification

## Purpose

Give the already-implemented, already-tested `sync_category_embeddings()` a real
trigger so `tn_category_embedding` is populated in production. No change to the
embedding logic itself.

## Requirements

### Requirement: Operator-triggerable sync endpoint

An authenticated, permissioned endpoint MUST invoke `sync_category_embeddings()` on
demand.

#### Scenario: Authorized trigger runs the sync

- GIVEN a user holding the required permission
- WHEN they call the sync trigger endpoint
- THEN `sync_category_embeddings()` executes and the response reports how many categories were embedded

#### Scenario: Unauthorized call is rejected

- GIVEN a user lacking the required permission
- WHEN they call the sync trigger endpoint
- THEN the request is rejected with `403` and the sync does not run

### Requirement: Script-reachable trigger for scheduling

A standalone script entry point MUST exist so the sync can be scheduled (cron)
independently of the HTTP endpoint.

#### Scenario: Script runs outside the request/response cycle

- GIVEN the script entry point
- WHEN it is invoked directly
- THEN it runs `sync_category_embeddings()` and exits non-zero on failure, so a cron failure is detectable

### Requirement: Production table gets populated

After the trigger runs against real category data, `tn_category_embedding` MUST
contain rows, and suggestion lookups MUST return non-empty results for categories with
matches.

#### Scenario: Table is non-empty after sync

- GIVEN `tn_category_embedding` is empty
- WHEN the sync trigger runs successfully
- THEN the table contains at least one row per distinct category/subcategory pair processed
