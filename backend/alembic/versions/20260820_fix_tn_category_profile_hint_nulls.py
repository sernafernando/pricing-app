"""Fix `uq_tn_category_profile_hint` not deduping NULL `subcategoria` (defect)

`uq_tn_category_profile_hint` (added by `20260818_add_tn_publisher_tables`)
is a plain `UNIQUE (categoria, subcategoria, profile_id)` constraint.
Postgres treats every NULL as DISTINCT for uniqueness purposes, so two
rows with `subcategoria IS NULL` (the category-only hint case) never
collide on the constraint — the DB does not actually dedupe that case at
all. `tn_publish_service._upsert_category_profile_hint` works around this
in Python (query-then-update before insert), but the constraint itself was
still wrong, and any OTHER writer would duplicate.

Fix: recreate the constraint with `NULLS NOT DISTINCT` (Postgres 15+,
verified against this deployment's Postgres 18 — `sa.UniqueConstraint(...,
postgresql_nulls_not_distinct=True)` is supported by the pinned
SQLAlchemy 2.0.23/Alembic 1.12.1, verified by compiling the DDL locally
before writing this migration). A partial unique index was considered as
the SQLAlchemy-version-compatibility fallback, but is NOT needed here
since `postgresql_nulls_not_distinct` compiles correctly.

Safety on a table that may already hold duplicates (this is exactly the
gap the Python workaround was covering for — duplicates ARE plausible):
before adding the new constraint, dedupe existing rows first, keeping the
row with the highest `uso_count` (tie-broken by lowest `id`), and SUMMING
the `uso_count` of every row being removed into the survivor so usage
history is not silently lost.

Revision ID: 20260820_fix_tn_category_profile_hint_nulls
Revises: 20260818_add_tn_publisher_tables
Create Date: 2026-08-20 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260820_fix_tn_category_profile_hint_nulls"
down_revision = "20260818_add_tn_publisher_tables"
branch_labels = None
depends_on = None


def upgrade():
    # 1) Dedupe existing rows BEFORE the new constraint can reject a
    #    duplicate insert. For every (categoria, subcategoria, profile_id)
    #    key (NULLS treated as equal here, unlike the old constraint), keep
    #    the row with the highest uso_count (ties -> lowest id), sum every
    #    other row's uso_count into the survivor, then delete the losers.
    op.execute("""
        WITH ranked AS (
            SELECT
                id,
                categoria,
                subcategoria,
                profile_id,
                uso_count,
                ROW_NUMBER() OVER (
                    PARTITION BY categoria, subcategoria, profile_id
                    ORDER BY uso_count DESC, id ASC
                ) AS rn
            FROM tn_category_profile_hint
        ),
        survivors AS (
            SELECT id, categoria, subcategoria, profile_id
            FROM ranked
            WHERE rn = 1
        ),
        losers_sum AS (
            SELECT
                s.id AS survivor_id,
                COALESCE(SUM(r.uso_count), 0) AS extra_uso_count
            FROM survivors s
            JOIN ranked r
                ON r.categoria = s.categoria
                AND (r.subcategoria IS NOT DISTINCT FROM s.subcategoria)
                AND r.profile_id = s.profile_id
                AND r.rn > 1
            GROUP BY s.id
        )
        UPDATE tn_category_profile_hint t
        SET uso_count = t.uso_count + losers_sum.extra_uso_count
        FROM losers_sum
        WHERE t.id = losers_sum.survivor_id;
    """)

    op.execute("""
        DELETE FROM tn_category_profile_hint t
        WHERE t.id NOT IN (
            SELECT DISTINCT ON (categoria, subcategoria, profile_id) id
            FROM tn_category_profile_hint
            ORDER BY categoria, subcategoria, profile_id, uso_count DESC, id ASC
        );
    """)

    # 2) Recreate the constraint with NULLS NOT DISTINCT so Postgres itself
    #    dedupes the category-only (subcategoria IS NULL) case, closing the
    #    gap the Python-side query-then-update workaround was covering for.
    op.drop_constraint("uq_tn_category_profile_hint", "tn_category_profile_hint", type_="unique")
    op.create_unique_constraint(
        "uq_tn_category_profile_hint",
        "tn_category_profile_hint",
        ["categoria", "subcategoria", "profile_id"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade():
    op.drop_constraint("uq_tn_category_profile_hint", "tn_category_profile_hint", type_="unique")
    op.create_unique_constraint(
        "uq_tn_category_profile_hint",
        "tn_category_profile_hint",
        ["categoria", "subcategoria", "profile_id"],
    )
    # Deliberately NOT reversing the dedup: the merged rows (summed
    # uso_count) cannot be un-merged without losing information either way,
    # and re-fragmenting a correctly-deduped usage count on downgrade would
    # be actively wrong, not neutral.
