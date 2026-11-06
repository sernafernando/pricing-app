---
name: postgres-patterns
description: >
  PostgreSQL query, index, and schema patterns for Pricing App, plus the database review checklist.
  Trigger: When writing SQL or SQLAlchemy queries, choosing indexes, reviewing DB code, or a query is slow.
license: MIT
metadata:
  author: pricing-app
  version: "1.0.0"
  scope: [backend, root]
  auto_invoke:
    - "Writing or reviewing SQL/SQLAlchemy queries and indexes"
allowed-tools: Read, Edit, Write, Glob, Grep, Bash
---

# PostgreSQL Patterns

> Adapted from ECC `skills/postgres-patterns/SKILL.md` and `agents/database-reviewer.md`
> (MIT, Copyright (c) 2026 Affaan Mustafa), source commit `b38be6a7f6350964d59328b52f0624e1d1d552d1`.
> ECC credits Supabase Agent Skills (MIT) for the underlying patterns.

For index and column changes on live tables, also load `database-migrations`.

## Index Cheat Sheet

| Query pattern | Index | Example |
|---|---|---|
| `WHERE col = value` / `col > value` | B-tree (default) | `CREATE INDEX idx ON t (col)` |
| `WHERE a = x AND b > y` | Composite, equality first | `CREATE INDEX idx ON t (a, b)` |
| Only a small subset is queried | Partial | `ON ml_payments_ops (order_id) WHERE coupon_amount > 0` |
| `WHERE jsonb_col @> '{...}'` | GIN | `CREATE INDEX idx ON t USING gin (col)` |
| Append-only time ranges | BRIN | `CREATE INDEX idx ON t USING brin (col)` |

- **Index foreign keys and filter columns** (already a `pricing-app-backend` rule).
- **`OR` across columns** needs every branch indexed, or Postgres falls back to a sequential scan.
  Worked example: `resolver_operaciones` in `backend/app/services/rma_operaciones.py` ORs
  `mlorder_id`, `ml_id` (indexed) with `ml_pack_id` (not indexed) on
  `tb_mercadolibre_orders_header`.
- **Covering index**: `INCLUDE (col)` avoids the table lookup for read-only columns.

## Data Types

The source's "always bigint / text / timestamptz" is rewritten: existing tables mix `Integer` and
`BigInteger` ids, `String(n)` and `Text`, naive and `timezone=True` `DateTime`. Changing an existing
column type is a persisted-format change, not a review nit.

- New columns: follow the convention of the table and of the column you join against
  (`ml_pack_id` is `String(50)` in `mercadolibre_order_header.py` but `BigInteger` in `venta_ml.py`;
  joining them needs a cast, which also defeats the index).
- Money: `Numeric`, never `Float` for new columns (some legacy columns, e.g. `offset_ganancia.monto`,
  are `Float`; don't copy them).
- Flags: `Boolean`, not `String`/`Integer`.

## Common Patterns

**UPSERT** (SQLAlchemy `on_conflict_do_update`, used across `app/services/`, e.g.
`ml_item_override_service.py`):

```sql
INSERT INTO t (a, b, v) VALUES (:a, :b, :v)
ON CONFLICT (a, b) DO UPDATE SET v = EXCLUDED.v;
```

**Queue claim with SKIP LOCKED** (`app/services/promo_refresh_drain.py`,
`catalog_competition_refresh_queue.py`): each row is claimed in a short session with
`.with_for_update(skip_locked=True)`, so parallel workers never block on the same row.

**Cursor pagination** on large tables: `WHERE id > :last_id ORDER BY id LIMIT :n` instead of a
growing `OFFSET`, which reads and discards every skipped row.

## Connections and Transactions

- The app reaches Postgres through PgBouncer in `pool_mode = transaction`
  (`backend/pgbouncer.ini.example`). Startup parameters in `connect_args` are rejected, so
  `statement_timeout` and `idle_in_transaction_session_timeout` are set on every pool checkout
  (`backend/app/core/database.py`). Don't move them to `connect_args`.
- **Short transactions; never hold a session across an external HTTP call** (ML, ERP). The
  `database.py` note on pool sizing names this as the real fix for pool exhaustion.
- Consistent lock ordering (`ORDER BY id FOR UPDATE`) when locking several rows, to avoid deadlocks.
- Sessions use `autoflush=False`; tests against real Postgres must too.

## Review Checklist

Folded in from ECC `database-reviewer` (a project agent cannot be committed: `.claude/` is ignored).

- [ ] WHERE/JOIN columns indexed; every `OR` branch indexed
- [ ] Composite indexes: equality columns first, then range
- [ ] No N+1: no query per row inside a loop; use `IN (...)` or a join (`resolver_operaciones`
      does two queries for any number of values)
- [ ] Batch inserts (multi-row insert / bulk), not one `INSERT` per row in a loop
- [ ] Only the needed columns selected on large tables (no `SELECT *` in raw SQL)
- [ ] Raw SQL uses bound parameters (`text("... WHERE mlo.ml_pack_id = :pack_id")`,
      `backend/app/routers/seriales_traza_ml.py`), never f-strings with user input
- [ ] Join columns have the same type (no implicit casts)
- [ ] Money in `Numeric`
- [ ] Transactions short; no session held during external calls
- [ ] `EXPLAIN ANALYZE` on complex queries when the data is available (agents have no production
      access; ask the orchestrator)

## Diagnostic Queries

Run only with production access authorized by the owner through the orchestrator.

```sql
-- Unindexed foreign keys
SELECT conrelid::regclass, a.attname
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
WHERE c.contype = 'f'
  AND NOT EXISTS (SELECT 1 FROM pg_index i
                  WHERE i.indrelid = c.conrelid AND a.attnum = ANY(i.indkey));

-- Dead tuples (bloat)
SELECT relname, n_dead_tup, last_autovacuum
FROM pg_stat_user_tables WHERE n_dead_tup > 1000 ORDER BY n_dead_tup DESC;

-- Slow queries (only if the pg_stat_statements extension is installed)
SELECT query, mean_exec_time, calls FROM pg_stat_statements
ORDER BY mean_exec_time DESC LIMIT 10;
```
