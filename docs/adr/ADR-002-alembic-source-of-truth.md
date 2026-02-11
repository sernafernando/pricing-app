# ADR-002 - Alembic as Schema Source of Truth

Status: Accepted
Date: 2026-02-10

## Context

The repository contains multiple SQL/migration locations, which increases drift risk and weakens rollback safety.

## Decision

- Alembic is the mandatory mechanism for all new schema changes.
- Manual SQL scripts can exist for reference or one-off analysis, but not as primary schema evolution path.
- Schema-changing PRs must include migration and rollback notes.

## Consequences

- Stronger migration traceability and rollback confidence.
- Requires discipline to avoid quick manual DB hotfixes.

## Follow-up

- Publish migration policy in backend docs.
- Mark legacy SQL folders as legacy/reference where applicable.
