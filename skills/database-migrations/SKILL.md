---
name: database-migrations
description: >
  Safe Alembic + PostgreSQL migration patterns for Pricing App: concurrent indexes, safe columns, backfills, heads.
  Trigger: When writing an Alembic migration, adding a column or index to a large table, a data backfill, or fixing multiple heads.
license: MIT
metadata:
  author: pricing-app
  version: "1.0.0"
  scope: [backend, root]
  auto_invoke:
    - "Writing Alembic migrations (indexes, columns, backfills, heads)"
allowed-tools: Read, Edit, Write, Glob, Grep, Bash
---

# Database Migrations (Alembic + PostgreSQL)

> Adapted from ECC `skills/database-migrations/SKILL.md` (MIT, Copyright (c) 2026 Affaan Mustafa),
> source commit `b38be6a7f6350964d59328b52f0624e1d1d552d1`.

Complements `pricing-app-backend` (naming, model + migration basics). This skill covers making the
migration safe on a live database.

## Core Principles

1. **Every schema change is an Alembic revision** in `backend/alembic/versions/`. Never alter the
   database by hand, and never add new files to the legacy `backend/migrations/` SQL folder.
2. **Fix forward in production.** Write a real `downgrade()`, but a mistake that already ran is
   fixed with a new revision. A downgrade may refuse when it would lose data (see
   `20261229_publicacion_color`, whose downgrade refuses while a publication is painted).
3. **Deployed revisions are immutable.** Never edit a revision that ran in production.
4. **Agents do not choose `down_revision` alone.** The orchestrator owns it; ask before pushing a
   migration.
5. **Size matters.** A migration that works on 100 rows may lock on millions. Agents have no
   production access, so reason about table size and use `lock_timeout` (below).

## Safety Checklist

- [ ] `upgrade()` and `downgrade()` both exist (or the downgrade refuses on purpose, with a message)
- [ ] No long locks on large, written tables: indexes built `CONCURRENTLY`
- [ ] New columns are nullable or have a constant default (never `NOT NULL` without default)
- [ ] Large backfills are not in the same transaction as the DDL
- [ ] A real-Postgres test in `backend/tests/migrations/` runs the upgrade and downgrade
- [ ] `alembic heads` shows one head

## Adding a Column Safely

```python
# GOOD: nullable, no rewrite
op.add_column("some_table", sa.Column("new_col", sa.Text(), nullable=True))

# GOOD: constant default (Postgres 11+ adds it without rewriting the table)
op.add_column("some_table", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))

# BAD: NOT NULL without default on an existing table fails on existing rows
op.add_column("some_table", sa.Column("new_col", sa.Text(), nullable=False))
```

To end with `NOT NULL`: add nullable, backfill, then add the constraint in a later revision.

## Adding an Index Without Blocking Writes

A plain `CREATE INDEX` blocks writes for the whole build. `CONCURRENTLY` does not, but it cannot run
inside a transaction, and `backend/alembic/env.py` runs every migration inside
`context.begin_transaction()`. Our pattern (`20261228_ml_pay_ops_coupon_idx`,
`20261011_ml_items_last_trigger_index`):

```python
_INDEX = "ix_ml_payments_ops_coupon_order_id"

def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            invalid = op.get_bind().execute(sa.text(
                "SELECT NOT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = :name AND n.nspname = current_schema()"
            ), {"name": _INDEX}).scalar()
            if invalid:
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
                       "ON ml_payments_ops (order_id) WHERE coupon_amount > 0")
        finally:
            op.execute("RESET lock_timeout")
```

Why each piece:

- **Own revision**: `autocommit_block()` commits what the upgrade ran before it; a failed build next
  to other DDL would leave that DDL committed and the revision unrerunnable.
- **`lock_timeout`**: a build waiting behind a long write transaction fails in seconds instead of
  holding the deploy; a rerun builds it again.
- **Invalid leftover check**: a cancelled `CONCURRENTLY` build leaves an INVALID index that
  `IF NOT EXISTS` alone would accept.
- `downgrade()` uses `DROP INDEX CONCURRENTLY IF EXISTS` in the same block.

Worked example: `tb_mercadolibre_orders_header.ml_pack_id` has no index, and
`backend/app/services/rma_operaciones.py` (`resolver_operaciones`) searches it with an `OR` over
`mlorder_id`, `ml_id`, `ml_pack_id`. Postgres can combine per-column indexes for an `OR` (bitmap OR)
only when every branch is indexed; one unindexed branch means a sequential scan. The fix is a
`CONCURRENTLY` index on `ml_pack_id` in its own revision, following the pattern above.

## Data in Migrations

The source rule "never mix DDL and DML in one migration" does not match this repo: small seeds ship
with their table (`20261220_gestion_full_unidades_caja` creates the table and seeds its permissions).
Our rule instead:

- **Small, bounded seeds** (permissions, catalog rows): same revision as the DDL is fine.
- **Large backfills** (rows proportional to a big table): own revision, batched, so one failure does
  not roll back the schema and no single transaction locks the table. A `DO $$ ... COMMIT ... $$`
  loop cannot commit inside Alembic's transaction; batch inside an `autocommit_block()` instead.

```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        while True:
            updated = op.get_bind().execute(sa.text(
                "UPDATE some_table SET new_col = lower(old_col) WHERE id IN "
                "(SELECT id FROM some_table WHERE new_col IS NULL LIMIT 10000 FOR UPDATE SKIP LOCKED)"
            )).rowcount
            if updated == 0:
                break
```

## Renaming or Removing a Column (expand-contract)

Never rename in place on a live table: the running app still reads the old name.

1. Expand: add the new column (nullable). Deploy code that writes both.
2. Backfill existing rows (own revision if large).
3. Deploy code that reads only the new column.
4. Contract: drop the old column in a later revision.

Removing: remove every code reference first, deploy, then drop the column in the next revision.

## Multiple Heads

Two PRs that chain on the same head and merge in the same window leave two heads, and
`alembic upgrade head` refuses. We fix it with an empty merge revision naming both parents
(`merge_heads_20261114_ads_permiso_sell_in_bonos.py`), with a docstring saying which PRs collided.
Migration tests assert one head (`backend/tests/migrations/test_migration_combo_componentes_postgres.py`,
`test_single_head_descends_from_this_revision`).

## PgBouncer

Alembic connects directly (`DATABASE_URL_DIRECT`), never through PgBouncer, which runs in
`pool_mode = transaction` (`backend/pgbouncer.ini.example`). See `backend/alembic/env.py`.

## Anti-Patterns

| Anti-pattern | Why it fails | Instead |
|---|---|---|
| Manual SQL in production | No audit trail, unrepeatable | Alembic revision |
| Editing a deployed revision | Drift between environments | New revision |
| `NOT NULL` without default | Fails or rewrites existing rows | Nullable, backfill, constrain |
| Plain `CREATE INDEX` on a written table | Blocks writes during build | `CONCURRENTLY` in `autocommit_block()` |
| `CONCURRENTLY` next to other DDL | Partial commit on failure | Own revision |
| Large backfill in the DDL transaction | Long locks, all-or-nothing | Own batched revision |
| Dropping a column before removing code | App errors on missing column | Remove code, deploy, then drop |

## Commands

```bash
cd backend
alembic heads                 # must print one head
alembic history -r -3:        # recent chain
alembic merge -m "merge heads" <rev_a> <rev_b>
# Migration tests run on the server, only the touched file:
/mnt/kingston/sistema/dev/handoffs/run_tests.sh backend tests/migrations/test_migration_<name>_postgres.py
```
