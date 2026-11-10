"""Store scope of an existing sell out tactical against real tables: a tactical created before
`20261107_tacticals_tiendas` (as that migration's backfill leaves it: all stores, the `fuera` and
`tienda_nube` rows and one shared cap) credits exactly what it credited before the scope existed.

Postgres only (the rebuild takes an advisory lock). Runs in a throwaway schema.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.tactical import TacticalTienda
from app.models.sell_out import SellOutCampana
from app.models.sell_out import SellOutConsumo
from app.services.sell_out import criterio, resumen, tienda_scope
from app.services.sell_out.asignacion import recalcular
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

D = date
TP_ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}
GAUSS, TPLINK = 57997, 2645


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema(
        "sell_out_tienda",
        [*w.TABLES, MlTiendaOficial.__table__, TacticalTienda.__table__],
        w.STUBS,
        after=_install,
    ) as engine:
        yield engine


def _install(engine: Engine) -> None:
    w._install(engine)
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
    w.clean(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tb_mercadolibre_items_publicados"))
        conn.execute(text("DELETE FROM tacticals"))  # its store rows cascade


def _tactical_existente(engine: Engine) -> int:
    """A tactical that predates the store scope, as the migration's backfill leaves it."""
    with engine.begin() as conn:
        tid = conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id, "
                "todas_tiendas, tope_compartido) VALUES ('sell_out', 'Viejo', 'TP-LINK', '2026-11-01', "
                "'2026-11-30', 'ARS', 7, true, true) RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text("INSERT INTO tactical_tiendas (tactical_id, tipo) VALUES (:t, 'fuera'), (:t, 'tienda_nube')"),
            {"t": tid},
        )
    return tid


def _tactical_solo_gauss(engine: Engine) -> int:
    """A tactical narrowed to the GaussOnline store: no other store, no Por fuera, no Tienda Nube."""
    with engine.begin() as conn:
        tid = conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id, "
                "todas_tiendas, tope_compartido) VALUES ('sell_out', 'Gauss', 'TP-LINK', '2026-11-01', "
                "'2026-11-30', 'ARS', 7, false, true) RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text("INSERT INTO tactical_tiendas (tactical_id, tipo, store_id) VALUES (:t, 'oficial', :s)"),
            {"t": tid, "s": GAUSS},
        )
    return tid


def _tactical_por_tienda(engine: Engine) -> int:
    """A tactical over the GaussOnline and TP-Link stores with one cap per store."""
    with engine.begin() as conn:
        tid = conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id, "
                "todas_tiendas, tope_compartido) VALUES ('sell_out', 'Por tienda', 'TP-LINK', '2026-11-01', "
                "'2026-11-30', 'ARS', 7, false, false) RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO tactical_tiendas (tactical_id, tipo, store_id) "
                "VALUES (:t, 'oficial', :g), (:t, 'oficial', :p)"
            ),
            {"t": tid, "g": GAUSS, "p": TPLINK},
        )
    return tid


def _venta_ml(engine: Engine, item_id: int, cantidad: int, dia: date, store_id: Optional[int]) -> int:
    ref = w.venta(engine, "ml", item_id, cantidad, dia)
    if store_id is not None:
        w.execute(
            engine,
            "INSERT INTO tb_mercadolibre_items_publicados (mlp_publicationid, mlp_official_store_id) VALUES (:mla, :s)",
            mla=f"MLA{ref}",
            s=store_id,
        )
    return ref


def _recalcular(engine: Engine, campana: int) -> None:
    with sessionmaker(bind=engine, autoflush=False)() as db:
        recalcular(db, [campana])
        db.commit()


def _filas(engine: Engine, campana: int) -> list:
    return [(r[1], r[2], r[5], r[6]) for r in w.consumos(engine, campana)]


class TestExistingTactical:
    def test_it_keeps_its_fuera_tienda_nube_and_no_store_ml_credits(self, engine: Engine) -> None:
        campana = w.campana(
            engine, [w.grupo(engine, [TP_ROUTERS])], tactical_id=_tactical_existente(engine), tactical_linea=1
        )
        ml = _venta_ml(engine, 2964, 2, D(2026, 11, 2), store_id=None)
        fuera = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 3))
        tn = w.venta(engine, "tn", 2964, 3, D(2026, 11, 4))

        _recalcular(engine, campana)
        _recalcular(engine, campana)  # the next recalculation keeps them too

        assert _filas(engine, campana) == [
            ("ml", ml, 2, Decimal("20.00")),
            ("fuera", fuera, 1, Decimal("10.00")),
            ("tn", tn, 3, Decimal("30.00")),
        ]

    def test_its_cap_stays_one_pool_over_two_stores(self, engine: Engine) -> None:
        campana = w.campana(
            engine,
            [w.grupo(engine, [TP_ROUTERS])],
            tactical_id=_tactical_existente(engine),
            tactical_linea=1,
            tope_unidades=3,
        )
        gauss = _venta_ml(engine, 2964, 2, D(2026, 11, 2), store_id=GAUSS)
        tplink = _venta_ml(engine, 2964, 2, D(2026, 11, 3), store_id=TPLINK)

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("ml", gauss, 2, Decimal("20.00")), ("ml", tplink, 1, Decimal("10.00"))]


