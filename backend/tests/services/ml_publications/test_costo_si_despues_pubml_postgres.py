"""Publicaciones ML after a costo SI recompute (owner L15: "si alguien edita por alguna razón el sell in de cualquier
factura o loyalty o lo que fuera, se tienen que recalcular todos los costos posteriores y los promedios claramente").

pubml markups are computed live; the two stored values that depend on the cost are the "hay mejores ofertas" flag
and the catalog snapshot competitor markups. The `pubml` callback queues both for every MLA of the product and of
every combo (not a PC) that contains it. Interface: handoffs/sell-in-costo-si-interfaz.md §1 and §3. Invented data."""

from __future__ import annotations

import sys
from datetime import date
from typing import Iterator

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import sessionmaker

from app.models.catalog_competition_refresh_pending import CatalogCompetitionRefreshPending
from app.models.worker_job_state import WorkerJobState
from app.services import ml_hay_mejores_pendientes as pendientes
from app.services import catalog_competition_target as target
from app.services.costo_si import despues
from app.services.costo_si.despues import pubml
from tests.services.costo_si import _world as w

pytestmark = pytest.mark.postgres

P = 5601
OTRO = 5602
COMBO = 5603
PC = 5604
DESDE = date(2026, 10, 1)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    from tests.conftest import _restore_pristine_pg_types

    with w.world("costo_si_despues_pubml") as engine:
        tables = [WorkerJobState.__table__, CatalogCompetitionRefreshPending.__table__]
        _restore_pristine_pg_types(tables)
        for table in tables:
            table.create(bind=engine)
        # The ML columns the world's stand-ins leave out and these consumers read.
        w.run(engine, "ALTER TABLE ml_items ADD COLUMN catalog_listing BOOLEAN")
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(despues, "_CALLBACKS", {})
    monkeypatch.setattr(despues, "_cargados", True)
    yield
    w.clean(engine)
    w.run(engine, "DELETE FROM worker_job_state")
    w.run(engine, "DELETE FROM catalog_competition_refresh_pending")


def _publicacion(engine: Engine, mla: str, producto: int, *, catalogo: bool = False, estado: str = "linked") -> None:
    w.run(engine, "INSERT INTO ml_items (item_id, catalog_listing) VALUES (:m, :c)", m=mla, c=catalogo)
    w.run(
        engine,
        "INSERT INTO ml_item_product_links (item_id, variation_id, producto_item_id, match_status) "
        "VALUES (:m, 0, :p, :s)",
        m=mla,
        p=producto,
        s=estado,
    )


def _mundo(engine: Engine) -> None:
    w.producto(engine, P)
    w.producto(engine, OTRO)
    w.producto(engine, COMBO)
    w.producto(engine, PC, cat_id=47)
    w.run(
        engine,
        "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :p, 2), (:pc, :p, 1)",
        c=COMBO,
        p=P,
        pc=PC,
    )
    _publicacion(engine, "MLA10", P)  # plain listing of P, no catalog sister
    _publicacion(engine, "MLA11", P, catalogo=True)  # P's catalog listing
    _publicacion(engine, "MLA20", COMBO)  # the combo's listing
    _publicacion(engine, "MLA30", PC)  # a PC is its own product: its cost is not P's
    _publicacion(engine, "MLA40", OTRO, catalogo=True)  # unrelated
    _publicacion(engine, "MLA12", P, estado="unlinked")  # not linked: nobody prices it with P


def _despachar(engine: Engine) -> None:
    with sessionmaker(bind=engine)() as db:
        despues.despachar(db, P, DESDE)
        db.commit()


def test_the_package_registers_the_pubml_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loaded with the rest of `costo_si/despues/`: no shared list to edit."""
    monkeypatch.setattr(despues, "_cargados", False)
    monkeypatch.delitem(sys.modules, pubml.__name__)
    despues._cargar()
    assert despues._CALLBACKS["pubml"].__module__ == pubml.__name__
    assert despues._CALLBACKS["pubml"].__name__ == "_on_costo_si"


def test_queues_the_mlas_of_the_product_and_of_its_combos_for_hay_mejores(engine: Engine) -> None:
    despues.registrar("pubml", pubml._on_costo_si)
    _mundo(engine)

    _despachar(engine)

    with sessionmaker(bind=engine)() as db:
        assert pendientes.pendientes(db) == ["MLA10", "MLA11", "MLA20"]


def test_running_twice_keeps_one_entry_each(engine: Engine) -> None:
    despues.registrar("pubml", pubml._on_costo_si)
    _mundo(engine)

    _despachar(engine)
    _despachar(engine)

    with sessionmaker(bind=engine)() as db:
        assert pendientes.pendientes(db) == ["MLA10", "MLA11", "MLA20"]
    assert w.rows(engine, "SELECT mla, attempts FROM catalog_competition_refresh_pending ORDER BY mla") == [
        ("MLA11", 0)
    ]


def test_enqueues_the_catalog_competition_refresh_of_the_catalog_listing(engine: Engine) -> None:
    """MLA10 and MLA11 both lead to P's catalog listing; the combo has none; the unrelated catalog MLA40 stays out."""
    despues.registrar("pubml", pubml._on_costo_si)
    _mundo(engine)

    _despachar(engine)

    assert w.rows(engine, "SELECT mla FROM catalog_competition_refresh_pending ORDER BY mla") == [("MLA11",)]


def test_the_batch_target_is_the_one_mla_resolver_of_every_mla(engine: Engine) -> None:
    """`mlas_for_catalog_competition_refresh` keeps `mla_for_catalog_competition_refresh`'s rule, in three
    statements: a catalog listing is its own target, a plain one leads to its product's lowest catalog listing."""
    _mundo(engine)
    _publicacion(engine, "MLA13", P, catalogo=True)  # a second catalog listing of P: the lowest id wins
    _publicacion(engine, "MLA41", OTRO)  # a plain listing of OTRO: its catalog sister MLA40
    mlas = ["MLA10", "MLA11", "MLA12", "MLA13", "MLA20", "MLA30", "MLA41", "MLA99"]
    with sessionmaker(bind=engine)() as db:
        one_by_one = {t for t in (target.mla_for_catalog_competition_refresh(db, m) for m in mlas) if t}
        statements: list[str] = []

        def record(connection, cursor, statement, *rest) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            batch = target.mlas_for_catalog_competition_refresh(db, mlas)
        finally:
            event.remove(engine, "before_cursor_execute", record)
    assert batch == one_by_one == {"MLA11", "MLA13", "MLA40"}
    assert len(statements) == 3


def test_a_product_without_publications_queues_nothing(engine: Engine) -> None:
    despues.registrar("pubml", pubml._on_costo_si)
    w.producto(engine, OTRO)

    with sessionmaker(bind=engine)() as db:
        despues.despachar(db, OTRO, DESDE)
        db.commit()

    assert w.rows(engine, "SELECT count(*) FROM worker_job_state") == [(0,)]
    assert w.rows(engine, "SELECT count(*) FROM catalog_competition_refresh_pending") == [(0,)]
