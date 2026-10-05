"""`v_facturas_compra_vigentes` on real Postgres: the rewrite (migration
20261005_vfactvig_lookup) returns EXACTLY what compras_014 returned, and a
lookup by `ct_transaction` (or any caller's pattern) touches only its rows.

Measured in production 2026-10-05: the compras_014 view was the top CPU
consumer. `WHERE v.ct_transaction = :ct` (erp_matching_service, once per
invoice inside the ERP sync loop) ran as a parallel query on ~3 of 4 cores,
because `base` is referenced three times (so Postgres materializes it), the
`contrapartes` CTE self-joins EVERY purchase row and the `anuladas` CTE
DISTINCTs every annulment -- a filter on the view can't reach inside them.

The OLD definition is loaded verbatim from the compras_014 migration file and
created under another name, so parity is checked against the real thing, not a
hand-copied approximation.

Dataset (committed into the shared test DB, tables dropped at teardown):
  * handcrafted rows (ct 900001..) with an explicit expected verdict each;
  * a dense block (~12k rows, few suppliers, docnumbers shared by 2-4 rows,
    sd types picked by hash) so pairs, triples, both sd_id orders, annulled
    tuples, NULL keys, 'X'/'x'/NULL kindof and mismatched comp/bra collide a lot;
  * a volume block of 600k rows (75% sales, 25% purchases with counterpart
    pairs, NCs, receipts, annulments, packing lists) for the plans/timings.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text

pytestmark = pytest.mark.postgres

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS = _BACKEND_ROOT / "alembic" / "versions"
_NEW_MIGRATION = _VERSIONS / "20261005_vista_facturas_vigentes_lookup.py"
_OLD_MIGRATION = _VERSIONS / "compras_014_vista_facturas_vigentes.py"

VIEW = "v_facturas_compra_vigentes"
OLD_VIEW = "v_facturas_compra_vigentes_old_compras014"

VOLUME_ROWS = 600_000


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _new_migration():
    return _load(_NEW_MIGRATION, "vfactvig_lookup_migration")


def _old_view_sql() -> str:
    sql = _load(_OLD_MIGRATION, "compras_014_migration").VIEW_DEFINITION
    assert f"VIEW {VIEW} AS" in sql
    return sql.replace(f"VIEW {VIEW} AS", f"VIEW {OLD_VIEW} AS")


def _run_migration(url: str, step: str) -> None:
    """The migration the way `alembic upgrade` runs it: a transactional
    connection whose `autocommit_block` steps out for CONCURRENTLY."""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = _new_migration()
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with ctx.begin_transaction(), Operations.context(ctx):
                getattr(migration, step)()
    finally:
        engine.dispose()


# ──────────────────────────────────────────────────────────────────────────
# Seed
# ──────────────────────────────────────────────────────────────────────────

# sd catalog: a subset of the real one (sd ids/flags as in production), plus
# sd 90 -- a counterpart type whose sd_id is LOWER than the invoice's, so the
# "higher sd_id is the counterpart" rule is exercised in both directions.
_SALE_DOCUMENTS = [
    # sd_id, desc, purchase, annul, packinglist, quotation, creditnote, debitnote, receipt, inbalance, taxable, +/-, hacc
    (1, "Factura venta", False, False, False, False, False, False, False, True, True, 1, None),
    (56, "Anulacion venta", False, True, False, False, False, False, False, False, False, 1, None),
    (90, "Contraparte previa FC", True, False, False, False, False, False, False, True, True, -1, 10011),
    (101, "Factura compra", True, False, False, False, False, False, False, True, True, 1, 10011),
    (102, "Remito compra", True, False, True, False, False, False, False, False, False, 1, None),
    (103, "NC compra", True, False, False, False, True, False, False, False, False, -1, 10011),
    (104, "ND compra", True, False, False, False, False, True, False, False, False, 1, None),
    (105, "Presupuesto compra", True, False, False, True, False, False, False, False, False, 1, None),
    (106, "Orden de pago", True, False, False, False, False, False, True, False, False, -1, 10012),
    (124, "Otro compra +", True, False, False, False, False, False, False, False, False, 1, None),
    (151, "Anulacion compra", True, True, False, False, False, False, False, False, False, 1, 10011),
    (161, "Contraparte FC", True, False, False, False, False, False, False, True, True, -1, 10011),
    (164, "Otro compra -", True, False, False, False, False, False, False, False, False, -1, None),
    (166, "Contraparte OP", True, False, False, False, False, False, False, False, False, 1, 10012),
]

# ct_transaction -> (sd_id, supp_id, ct_docnumber, comp_id, bra_id, ct_kindof, expected_in_view)
_HANDCRAFTED = {
    900001: (101, 9001, "H1", 1, 1, "C", True),  # plain invoice
    900002: (101, 9001, "H2", 1, 1, "C", False),  # annulled by a purchase annulment
    900003: (151, 9001, "H2", 1, 1, "C", False),  # the annulment itself
    900004: (101, 9001, "H3", 1, 1, "C", False),  # annulled by a NON-purchase annulment
    900005: (56, 9001, "H3", 1, 1, "C", False),
    900006: (101, 9001, "H4", 1, 1, "C", True),  # pair: lower sd_id stays
    900007: (161, 9001, "H4", 1, 1, "C", False),  # pair: higher sd_id is the counterpart
    900008: (90, 9001, "H5", 1, 1, "C", True),  # pair, other order: the -1 row is the lower sd_id
    900009: (101, 9001, "H5", 1, 1, "C", False),
    900010: (101, 9001, "H6", 1, 1, "C", True),  # different bra_id: not a pair
    900011: (161, 9001, "H6", 1, 2, "C", True),
    900012: (90, 9001, "H7", 1, 1, "C", True),  # triple
    900013: (101, 9001, "H7", 1, 1, "C", False),  # counterpart of 90
    900014: (161, 9001, "H7", 1, 1, "C", False),  # counterpart of 101 (101 is in base even if excluded)
    900015: (124, 9001, "H8", 1, 1, "C", True),  # NULL hacc_group: never a pair
    900016: (164, 9001, "H8", 1, 1, "C", True),
    900017: (101, 9001, "H9", 1, 1, "X", False),  # kindof 'X'
    900018: (101, 9001, "H10", 1, 1, None, True),  # kindof NULL
    900019: (101, 9001, "H11", 1, 1, "x", True),  # 'x' <> 'X'
    900020: (102, 9001, "H12", 1, 1, "C", False),  # packing list
    900021: (105, 9001, "H13", 1, 1, "C", False),  # quotation
    900022: (101, None, "H14", 1, 1, "C", False),  # NULL supp_id
    900023: (101, 9001, None, 1, 1, "C", False),  # NULL ct_docnumber
    900024: (101, 9001, "H15", 1, 1, "X", False),  # 'X' leaves base ...
    900025: (161, 9001, "H15", 1, 1, "C", True),  # ... so its would-be counterpart stays
    900027: (101, 9001, "H17", 1, 1, "C", True),  # different supplier: not a pair
    900028: (161, 9002, "H17", 1, 1, "C", True),
    900029: (101, 9001, "H18", 1, 1, "C", True),  # annulment of ANOTHER supplier's doc
    900030: (151, 9002, "H18", 1, 1, "C", False),
    900031: (106, 9001, "H19", 1, 1, "C", True),  # receipt pair
    900032: (166, 9001, "H19", 1, 1, "C", False),
    900033: (101, 9001, "H20", 1, 1, "C", True),  # NC vs FC, same hacc, opposite sign
    900034: (103, 9001, "H20", 1, 1, "C", False),
    900035: (101, 9001, "H21", 1, 1, "C", True),  # different comp_id: not a pair
    900036: (161, 9001, "H21", 2, 1, "C", True),
    900037: (None, 9001, "H22", 1, 1, "C", False),  # no sd_id
    900038: (999, 9001, "H22b", 1, 1, "C", False),  # sd_id missing from the catalog
    900039: (101, 9001, "H23", 1, 1, "C", False),  # an 'X' annulment still annuls
    900040: (151, 9001, "H23", 1, 1, "X", False),
    900041: (1, 9001, "H24", 1, 1, "C", False),  # sales document
    900042: (101, 9001, "H25", None, 1, "C", True),  # NULL comp_id: never a pair
    900043: (161, 9001, "H25", None, 1, "C", True),
}

_DENSE_SD_CHOICES = "ARRAY[101,101,101,103,104,106,124,161,166,90,151,56,102,105,164,1,NULL,999]"


def _dense_insert(ct_offset: int, rows: int, group_size: int, supp_offset: int) -> str:
    h = "abs(hashint4({}))"
    return f"""
    INSERT INTO tb_commercial_transactions
        (ct_transaction, comp_id, bra_id, supp_id, ct_docnumber, ct_kindof,
         sd_id, ct_total, curr_id_transaction, ct_date)
    SELECT {ct_offset} + i,
           1 + ({h.format("i * 7 + " + str(ct_offset))} % 12 = 0)::int,
           1 + ({h.format("i * 11 + " + str(ct_offset))} % 14 = 0)::int,
           CASE WHEN {h.format("i * 3 + " + str(ct_offset))} % 25 = 0 THEN NULL
                ELSE {supp_offset} + ((i / {group_size}) % 40) + 1 END,
           CASE WHEN {h.format("i * 5 + " + str(ct_offset))} % 31 = 0 THEN NULL
                ELSE 'D' || (i / {group_size}) END,
           CASE {h.format("i * 13 + " + str(ct_offset))} % 15
                WHEN 0 THEN 'X' WHEN 1 THEN NULL WHEN 2 THEN 'x' ELSE 'C' END,
           ({_DENSE_SD_CHOICES})[1 + {h.format("i + " + str(ct_offset))} % 18],
           (i % 997) + 0.25,
           1 + (i % 3 = 0)::int,
           TIMESTAMP '2025-01-01' + (i % 400) * INTERVAL '1 day'
    FROM generate_series(1, {rows}) AS i
    """


# Volume: i in 1..600k. i % 4 = 0 is a purchase (j = i / 4); the rest are
# sales with no supplier. Purchases come in groups of 10 consecutive j per
# supplier: j%10 = 0/1 are an invoice + its counterpart (same doc), 3 is an
# NC, 5 is an ND -- or, every 4th group, an annulment of the j%10=4 invoice --
# 6 a receipt, 8 an "other", 9 a packing list.
_VOLUME_INSERT = f"""
INSERT INTO tb_commercial_transactions
    (ct_transaction, comp_id, bra_id, supp_id, cust_id, ct_docnumber, ct_kindof,
     sd_id, ct_total, curr_id_transaction, ct_date)