def _tactical_todas(engine: Engine) -> int:
    """A tactical with "Todas las tiendas oficiales" and no channel row: stored as all (S2)."""
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id, "
                "todas_tiendas, tope_compartido) VALUES ('sell_out', 'Todas', 'TP-LINK', '2026-11-01', "
                "'2026-11-30', 'ARS', 7, true, true) RETURNING id"
            )
        ).scalar_one()


class TestTodasEsTodasLasVentas:
    """S2, owner 2026-11-10: "Si es Todas las tiendas oficiales es todas las ventas de ese producto"."""

    def test_todas_credits_ml_without_store_fuera_and_tienda_nube(self, engine: Engine) -> None:
        campana = w.campana(
            engine, [w.grupo(engine, [TP_ROUTERS])], tactical_id=_tactical_todas(engine), tactical_linea=1
        )
        gauss = _venta_ml(engine, 2964, 1, D(2026, 11, 2), store_id=GAUSS)
        ml = _venta_ml(engine, 2964, 2, D(2026, 11, 2), store_id=None)
        fuera = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 3))
        tn = w.venta(engine, "tn", 2964, 3, D(2026, 11, 4))

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [
            ("ml", gauss, 1, Decimal("10.00")),
            ("ml", ml, 2, Decimal("20.00")),
            ("fuera", fuera, 1, Decimal("10.00")),
            ("tn", tn, 3, Decimal("30.00")),
        ]

    def test_a_scoped_tactical_credits_none_of_them(self, engine: Engine) -> None:
        campana = w.campana(
            engine, [w.grupo(engine, [TP_ROUTERS])], tactical_id=_tactical_solo_gauss(engine), tactical_linea=1
        )
        gauss = _venta_ml(engine, 2964, 1, D(2026, 11, 2), store_id=GAUSS)
        _venta_ml(engine, 2964, 2, D(2026, 11, 2), store_id=None)
        w.venta(engine, "fuera", 2964, 1, D(2026, 11, 3))
        w.venta(engine, "tn", 2964, 3, D(2026, 11, 4))

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("ml", gauss, 1, Decimal("10.00"))]


class TestNarrowedTacticalReads:
    """The reads around the rebuild count only the sales the scope credits, like the rebuild does."""

    def test_the_preview_by_units_splits_only_over_the_stores_it_credits(self, engine: Engine) -> None:
        campana = w.monto_total(
            engine,
            [w.grupo(engine, [TP_ROUTERS])],
            "300.00",
            tactical_id=_tactical_solo_gauss(engine),
            tactical_linea=1,
        )
        _venta_ml(engine, 2964, 2, D(2026, 11, 2), store_id=GAUSS)
        _venta_ml(engine, 2964, 1, D(2026, 11, 3), store_id=TPLINK)
        w.venta(engine, "fuera", 2964, 4, D(2026, 11, 4))

        with sessionmaker(bind=engine, autoflush=False)() as db:
            previa = criterio.vista_previa(db, db.get(SellOutCampana, campana), "unidades")

        assert {i["item_id"]: (i["unidades"], i["monto"]) for i in previa["items"]} == {2964: (2, Decimal("300.00"))}

    def test_the_summary_counts_unknown_base_sales_only_inside_the_scope(self, engine: Engine) -> None:
        campana = w.campana(
            engine,
            [w.grupo(engine, [TP_ROUTERS])],
            tipo="porcentaje",
            monto_unit=None,
            porcentaje="10",
            tactical_id=_tactical_solo_gauss(engine),
            tactical_linea=1,
        )
        for dia, store in ((D(2026, 11, 2), GAUSS), (D(2026, 11, 3), TPLINK), (D(2026, 11, 4), None)):
            ref = _venta_ml(engine, 2964, 1, dia, store_id=store)
            w.execute(engine, "UPDATE ml_sale_lines SET gross = 0, mcosto = 0 WHERE item_row_id = :r", r=ref)

        with sessionmaker(bind=engine, autoflush=False)() as db:
            r = resumen.resumenes(db, [db.get(SellOutCampana, campana)])

        assert r[campana]["pendientes_base"] == 1


