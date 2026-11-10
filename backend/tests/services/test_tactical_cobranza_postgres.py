"""Tactical collection check (tactical cobranza S1, S2, S4) on Postgres: one record per tactical, undo, the list's
Cobrados / Pendientes filter and its KPIs.

Owner, 2026-11-10: "Eso que se vaya marcando como cobrado, filtro de cobrados o pendientes y kpis de pendientes y
cobrados."
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.schemas.tacticals import TacticalCobranzaIn
from app.services import tacticals as service
from tests.services.sell._schema import throwaway_schema
from tests.services.test_tacticals_postgres import STUBS, TABLES, USUARIO, _install, _tactical

pytestmark = pytest.mark.postgres

HOY = date(2026, 11, 5)
TODOS = ["sell_in", "sell_out"]


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("tactical_cobranza_svc", TABLES, STUBS, after=_install) as e:
        yield e


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        with engine.begin() as conn:
            for table in ("sell_out_consumos", "sell_out_campanas", "offset_grupos", "auditoria"):
                conn.execute(text(f"DELETE FROM {table}"))
            for table in ("tactical_cobranzas", "tactical_tiendas", "tactical_marcas", "tacticals"):
                conn.execute(text(f"DELETE FROM {table}"))


def _usado(engine: Engine, tactical_id: int, monto: str) -> None:
    """A sale consumed `monto` of the tactical's only campaign: what the list shows as its money used."""
    with engine.begin() as conn:
        cid = conn.execute(text("SELECT id FROM sell_out_campanas WHERE tactical_id = :t"), {"t": tactical_id}).scalar()
        conn.execute(
            text(
                "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
                "VALUES (:c, 'fuera', :c, 2964, '2026-11-03', 1, :m)"
            ),
            {"c": cid, "m": monto},
        )


def _cobro(**valores) -> TacticalCobranzaIn:
    return TacticalCobranzaIn(**{"fecha_cobro": date(2026, 11, 9), **valores})


def _leido(db: Session, tactical_id: int) -> dict:
    db.expire_all()
    return service.serializar(db, [db.get(service.Tactical, tactical_id)])[0]