SELECT 1000000 + i,
       1,
       CASE WHEN i % 4 = 0 THEN ((i / 4 / 10) % 3) + 1 ELSE 1 END,
       CASE WHEN i % 4 = 0 THEN ((i / 4 / 10) % 800) + 1 END,
       CASE WHEN i % 4 <> 0 THEN i % 5000 END,
       CASE
           WHEN i % 4 <> 0 THEN 'V' || i
           WHEN (i / 4) % 10 = 1 THEN 'F' || (i / 4 - 1)
           WHEN (i / 4) % 40 = 5 THEN 'F' || (i / 4 - 1)
           ELSE 'F' || (i / 4)
       END,
       CASE WHEN i % 4 = 0 AND (i / 4) % 97 = 0 THEN 'X' ELSE 'C' END,
       CASE
           WHEN i % 4 <> 0 THEN CASE WHEN i % 1000 = 1 THEN 56 ELSE 1 END
           ELSE (ARRAY[101, 161, 101, 103, 101, 104, 106, 101, 124, 102])[1 + (i / 4) % 10]
       END,
       (i % 10000) + 0.5,
       1 + (i % 3 = 0)::int,
       TIMESTAMP '2024-01-01' + (i % 900) * INTERVAL '1 day'
FROM generate_series(1, {VOLUME_ROWS}) AS i
"""
# j % 40 = 5 rows get the annulment sd (151) instead of the ND:
_VOLUME_ANNULMENTS = """
UPDATE tb_commercial_transactions SET sd_id = 151
WHERE ct_transaction > 1000000
  AND (ct_transaction - 1000000) % 4 = 0
  AND ((ct_transaction - 1000000) / 4) % 40 = 5