class TestPerStoreCapLeft:
    """With one cap per store, what is left adds up what every store can still credit, never below zero."""

    def _resumen(self, engine: Engine, campana: int) -> dict:
        with sessionmaker(bind=engine, autoflush=False)() as db:
            return resumen.resumenes(db, [db.get(SellOutCampana, campana)])[campana]

    def test_left_adds_each_store_left_and_a_full_store_adds_zero(self, engine: Engine) -> None:
        campana = w.campana(
            engine,
            [w.grupo(engine, [TP_ROUTERS])],
            tactical_id=_tactical_por_tienda(engine),
            tactical_linea=1,
            tope_unidades=3,
            tope_monto="30.00",
        )
        _venta_ml(engine, 2964, 4, D(2026, 11, 2), store_id=GAUSS)
        _venta_ml(engine, 2964, 1, D(2026, 11, 3), store_id=TPLINK)
        _recalcular(engine, campana)

        r = self._resumen(engine, campana)

        assert r["unidades"] == 4  # Gauss credited its whole cap (3), TP-Link 1
        assert (r["tope_unidades_restantes"], r["tope_monto_restante"], r["tope_por_tienda"]) == (
            2,
            Decimal("20.00"),
            True,
        )

    def test_a_shared_cap_keeps_the_cap_minus_what_was_credited(self, engine: Engine) -> None:
        campana = w.campana(
            engine,
            [w.grupo(engine, [TP_ROUTERS])],
            tactical_id=_tactical_existente(engine),
            tactical_linea=1,
            tope_unidades=3,
        )
        _venta_ml(engine, 2964, 2, D(2026, 11, 2), store_id=GAUSS)
        _recalcular(engine, campana)

        r = self._resumen(engine, campana)

        assert (r["tope_unidades_restantes"], r["tope_monto_restante"], r["tope_por_tienda"]) == (1, None, False)


class TestStoreLookup:
    """The official-store lookup runs only when a scope reads the sale's store."""

    def _lecturas_de_publicados(self, engine: Engine, campana: int) -> int:
        vistas: list[str] = []

        def _ver(conn, cursor, statement, *args) -> None:
            if "tb_mercadolibre_items_publicados" in statement:
                vistas.append(statement)

        event.listen(engine, "before_cursor_execute", _ver)
        try:
            _recalcular(engine, campana)
        finally:
            event.remove(engine, "before_cursor_execute", _ver)
        return len(vistas)

    def test_todays_reach_skips_it(self, engine: Engine) -> None:
        campana = w.campana(
            engine, [w.grupo(engine, [TP_ROUTERS])], tactical_id=_tactical_existente(engine), tactical_linea=1
        )
        ml = _venta_ml(engine, 2964, 2, D(2026, 11, 2), store_id=GAUSS)

        assert self._lecturas_de_publicados(engine, campana) == 0
        assert _filas(engine, campana) == [("ml", ml, 2, Decimal("20.00"))]

    def test_a_narrowed_scope_reads_it(self, engine: Engine) -> None:
        campana = w.campana(
            engine, [w.grupo(engine, [TP_ROUTERS])], tactical_id=_tactical_solo_gauss(engine), tactical_linea=1
        )
        gauss = _venta_ml(engine, 2964, 2, D(2026, 11, 2), store_id=GAUSS)
        _venta_ml(engine, 2964, 1, D(2026, 11, 3), store_id=TPLINK)

        assert self._lecturas_de_publicados(engine, campana) == 1
        assert _filas(engine, campana) == [("ml", gauss, 2, Decimal("20.00"))]


class TestUsedPerCounter:
    def test_adds_up_each_counter_in_sql_an_ml_sale_under_its_publication_store(self, engine: Engine) -> None:
        campana = w.campana(
            engine,
            [w.grupo(engine, [TP_ROUTERS])],
            tactical_id=_tactical_por_tienda(engine),
            tactical_linea=1,
        )
        _venta_ml(engine, 2964, 2, D(2026, 11, 2), store_id=GAUSS)
        _venta_ml(engine, 2964, 1, D(2026, 11, 3), store_id=GAUSS)
        _venta_ml(engine, 2964, 4, D(2026, 11, 4), store_id=TPLINK)
        _recalcular(engine, campana)
        t = SellOutConsumo

        with sessionmaker(bind=engine, autoflush=False)() as db:
            usados = tienda_scope.usado_por_contador(
                db, (t.campana_id, t.canal, t.venta_ref, t.unidades, t.monto), [campana]
            )

        assert usados == {
            campana: (
                {("oficial", GAUSS): 3, ("oficial", TPLINK): 4},
                {("oficial", GAUSS): Decimal("30.00"), ("oficial", TPLINK): Decimal("40.00")},
            )
        }