class TestCobrar:
    def test_a_tactical_without_a_record_reads_pending(self, db) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        assert _leido(db, tactical.id)["cobranza"] is None

    def test_saving_marks_it_collected_with_every_field_and_the_author(self, db) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        service.cobrar(db, tactical.id, _cobro(medio="nota_credito", nc_numero=" NC 0003-123 ",
                                               observaciones="Llegó con la NC de octubre"), USUARIO)  # fmt: skip

        cobranza = _leido(db, tactical.id)["cobranza"]
        assert {
            k: cobranza[k]
            for k in (
                "fecha_cobro",
                "medio",
                "nc_numero",
                "distribuidor",
                "otro_detalle",
                "observaciones",
                "usuario_id",
            )
        } == {  # fmt: skip
            "fecha_cobro": date(2026, 11, 9),
            "medio": "nota_credito",
            "nc_numero": "NC 0003-123",
            "distribuidor": None,
            "otro_detalle": None,
            "observaciones": "Llegó con la NC de octubre",
            "usuario_id": USUARIO,
        }

    def test_only_the_date_is_required(self, db) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        service.cobrar(db, tactical.id, _cobro(), USUARIO)

        cobranza = _leido(db, tactical.id)["cobranza"]
        assert (cobranza["fecha_cobro"], cobranza["medio"], cobranza["observaciones"]) == (
            date(2026, 11, 9),
            None,
            None,
        )

    def test_saving_again_edits_the_one_record(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        service.cobrar(db, tactical.id, _cobro(medio="nota_credito", nc_numero="NC 1"), USUARIO)

        service.cobrar(db, tactical.id, _cobro(fecha_cobro=date(2026, 11, 10), medio="fondo_distribuidor",
                                               distribuidor="Grupo Núcleo"), USUARIO)  # fmt: skip

        cobranza = _leido(db, tactical.id)["cobranza"]
        assert (cobranza["fecha_cobro"], cobranza["medio"], cobranza["nc_numero"], cobranza["distribuidor"]) == (
            date(2026, 11, 10), "fondo_distribuidor", None, "Grupo Núcleo",
        )  # fmt: skip
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM tactical_cobranzas")).scalar() == 1

    def test_undo_leaves_it_pending_and_an_unknown_tactical_is_none(self, db) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        service.cobrar(db, tactical.id, _cobro(medio="otro", otro_detalle="Transferencia"), USUARIO)

        assert service.deshacer_cobro(db, tactical.id) is True
        assert _leido(db, tactical.id)["cobranza"] is None
        assert service.deshacer_cobro(db, tactical.id) is False
        assert service.cobrar(db, 999999, _cobro(), USUARIO) is None


class TestListar:
    def _ids(self, db, **filtros) -> list[int]:
        filtros = service.Filtros(**{"tipos": TODOS, **filtros})
        return sorted(t.id for t in service.listar(db, filtros, 1, 50, hoy=HOY)[1])

    def test_the_collection_filter(self, db) -> None:
        cobrado = service.crear(db, _tactical(nombre="Cobrado"), USUARIO)
        pendiente = service.crear(db, _tactical(nombre="Pendiente"), USUARIO)
        service.cobrar(db, cobrado.id, _cobro(), USUARIO)

        assert self._ids(db, cobranza="cobrados") == [cobrado.id]
        assert self._ids(db, cobranza="pendientes") == [pendiente.id]
        assert self._ids(db) == sorted([cobrado.id, pendiente.id])
        assert service.listar(db, service.Filtros(tipos=TODOS, cobranza="cobrados"), 1, 50, hoy=HOY)[0] == 1


class TestKpis:
    def test_count_and_money_used_per_currency_of_pending_and_collected(self, db, engine) -> None:
        a = service.crear(db, _tactical(nombre="A"), USUARIO)
        b = service.crear(db, _tactical(nombre="B"), USUARIO)
        c = service.crear(db, _tactical(nombre="C", moneda="USD", tc_modo="al_cobro"), USUARIO)
        cobrado = service.crear(db, _tactical(nombre="Cobrado"), USUARIO)
        _usado(engine, a.id, "50")
        _usado(engine, b.id, "20.5")
        _usado(engine, c.id, "7")
        _usado(engine, cobrado.id, "100")
        service.cobrar(db, cobrado.id, _cobro(), USUARIO)

        kpis = service.kpis(db, service.Filtros(tipos=TODOS), hoy=HOY)

        assert kpis == {
            "pendientes": {"cantidad": 3, "montos": [{"moneda": "ARS", "monto": Decimal("70.50")},
                                                     {"moneda": "USD", "monto": Decimal("7.00")}]},
            "cobrados": {"cantidad": 1, "montos": [{"moneda": "ARS", "monto": Decimal("100.00")}]},
        }  # fmt: skip

    def test_they_follow_the_other_filters_but_not_the_collection_one(self, db, engine) -> None:
        hot = service.crear(db, _tactical(nombre="Hot sale"), USUARIO)
        otro = service.crear(db, _tactical(nombre="Otro"), USUARIO)
        _usado(engine, hot.id, "10")
        _usado(engine, otro.id, "30")
        service.cobrar(db, otro.id, _cobro(), USUARIO)

        por_texto = service.kpis(db, service.Filtros(tipos=TODOS, q="hot"), hoy=HOY)
        solo_cobrados = service.kpis(db, service.Filtros(tipos=TODOS, cobranza="cobrados"), hoy=HOY)

        assert por_texto == {
            "pendientes": {"cantidad": 1, "montos": [{"moneda": "ARS", "monto": Decimal("10.00")}]},
            "cobrados": {"cantidad": 0, "montos": []},
        }
        assert (solo_cobrados["pendientes"]["cantidad"], solo_cobrados["cobrados"]["cantidad"]) == (1, 1)
