"""Tactical store scope in the screens' sell in / sell out resolver, against real tables: several store contexts
(one per official store of a page) are resolved from ONE database read, each with the same result as resolving it
alone. Postgres only, like the allocators it reads after."""

from __future__ import annotations

from datetime import date
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.tactical import TacticalTienda
from app.services.productos_sell_in_out import resolver_sell_in_out_batch, resolver_sell_in_out_por_contexto
from app.services.sell_out import asignacion
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _world as si
from tests.services.sell_out import _world as so
from tests.services.test_productos_sell_in_out_postgres import STUBS, TABLES, _install as _install_base

pytestmark = pytest.mark.postgres

D = date
HOY = D(2026, 11, 10)
ROUTER = 2964
GAUSS, TPLINK = 57997, 2645
PUBLICADOS = (
    "CREATE TABLE tb_mercadolibre_items_publicados ("
    "mlp_id SERIAL PRIMARY KEY, mlp_publicationid VARCHAR(50), mlp_official_store_id INTEGER)"
)
CONTEXTOS = {GAUSS: [("ml", GAUSS)], TPLINK: [("ml", TPLINK)], "sin_tienda": [("ml", None)], "todas": None}


def _install(engine: Engine) -> None:
    _install_base(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden, activa) "
                "VALUES (57997, 'GaussOnline', 'gauss', 1, true), (2645, 'TP-Link', 'tplink', 2, true)"
            )
        )


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema(
        "productos_sio_tienda",
        [*TABLES, MlTiendaOficial.__table__, TacticalTienda.__table__],
        [*STUBS, PUBLICADOS],
        after=_install,
    ) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    si.clean(engine)
    so.clean(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tb_mercadolibre_items_publicados"))
        conn.execute(text("DELETE FROM tacticals"))


def _campana_de_tactical(engine: Engine, *, todas: bool, oficiales=(), compartido: bool = False, **kw) -> int:
    with engine.begin() as conn:
        tid = conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id, "
                "todas_tiendas, tope_compartido) VALUES ('sell_out', 'T', 'TP-LINK', '2026-11-01', '2026-11-30', "
                "'ARS', 7, :todas, :comp) RETURNING id"
            ),
            {"todas": todas, "comp": compartido},
        ).scalar_one()
        for store_id in oficiales:
            conn.execute(
                text("INSERT INTO tactical_tiendas (tactical_id, tipo, store_id) VALUES (:t, 'oficial', :s)"),
                {"t": tid, "s": store_id},
            )
    gid = so.grupo(engine, [{"item_id": ROUTER}])
    return so.campana(engine, [gid], tactical_id=tid, tactical_linea=1, **kw)


def _venta_ml(engine: Engine, dia: date, store_id: Optional[int]) -> None:
    ref = si.venta(engine, "ml", ROUTER, 1, dia)
    if store_id is not None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tb_mercadolibre_items_publicados (mlp_publicationid, mlp_official_store_id) "
                    "VALUES (:mla, :s)"
                ),
                {"mla": f"MLA{ref}", "s": store_id},
            )


def _campanas(batch) -> list:
    return [c.campana.id for c in batch.campanas.get(ROUTER, [])]


def _statements(engine: Engine, contextos) -> int:
    statements = []
    with sessionmaker(bind=engine, autoflush=False)() as db:
        event.listen(db.connection(), "before_cursor_execute", lambda *a: statements.append(a[2]))
        resolver_sell_in_out_por_contexto(db, [ROUTER], HOY, contextos)
    return len(statements)


class TestPorContexto:
    def test_each_store_gets_what_resolving_it_alone_gives(self, engine: Engine) -> None:
        por_tienda = _campana_de_tactical(engine, todas=False, oficiales=(GAUSS, TPLINK), tope_unidades=1)
        todas = _campana_de_tactical(engine, todas=True)
        _venta_ml(engine, D(2026, 11, 5), GAUSS)  # uses up GaussOnline's own cap of the per-store campaign
        with sessionmaker(bind=engine, autoflush=False)() as db:
            asignacion.recalcular(db, [por_tienda, todas])
            db.commit()

        with sessionmaker(bind=engine, autoflush=False)() as db:
            juntos = resolver_sell_in_out_por_contexto(db, [ROUTER], HOY, CONTEXTOS)
            solos = {k: resolver_sell_in_out_batch(db, [ROUTER], HOY, contextos=c) for k, c in CONTEXTOS.items()}

        assert {k: _campanas(b) for k, b in juntos.items()} == {k: _campanas(b) for k, b in solos.items()}
        assert _campanas(juntos[GAUSS]) == [todas]
        assert _campanas(juntos[TPLINK]) == [por_tienda, todas]
        assert _campanas(juntos["sin_tienda"]) == [todas]  # all stores reaches a publication with no official store

    def test_more_stores_cost_no_more_queries(self, engine: Engine) -> None:
        _campana_de_tactical(engine, todas=False, oficiales=(GAUSS, TPLINK), tope_unidades=5)
        _venta_ml(engine, D(2026, 11, 5), GAUSS)

        assert _statements(engine, CONTEXTOS) == _statements(engine, {GAUSS: [("ml", GAUSS)]})
