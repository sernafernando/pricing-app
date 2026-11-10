"""Store scope of an existing sell in cost bonus that belongs to a tactical, against real tables: a tactical
created before `20261107_tacticals_tiendas` (as that migration's backfill leaves it: all stores, the `fuera` and
`tienda_nube` rows and one shared cap) discounts exactly what it discounted before the scope existed.

Postgres only, in a throwaway schema (`_bono_world` plus the store tables)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.tactical import TacticalTienda
from app.services.sell_in import bonos_costo
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _bono_world as b
from tests.services.sell_in import _world as w

pytestmark = pytest.mark.postgres

D = date
GAUSS, TPLINK = 57997, 2645
# The publication's official store, as the sales reach reads it (latest `mlp_official_store_id` per MLA).
PUBLICADOS = (
    "CREATE TABLE tb_mercadolibre_items_publicados ("
    "mlp_id SERIAL PRIMARY KEY, mlp_publicationid VARCHAR(50), mlp_official_store_id INTEGER)"
)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema(
        "sell_in_bono_tienda",
        [*b.TABLES, MlTiendaOficial.__table__, TacticalTienda.__table__],
        [*b.STUBS, PUBLICADOS],
        after=_install,
    ) as engine:
        yield engine


def _install(engine: Engine) -> None:
    b._install(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden, activa) "
                "VALUES (57997, 'GaussOnline', 'gauss', 1, true), (2645, 'TP-Link', 'tplink', 2, true)"
            )
        )


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tb_mercadolibre_items_publicados"))
        conn.execute(text("DELETE FROM tacticals"))  # its store rows cascade


def _bono_de_tactical_existente(engine: Engine, **kw) -> int:
    """A fixed 10 ARS per unit cost bonus, line 1 of a tactical that predates the store scope (as the backfill
    leaves it)."""
    bono = b.bono_costo(engine, monto_unit="10.00", **kw)
    with engine.begin() as conn:
        tid = conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id, "
                "todas_tiendas, tope_compartido) VALUES ('sell_in', 'Viejo', 'TP-LINK', '2026-10-01', "
                "'2026-10-31', 'ARS', 7, true, true) RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text("INSERT INTO tactical_tiendas (tactical_id, tipo) VALUES (:t, 'fuera'), (:t, 'tienda_nube')"),
            {"t": tid},
        )
        conn.execute(
            text("UPDATE sell_in_bonos_marca SET tactical_id = :t, tactical_linea = 1 WHERE id = :b"),
            {"t": tid, "b": bono},
        )
    return bono


def _venta_ml(engine: Engine, cantidad: int, dia: date, store_id: Optional[int]) -> int:
    ref = w.venta(engine, "ml", 2964, cantidad, dia)  # mcosto 30: never below the 10 ARS per unit
    if store_id is not None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tb_mercadolibre_items_publicados (mlp_publicationid, mlp_official_store_id) "
                    "VALUES (:mla, :s)"
                ),
                {"mla": f"MLA{ref}", "s": store_id},
            )
    return ref


def _con_costo(engine: Engine, canal: str, cantidad: int, dia: date) -> int:
    ref = w.venta(engine, canal, 2964, cantidad, dia)
    w.update_venta(engine, canal, ref, costo_total=Decimal("1000.00") * cantidad)
    return ref


def _recalcular(engine: Engine) -> None:
    with sessionmaker(bind=engine, autoflush=False)() as db:
        bonos_costo.recalcular(db, [2964])
        db.commit()


def _filas(engine: Engine):
    """`(bono_id, canal, venta_ref, unidades, descuento_ars)`."""
    return sorted((r[0], r[1], r[2], r[5], r[6]) for r in b.bono_consumos(engine))


class TestExistingTacticalBonus:
    def test_it_keeps_its_fuera_tienda_nube_and_no_store_ml_discounts(self, engine: Engine) -> None:
        bono = _bono_de_tactical_existente(engine)
        ml = _venta_ml(engine, 1, D(2026, 10, 5), store_id=None)
        fuera = _con_costo(engine, "fuera", 1, D(2026, 10, 6))
        tn = _con_costo(engine, "tn", 2, D(2026, 10, 7))

        _recalcular(engine)
        _recalcular(engine)  # the next recalculation keeps them too

        assert _filas(engine) == sorted(
            [
                (bono, "ml", ml, 1, Decimal("10.00")),
                (bono, "fuera", fuera, 1, Decimal("10.00")),
                (bono, "tn", tn, 2, Decimal("20.00")),
            ]
        )

    def test_its_cap_stays_one_pool_over_two_stores(self, engine: Engine) -> None:
        bono = _bono_de_tactical_existente(engine, tope_unidades=1)
        gauss = _venta_ml(engine, 1, D(2026, 10, 5), store_id=GAUSS)
        _venta_ml(engine, 1, D(2026, 10, 6), store_id=TPLINK)

        _recalcular(engine)

        assert _filas(engine) == [(bono, "ml", gauss, 1, Decimal("10.00"))]
