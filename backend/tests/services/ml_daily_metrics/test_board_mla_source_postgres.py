"""ODD `publicaciones-ml-vista` P9a on real Postgres: `BoardFilter.mla_source`
restricts the Board to a set of MLAs; absent, the Board is byte-identical to
what it was before the field existed.

T1 (characterization): every SQL statement the Board executes, for a spread of
filters and views, is pinned in `golden/board_sql_no_mla_source.json`, which
was generated on UNMODIFIED main. Regenerate it only deliberately, with
`UPDATE_BOARD_GOLDEN=1`, and review the diff: a change there is a change to
Métricas ML.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, List, Optional, Sequence, Tuple

import pytest
from sqlalchemy import String, event, false, literal, null, select, text, union_all
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado as M
from app.services.ml_daily_metrics import board
from tests.services.ml_daily_metrics import test_board_nested_groups_postgres as nested

globals()["tree_catalog"] = nested.tree_catalog

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
GOLDEN = Path(__file__).parent / "golden" / "board_sql_no_mla_source.json"
EPSON_LOGI = [("EPSON", "IMPRESORAS"), ("LOGITECH", "GAMING")]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _filter(**kw: Any) -> board.BoardFilter:
    kw.setdefault("group_by", "product")
    return board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, **kw)


def _everything(
    db: Session,
    f: board.BoardFilter,
    *,
    scope: Sequence[str] = (),
    scope_pairs: Optional[Sequence[Tuple[str, str]]] = None,
    through_leaves: bool = False,
    product_item_id: Optional[int] = None,
) -> None:
    """Exercise every public read of the Board once."""
    with board.Board(
        db, f, product_item_id=product_item_id, scope=scope, scope_pairs=scope_pairs, through_leaves=through_leaves
    ) as b:
        b.kpis()
        b.facets()
        if f.group_by == "group":
            b.group_counts()
            b.group_page(None)
            b.group_page(2, 1, with_series=False)
            if through_leaves:
                keys = b.leaf_keys(50)
                b.leaves_for_keys(keys[:3])
        else:
            b.product_count()
            b.page(None)
            keys = b.ordered_keys(3)
            b.rows_for_keys(keys, with_series=True)


SCENARIOS = {
    "products": lambda db: _everything(db, _filter()),
    "publications": lambda db: _everything(db, _filter(group_by="publication")),
    "filters": lambda db: _everything(
        db,
        _filter(
            stores=("57997",),
            marcas=("EPSON",),
            pub_status=("active",),
            alerts=("sin_ventas_30d", "margen_cayendo"),
            stock=("con_stock",),
            ageing_exclude=("over_60",),
            pub_type_exclude=("premium",),
            solo_con_ventas=True,
            q="epson",
            sort="units",
        ),
    ),
    "pm_scope": lambda db: _everything(db, _filter(), scope_pairs=EPSON_LOGI),
    "empty_pm_scope": lambda db: _everything(db, _filter(), scope_pairs=[]),
    "group_marca": lambda db: _everything(db, _filter(group_by="group", dimension="marca")),
    "group_node": lambda db: _everything(db, _filter(group_by="group", dimension="marca"), scope=("EPSON",)),
    "group_leaves": lambda db: _everything(
        db, _filter(group_by="group", dimension="categoria"), through_leaves=True, scope_pairs=EPSON_LOGI
    ),
    "product_sub_rows": lambda db: _everything(db, _filter(group_by="publication"), product_item_id=21),
}


def _normalize(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _capture(db: Session, run: Callable[[Session], None]) -> List[str]:
    seen: list = []
    engine = db.get_bind()

    def spy(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        sql = _normalize(statement)
        params = repr(sorted(parameters.items())) if isinstance(parameters, dict) else repr(parameters)
        # A digest of the statement AND its bound values, plus the statement's head
        # so a mismatch says which one moved.
        seen.append(f"{hashlib.sha256((sql + params).encode()).hexdigest()[:16]} {sql[:70]}")

    event.listen(engine, "before_cursor_execute", spy)
    try:
        run(db)
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    return seen


@pytest.mark.postgres
def test_board_sql_without_mla_source_is_pinned_to_main(tree_catalog: Session) -> None:
    captured = {name: _capture(tree_catalog, run) for name, run in SCENARIOS.items()}
    if os.environ.get("UPDATE_BOARD_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(captured, indent=1, sort_keys=True) + "\n")
    pinned = json.loads(GOLDEN.read_text())
    assert set(captured) == set(pinned)
    for name in pinned:
        assert captured[name] == pinned[name], f"Board SQL changed for scenario {name!r}"
        assert captured[name], f"scenario {name!r} executed no SQL"


# ── T2: the restriction itself ───────────────────────────────────────────────

MLA_21 = "MLA9000000021"  # product 21, Gauss, 1u
MLA_121 = "MLA9000000121"  # product 21, old TP-Link, 2u
MLA_26 = "MLA9000000026"  # product 26, 2u


def _mlas(*values: str) -> Any:
    """A one-column select of literal MLAs (what a caller's own query would be)."""
    return union_all(*(select(literal(v, String).label("mla")) for v in values))


def _of_products(*items: int) -> Any:
    return select(M.mlp_publicationID).where(M.item_id.in_(items))


def _board(db: Session, f: board.BoardFilter, **kw: Any) -> board.Board:
    kw.setdefault("scope_pairs", None)
    return board.Board(db, f, **kw)


@pytest.mark.postgres
def test_mla_source_restricts_the_lines_and_the_pairs(tree_catalog: Session) -> None:
    f = _filter(mla_source=_mlas(MLA_21, MLA_26))
    with _board(tree_catalog, f) as b:
        by_product = {row.key: row for row in b.page(None)}
        kpis = b.kpis()
    # Product 21 keeps only the sale of ITS MLA in the set (1u, not 1u + 2u).
    assert set(by_product) == {"21", "26"}
    assert by_product["21"].units == 1
    assert by_product["26"].units == 2
    assert kpis.units == 3

    with _board(tree_catalog, _filter(group_by="publication", mla_source=_mlas(MLA_21, MLA_26))) as b:
        assert {row.key for row in b.page(None)} == {MLA_21, MLA_26}

    with _board(tree_catalog, _filter(group_by="group", dimension="marca", mla_source=_mlas(MLA_21, MLA_26))) as b:
        assert {row.key: row.units for row in b.group_page(None)} == {"EPSON": 3}


@pytest.mark.postgres
def test_kpis_equal_metricas_for_the_same_set_of_mlas(tree_catalog: Session) -> None:
    """The MLAs of products 21, 26, 27 and 29 = what the PM scope of EPSON/Impresoras
    + LOGITECH/Gaming selects: same universe, so the same KPIs and rows."""
    via_set = _filter(mla_source=_of_products(21, 26, 27, 29))
    with _board(tree_catalog, via_set) as a:
        got = (a.kpis(), {r.key: r.units for r in a.page(None)}, a.product_count())
    with _board(tree_catalog, _filter(), scope_pairs=EPSON_LOGI) as b:
        want = (b.kpis(), {r.key: r.units for r in b.page(None)}, b.product_count())
    assert got == want
    assert got[2] == 4


@pytest.mark.postgres
def test_an_empty_set_is_empty_never_store_wide(tree_catalog: Session) -> None:
    f = _filter(mla_source=select(literal(MLA_21, String).label("mla")).where(false()))
    with _board(tree_catalog, f) as b:
        k = b.kpis()
        facets = b.facets()
        assert b.product_count() == 0
        assert b.page(None) == []
    assert (k.units, k.rows, k.gross) == (0, 0, 0)
    assert facets.stores == {} and facets.stores_total == 0


@pytest.mark.postgres
def test_a_set_of_unknown_or_null_mlas_selects_nothing(tree_catalog: Session) -> None:
    f = _filter(mla_source=union_all(select(literal("MLA0").label("m")), select(null().label("m"))))
    with _board(tree_catalog, f) as b:
        assert b.kpis().units == 0
        assert b.page(None) == []


@pytest.mark.postgres
def test_the_pm_scope_still_applies_on_top_of_the_set(tree_catalog: Session) -> None:
    everything = _of_products(21, 22, 23, 24, 25, 26, 27, 28, 29)
    with _board(tree_catalog, _filter(mla_source=everything), scope_pairs=EPSON_LOGI) as b:
        assert {row.key for row in b.page(None)} == {"21", "26", "27", "29"}
    with _board(tree_catalog, _filter(mla_source=everything), scope_pairs=[]) as b:
        assert b.page(None) == []
        assert b.kpis().units == 0


@pytest.mark.postgres
def test_the_set_is_distinct_so_duplicate_mlas_do_not_double_count(tree_catalog: Session) -> None:
    with _board(tree_catalog, _filter(mla_source=_mlas(MLA_21, MLA_21, MLA_26))) as b:
        assert b.kpis().units == 3


def test_mla_source_is_not_part_of_the_filters_identity() -> None:
    a = _filter(mla_source=_mlas(MLA_21))
    b = _filter(mla_source=_mlas(MLA_26))
    assert a == b == _filter()
    assert hash(a) == hash(b) == hash(_filter())


def test_mla_source_must_select_exactly_one_column() -> None:
    two = select(literal("MLA1").label("a"), literal("MLA2").label("b"))
    with pytest.raises(ValueError, match="one column"):
        board.mla_set_query(two)


# ── lifecycle on a pooled connection (PgBouncer transaction mode) ────────────


@pytest.fixture()
def plain_session(board_pg_engine: Engine) -> Iterator[Session]:
    """A session with NO outer test transaction: commits and rollbacks are real."""
    session = sessionmaker(bind=board_pg_engine)()
    yield session
    session.rollback()
    session.close()


def _set_exists(session: Session) -> bool:
    return session.execute(text(f"SELECT to_regclass('pg_temp.{board.MLA_SET_TABLE}') IS NOT NULL")).scalar()


def _set_contents(session: Session) -> set:
    return {r[0] for r in session.execute(text(f"SELECT mla FROM {board.MLA_SET_TABLE}"))}


@pytest.mark.postgres
def test_the_set_table_is_gone_after_the_board_exits(plain_session: Session) -> None:
    with _board(plain_session, _filter(mla_source=_mlas(MLA_21, MLA_26))):
        assert _set_exists(plain_session)
        assert _set_contents(plain_session) == {MLA_21, MLA_26}
    assert not _set_exists(plain_session)


@pytest.mark.postgres
def test_consecutive_requests_on_one_connection_never_see_each_others_set(plain_session: Session) -> None:
    with _board(plain_session, _filter(mla_source=_mlas(MLA_21, MLA_26))):
        assert _set_contents(plain_session) == {MLA_21, MLA_26}
    with _board(plain_session, _filter(mla_source=_mlas(MLA_121))):
        assert _set_contents(plain_session) == {MLA_121}
    with _board(plain_session, _filter()):
        # A request WITHOUT a set neither creates nor inherits one.
        assert not _set_exists(plain_session)


@pytest.mark.postgres
def test_the_table_is_gone_after_a_failure_and_the_real_error_surfaces(plain_session: Session) -> None:
    from sqlalchemy.exc import DataError

    with pytest.raises(DataError, match="division by zero"):
        with _board(plain_session, _filter(mla_source=_mlas(MLA_21))):
            plain_session.execute(text("SELECT 1 / 0"))
    assert not _set_exists(plain_session)


@pytest.mark.postgres
def test_a_commit_midway_still_raises_and_leaves_no_table(plain_session: Session) -> None:
    with pytest.raises(RuntimeError, match="transaction"):
        with _board(plain_session, _filter(mla_source=_mlas(MLA_21))):
            plain_session.commit()
            assert not _set_exists(plain_session)
    assert not _set_exists(plain_session)