"""


def _seed(conn) -> None:
    for row in _SALE_DOCUMENTS:
        conn.execute(
            text(
                "INSERT INTO tb_sale_document (sd_id, sd_desc, sd_ispurchase, sd_isannulment, "
                "sd_ispackinglist, sd_isquotation, sd_iscreditnote, sd_isdebitnote, sd_isreceipt, "
                "sd_isinbalance, sd_istaxable, sd_plusorminus, hacc_group) "
                "VALUES (:a, :b, :c, :d, :e, :f, :g, :h, :i, :j, :k, :l, :m)"
            ),
            dict(zip("abcdefghijklm", row)),
        )
    for ct, (sd_id, supp, doc, comp, bra, kindof, _expected) in _HANDCRAFTED.items():
        conn.execute(
            text(
                "INSERT INTO tb_commercial_transactions (ct_transaction, comp_id, bra_id, supp_id, "
                "ct_docnumber, ct_kindof, sd_id, ct_total, curr_id_transaction, ct_date) "
                "VALUES (:ct, :comp, :bra, :supp, :doc, :kindof, :sd, 100.00, 1, TIMESTAMP '2026-01-01')"
            ),
            {"ct": ct, "comp": comp, "bra": bra, "supp": supp, "doc": doc, "kindof": kindof, "sd": sd_id},
        )
    conn.execute(text(_dense_insert(ct_offset=0, rows=8000, group_size=4, supp_offset=0)))
    conn.execute(text(_dense_insert(ct_offset=20000, rows=4000, group_size=2, supp_offset=40)))
    conn.execute(text(_VOLUME_INSERT))
    conn.execute(text(_VOLUME_ANNULMENTS))
    conn.execute(text("VACUUM ANALYZE tb_commercial_transactions"))
    conn.execute(text("VACUUM ANALYZE tb_sale_document"))


@pytest.fixture(scope="module")
def pg_url():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

    url = os.environ.get("POSTGRES_TEST_URL", POSTGRES_TEST_URL)
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {url}")

    from app.models.commercial_transaction import CommercialTransaction
    from app.models.tb_sale_document import SaleDocument

    tables = [CommercialTransaction.__table__, SaleDocument.__table__]
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            inspector = sa_inspect(conn)
            for table in tables:
                if inspector.has_table(table.name):
                    pytest.skip(f"{table.name} already exists in the test DB; refusing to touch it")
            # `ct_transaction` (BigInteger PK) and `ct_guid` (UUID) may have been
            # rewritten for SQLite by the shared `engine` fixture.
            _restore_pristine_pg_types(tables)
            for table in tables:
                table.create(bind=conn)
            try:
                _seed(conn)
                _run_migration(url, "upgrade")
                conn.execute(text(_old_view_sql()))
                yield url
            finally:
                conn.execute(text(f"DROP VIEW IF EXISTS {OLD_VIEW}"))
                conn.execute(text(f"DROP VIEW IF EXISTS {VIEW}"))
                for table in reversed(tables):
                    table.drop(bind=conn, checkfirst=True)
    finally:
        from tests.conftest import _patch_pg_types_for_sqlite

        _patch_pg_types_for_sqlite()
        engine.dispose()


@pytest.fixture()
def conn(pg_url):
    engine = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as c:
        yield c
    engine.dispose()


# ──────────────────────────────────────────────────────────────────────────
# Parity
# ──────────────────────────────────────────────────────────────────────────


def _rows(conn, view: str, where: str = "", params: dict | None = None) -> list[tuple]:
    return [tuple(r) for r in conn.execute(text(f"SELECT * FROM {view} {where}"), params or {}).all()]


class TestParity:
    def test_same_columns_names_types_and_order(self, conn) -> None:
        def columns(view):
            return conn.execute(
                text(
                    "SELECT attname, format_type(atttypid, atttypmod) FROM pg_attribute "
                    "WHERE attrelid = CAST(:v AS regclass) AND attnum > 0 ORDER BY attnum"
                ),
                {"v": view},
            ).all()

        assert columns(VIEW) == columns(OLD_VIEW)

    def test_the_dataset_exercises_every_exclusion(self, conn) -> None:
        """Parity is only meaningful if the old view actually excludes rows for
        each reason on this data."""
        base_where = """
            sd.sd_ispurchase AND NOT sd.sd_isannulment AND NOT sd.sd_ispackinglist
            AND NOT sd.sd_isquotation AND COALESCE(ct.ct_kindof, '') <> 'X'
            AND ct.supp_id IS NOT NULL AND ct.ct_docnumber IS NOT NULL
        """
        counts = conn.execute(
            text(
                f"""
                WITH base AS (
                    SELECT ct.* FROM tb_commercial_transactions ct
                    JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id WHERE {base_where}
                ),
                annulled AS (
                    SELECT DISTINCT ct.supp_id, ct.ct_docnumber FROM tb_commercial_transactions ct
                    JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id WHERE sd.sd_isannulment
                )
                SELECT
                    (SELECT count(*) FROM base),
                    (SELECT count(*) FROM {OLD_VIEW}),
                    (SELECT count(*) FROM base b JOIN annulled a USING (supp_id, ct_docnumber)),
                    (SELECT count(*) FROM base b WHERE NOT EXISTS (
                        SELECT 1 FROM annulled a WHERE a.supp_id = b.supp_id AND a.ct_docnumber = b.ct_docnumber)
                        AND b.ct_transaction NOT IN (SELECT ct_transaction FROM {OLD_VIEW})),
                    (SELECT count(*) FROM (SELECT 1 FROM base GROUP BY supp_id, ct_docnumber, comp_id, bra_id
                                           HAVING count(*) >= 3) t)
                """
            )
        ).one()
        base_rows, view_rows, annulled_rows, counterpart_rows, triples = counts
        assert view_rows > 100_000
        assert annulled_rows > 1_000
        assert counterpart_rows > 10_000
        assert triples > 100
        assert base_rows == view_rows + annulled_rows + counterpart_rows

    def test_new_and_old_return_identical_rows(self, conn) -> None:
        for left, right in ((OLD_VIEW, VIEW), (VIEW, OLD_VIEW)):
            diff = conn.execute(
                text(f"SELECT count(*) FROM (SELECT * FROM {left} EXCEPT ALL SELECT * FROM {right}) d")
            ).scalar()
            assert diff == 0, f"{left} EXCEPT ALL {right} returned {diff} rows"

    def test_handcrafted_cases(self, conn) -> None:
        present = {
            r[0]
            for r in conn.execute(
                text(f"SELECT ct_transaction FROM {VIEW} WHERE ct_transaction BETWEEN 900000 AND 900999")
            )
        }
        expected = {ct for ct, spec in _HANDCRAFTED.items() if spec[-1]}
        assert present == expected
        old_present = {
            r[0]
            for r in conn.execute(
                text(f"SELECT ct_transaction FROM {OLD_VIEW} WHERE ct_transaction BETWEEN 900000 AND 900999")
            )
        }
        assert old_present == expected

    def test_per_ct_transaction_lookups_agree_with_the_old_full_result(self, conn) -> None:
        """The pushed-down per-row path (different plan) must agree with the old
        view's full result, row for row, on every dense/handcrafted ct and a
        sample of the volume block -- present AND absent ones."""
        old = {r[0]: r for r in _rows(conn, OLD_VIEW, "WHERE ct_transaction < 1000000")}
        old.update({r[0]: r for r in _rows(conn, OLD_VIEW, "WHERE ct_transaction % 997 = 0")})
        cts = [
            r[0]
            for r in conn.execute(
                text("SELECT ct_transaction FROM tb_commercial_transactions WHERE ct_transaction < 1000000")
            )
        ]
        cts += list(range(1_000_000 + 997 - (1_000_000 % 997), 1_000_000 + VOLUME_ROWS, 997 * 7))
        assert sum(1 for ct in cts if ct in old) > 1_000
        stmt = text(f"SELECT * FROM {VIEW} WHERE ct_transaction = :ct")
        for ct in cts:
            got = [tuple(r) for r in conn.execute(stmt, {"ct": ct}).all()]
            assert got == ([old[ct]] if ct in old else []), ct


# ──────────────────────────────────────────────────────────────────────────
# Plans and timings per caller pattern
# ──────────────────────────────────────────────────────────────────────────

# A volume purchase alone in its doc (j % 10 = 7) and a counterpart (j % 10 = 1).
_J_IN = 1234 * 10 + 7
_J_OUT = 1234 * 10 + 1
_CT_IN = 1_000_000 + 4 * _J_IN
_CT_OUT = 1_000_000 + 4 * _J_OUT
_SUPP = ((_J_IN // 10) % 800) + 1
_BRA = ((_J_IN // 10) % 3) + 1

PATTERNS = {
    "B erp_matching loop: ct_transaction = X (in view)": (
        "SELECT v.ct_transaction, v.comp_id, v.bra_id, v.supp_id, v.ct_docnumber, v.ct_total "
        "FROM {view} v WHERE v.ct_transaction = :ct",
        {"ct": _CT_IN},
    ),
    "B erp_matching loop: ct_transaction = X (counterpart, not in view)": (
        "SELECT v.ct_transaction, v.comp_id, v.bra_id, v.supp_id, v.ct_docnumber, v.ct_total "
        "FROM {view} v WHERE v.ct_transaction = :ct",
        {"ct": _CT_OUT},
    ),
    "C pedidos: ct_transaction = X AND supp_id = Y LIMIT 1": (
        "SELECT ct_docnumber, ct_total, curr_id_transaction FROM {view} "
        "WHERE ct_transaction = :ct AND supp_id = :supp LIMIT 1",
        {"ct": _CT_IN, "supp": _SUPP},
    ),
    "A erp_matching: comp/bra/supp/docnumber LIMIT 2": (
        "SELECT ct_transaction FROM {view} WHERE comp_id = :comp AND bra_id = :bra "
        "AND supp_id = :supp AND ct_docnumber = :doc LIMIT 2",
        {"comp": 1, "bra": _BRA, "supp": _SUPP, "doc": f"F{_J_IN}"},
    ),
    "D facturas-erp-vigentes: supp_id [+ curr] ORDER BY ct_date LIMIT 200": (
        "SELECT v.ct_transaction, v.ct_docnumber, v.ct_date, v.ct_total, v.curr_id_transaction "
        "FROM {view} v WHERE v.supp_id = :supp AND v.curr_id_transaction = 1 "
        "ORDER BY v.ct_date DESC NULLS LAST, v.ct_transaction DESC LIMIT 200",
        {"supp": _SUPP},
    ),
    "E facturas-candidatas: supp_id + NOT IN linked ORDER BY ct_date LIMIT 100": (
        "SELECT v.ct_transaction, v.ct_docnumber, v.ct_date, v.ct_total, v.curr_id_transaction "
        "FROM {view} v WHERE v.supp_id = :supp "
        "AND v.ct_transaction NOT IN (SELECT x FROM (VALUES (CAST(1 AS BIGINT)), (2), (3)) t(x)) "
        "ORDER BY v.ct_date DESC NULLS LAST, v.ct_transaction DESC LIMIT 100",
        {"supp": _SUPP},
    ),
}

_SELECTIVE = list(PATTERNS)  # every caller pattern above must be served by index probes
_UNFILTERED = ("F unfiltered: count(*)", ("SELECT count(*) FROM {view}", {}))


def _explain(conn, sql: str, params: dict) -> tuple[float, list[dict]]:
    conn.execute(text(sql), params).all()  # warm the cache
    raw = conn.execute(text(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}"), params).scalar()
    plan = raw if isinstance(raw, list) else json.loads(raw)
    nodes: list[dict] = []

    def walk(node):
        nodes.append(node)
        for child in node.get("Plans", []):
            walk(child)

    walk(plan[0]["Plan"])
    return plan[0]["Execution Time"], nodes


def _offending(nodes: list[dict]) -> list[str]:
    bad = []
    for n in nodes:
        if n["Node Type"] == "Seq Scan" and n.get("Relation Name") == "tb_commercial_transactions":
            bad.append("Seq Scan on tb_commercial_transactions")
        if n["Node Type"] in ("Gather", "Gather Merge") or n.get("Parallel Aware"):
            bad.append(f"parallel node {n['Node Type']}")
    return bad


def _ct_rows_read(nodes: list[dict]) -> int:
    """Rows of tb_commercial_transactions the plan actually read (kept or
    filtered out), across every loop."""
    return int(
        sum(
            (n.get("Actual Rows", 0) + n.get("Rows Removed by Filter", 0) + n.get("Rows Removed by Index Recheck", 0))
            * n.get("Actual Loops", 1)
            for n in nodes
            if n.get("Relation Name") == "tb_commercial_transactions"
        )
    )


class TestPlans:
    @pytest.mark.parametrize("name", _SELECTIVE)
    def test_caller_pattern_touches_only_its_rows(self, conn, name) -> None:
        sql, params = PATTERNS[name]
        # Plan shape and rows read prove it; wall-clock limits would make the
        # test depend on how loaded the CI host is.
        _ms, nodes = _explain(conn, sql.format(view=VIEW), params)
        assert _offending(nodes) == [], name
        assert _ct_rows_read(nodes) < 5_000, f"{name}: read {_ct_rows_read(nodes)} rows"

    def test_same_answer_per_pattern(self, conn) -> None:
        for name, (sql, params) in PATTERNS.items():
            ordered = "ORDER BY" in sql
            new = [tuple(r) for r in conn.execute(text(sql.format(view=VIEW)), params).all()]
            old = [tuple(r) for r in conn.execute(text(sql.format(view=OLD_VIEW)), params).all()]
            assert (new if ordered else sorted(new)) == (old if ordered else sorted(old)), name
            expect_rows = "not in view" not in name
            assert bool(new) is expect_rows, f"{name}: unexpected {'empty' if expect_rows else 'non-empty'} result"

    def test_report_old_vs_new_timings(self, conn) -> None:
        """Evidence for the feature doc (`pytest -s` prints it); asserts nothing.
        The unfiltered count (only the post-deploy checklist runs it) uses a
        hash anti-join whose "rows read" isn't comparable with the old plan,
        and a wall-clock limit would depend on how loaded the CI host is. The
        caller patterns the app runs are pinned by plan shape above."""
        lines = []
        for name, (sql, params) in [*PATTERNS.items(), _UNFILTERED]:
            old_ms, old_nodes = _explain(conn, sql.format(view=OLD_VIEW), params)
            new_ms, new_nodes = _explain(conn, sql.format(view=VIEW), params)
            old_flags = ", ".join(sorted(set(_offending(old_nodes)))) or "no seq/parallel"
            lines.append(
                f"{name}: old {old_ms:.1f} ms, {_ct_rows_read(old_nodes)} ct rows read ({old_flags})"
                f" -> new {new_ms:.2f} ms, {_ct_rows_read(new_nodes)} ct rows read"
            )
        print("\n" + "\n".join(lines))


# ──────────────────────────────────────────────────────────────────────────
# Migration mechanics
# ──────────────────────────────────────────────────────────────────────────


def _validity(conn, name: str):
    return conn.execute(
        text(
            "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name AND pg_table_is_visible(c.oid)"
        ),
        {"name": name},
    ).scalar()


class TestMigration:
    def test_the_graph_has_a_single_head_and_includes_this_revision(self) -> None:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(_BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
        assert len(heads) == 1, f"alembic forked: {heads}"
        # Later migrations may sit on top; this one must stay on the line.
        assert _new_migration().revision in {r.revision for r in script.walk_revisions("base", heads[0])}

    def test_upgrade_left_a_valid_supp_docnumber_index(self, conn) -> None:
        name = _new_migration().INDEX
        assert _validity(conn, name) is True
        cols = conn.execute(
            text(
                "SELECT array_agg(a.attname ORDER BY k.ord) FROM pg_index i "
                "CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum "
                "WHERE i.indexrelid = CAST(:n AS regclass)"
            ),
            {"n": name},
        ).scalar()
        assert cols == ["supp_id", "ct_docnumber"]

    def test_rebuilds_an_invalid_index_left_by_an_interrupted_build(self, conn, pg_url) -> None:
        """A REAL invalid index: a concurrent UNIQUE build over the duplicated
        (supp_id, ct_docnumber) pairs fails after creating its catalog entry."""
        from sqlalchemy.exc import IntegrityError

        name = _new_migration().INDEX
        conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        with pytest.raises(IntegrityError):
            conn.execute(
                text(f"CREATE UNIQUE INDEX CONCURRENTLY {name} ON tb_commercial_transactions (supp_id, ct_docnumber)")
            )
        assert _validity(conn, name) is False

        _run_migration(pg_url, "upgrade")

        assert _validity(conn, name) is True
        unique = conn.execute(
            text("SELECT indisunique FROM pg_index WHERE indexrelid = CAST(:n AS regclass)"), {"n": name}
        ).scalar()
        assert unique is False

    def test_a_valid_index_is_left_alone(self, conn, pg_url) -> None:
        name = _new_migration().INDEX
        oid_before = conn.execute(text("SELECT CAST(:n AS regclass)::oid"), {"n": name}).scalar()

        _run_migration(pg_url, "upgrade")

        assert conn.execute(text("SELECT CAST(:n AS regclass)::oid"), {"n": name}).scalar() == oid_before

    def test_downgrade_restores_the_compras_014_definition(self, conn, pg_url) -> None:
        def viewdef(view):
            return conn.execute(text("SELECT pg_get_viewdef(CAST(:v AS regclass))"), {"v": view}).scalar()

        new_def = viewdef(VIEW)
        assert new_def != viewdef(OLD_VIEW)
        try:
            _run_migration(pg_url, "downgrade")
            assert viewdef(VIEW) == viewdef(OLD_VIEW)
            assert _validity(conn, _new_migration().INDEX) is None
        finally:
            _run_migration(pg_url, "upgrade")
        assert viewdef(VIEW) == new_def
