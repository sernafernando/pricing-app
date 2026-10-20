"""`GET /prearmado/combos/buscar` finds combos through `combo_componentes`, not
the ERP mirror (combos-propios C2). Postgres: the query uses ILIKE."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.combo_componente import ComboComponente
from app.models.tb_item import TBItem
from app.models.tb_item_association import TbItemAssociation
from app.routers.prearmado import buscar_combos
from app.services.combos.componentes import DETALLE_COMBOS_NO_SINCRONIZADOS
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

_TABLES = [ComboComponente.__table__, TBItem.__table__, TbItemAssociation.__table__]


@pytest.fixture()
def pg_session() -> Iterator[Session]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types(_TABLES)
    schema = f"combo_buscar_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    session = None
    try:
        with engine.begin() as conn:
            for table in _TABLES:
                table.create(bind=conn)
        session = sessionmaker(bind=engine)()
        yield session
    finally:
        if session is not None:
            session.close()
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


@pytest.mark.postgres
def test_finds_combos_of_the_app_table_only(pg_session: Session) -> None:
    db = pg_session
    for item_id, code in [(100, "NB-A"), (200, "NB-B"), (300, "NB-VIEJO"), (500, "NB-DISCO")]:
        db.add(TBItem(comp_id=1, item_id=item_id, item_code=code, item_desc=f"notebook {code}"))
    # 100 is a combo in both tables, 200 only in the app table, 300 only in the mirror.
    db.add_all(
        [
            ComboComponente(combo_item_id=100, componente_item_id=500, cantidad=Decimal("1")),
            ComboComponente(combo_item_id=100, componente_item_id=600, cantidad=Decimal("2")),
            ComboComponente(combo_item_id=200, componente_item_id=500, cantidad=Decimal("1")),
            TbItemAssociation(comp_id=1, itema_id=1, item_id=100, item_id_1=500, iasso_qty=1),
            TbItemAssociation(comp_id=1, itema_id=2, item_id=300, item_id_1=500, iasso_qty=1),
        ]
    )
    db.commit()

    found = buscar_combos(q="nb-", limit=20, db=db)

    # One row per combo even with several components.
    assert [c.item_id for c in found] == [100, 200]


@pytest.mark.postgres
def test_an_item_under_two_companies_is_found_once(pg_session: Session) -> None:
    """The old query joined the mirror on item_id AND comp_id, so the search
    only ever saw the company the bill of materials belongs to (1). The app
    table has no company: the search keeps that scope instead of returning
    one row per company."""
    db = pg_session
    db.add(TBItem(comp_id=1, item_id=100, item_code="NB-A", item_desc="notebook A"))
    db.add(TBItem(comp_id=2, item_id=100, item_code="NB-A-OTRA", item_desc="notebook A otra empresa"))
    db.add(ComboComponente(combo_item_id=100, componente_item_id=500, cantidad=Decimal("1")))
    db.commit()

    found = buscar_combos(q="nb-", limit=20, db=db)

    assert [(c.item_id, c.item_code) for c in found] == [(100, "NB-A")]


@pytest.mark.postgres
def test_an_empty_bom_is_503_not_an_empty_search(pg_session: Session) -> None:
    db = pg_session
    db.add(TBItem(comp_id=1, item_id=100, item_code="NB-A", item_desc="notebook A"))
    db.add(TbItemAssociation(comp_id=1, itema_id=1, item_id=100, item_id_1=500, iasso_qty=1))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        buscar_combos(q="nb-", limit=20, db=db)

    assert exc.value.status_code == 503
    assert exc.value.detail == DETALLE_COMBOS_NO_SINCRONIZADOS
