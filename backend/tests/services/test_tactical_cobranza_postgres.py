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
from tests.services.sell_in import _bono_world as bw
from tests.services.sell_in import _world as w
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
            for table in (
                "sell_out_consumos",
                "sell_out_campanas",
                "offset_grupos",
                "auditoria",
                "sell_in_bono_consumos",
            ):
                conn.execute(text(f"DELETE FROM {table}"))
            for table in ("tactical_cobranzas", "tactical_tiendas", "tactical_marcas"):
                conn.execute(text(f"DELETE FROM {table}"))
        bw.clean(engine)
        with engine.begin() as conn:
            conn.execute(text("UPDATE productos_erp SET categoria = 'Routers', iva = 21"))
            conn.execute(text("DELETE FROM tacticals"))


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


def _segun_las_lineas(db: Session, filtros: service.Filtros) -> dict:
    """The KPIs the slow way: every filtered tactical serialized, its lines' `monto_usado` summed per currency (what
    the list's Avance column shows). The SQL aggregate must give exactly these numbers."""
    tacticals = service.listar(db, filtros, 1, 500, hoy=HOY)[1]
    salida = {}
    for clave, cobrados in (("pendientes", False), ("cobrados", True)):
        grupo = [t for t in service.serializar(db, tacticals) if (t["cobranza"] is not None) == cobrados]
        montos: dict[str, Decimal] = {}
        for t in grupo:
            for linea in t["lineas"]:
                montos[linea["moneda"]] = montos.get(linea["moneda"], Decimal(0)) + Decimal(linea["monto_usado"])
        salida[clave] = {
            "cantidad": len(grupo),
            "montos": [
                {"moneda": m, "monto": montos[m].quantize(Decimal("0.01"))} for m in ("ARS", "USD") if m in montos
            ],
        }
    return salida


def _compras_de(engine: Engine, tactical_id: int) -> list[int]:
    with engine.connect() as conn:
        return list(conn.execute(text("SELECT id FROM sell_in_compra_items WHERE compra_id IN "
                                      "(SELECT id FROM sell_in_compras WHERE tactical_id = :t) ORDER BY id"),
                                 {"t": tactical_id}).scalars())  # fmt: skip


def _consumo_compra(engine: Engine, compra_item_id: int, ars: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sell_in_consumos (compra_item_id, canal, venta_ref, item_id, fecha_venta, unidades, "
                "descuento_ars) VALUES (:c, 'fuera', :c, 2964, '2026-11-03', 1, :m)"
            ),
            {"c": compra_item_id, "m": ars},
        )


def _bono_de(engine: Engine, tactical_id: int) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM sell_in_bonos_marca WHERE tactical_id = :t"), {"t": tactical_id}
        ).scalar()


class TestKpisEnSql:
    """Advisory (1) on #2182: the KPIs are one SQL aggregate, with the very numbers the lines show, every engine."""

    def test_every_engine_gives_the_numbers_the_lines_show(self, db, engine) -> None:
        # Sell out campaign, ARS, with usage; and one with no usage at all (a 0 line still names its currency).
        campana = service.crear(db, _tactical(nombre="Campaña"), USUARIO)
        _usado(engine, campana.id, "123.45")
        service.crear(db, _tactical(nombre="Sin uso", moneda="USD", tc_modo="al_cobro"), USUARIO)
        # Sell in cost bonus (ARS) with what its sales got.
        costo = service.crear(
            db,
            _tactical("sell_in", [{"alcance": "productos", "item_ids": [2964], "modo_monto": "por_unidad", "valor": "36"}],
                      nombre="Costo"),
            USUARIO,
        )  # fmt: skip
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sell_in_bono_consumos (bono_id, canal, venta_ref, item_id, fecha_venta, unidades, "
                    "descuento_ars) VALUES (:b, 'fuera', 1, 2964, '2026-11-03', 2, 72.10), "
                    "(:b, 'fuera', 2, 2964, '2026-11-04', 1, 36.05)"
                ),
                {"b": _bono_de(engine, costo.id)},
            )
        # Sell in invoice percentage bonus: its active purchases in its own currency count; a voided one and one in
        # another currency do not.
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 10, 10))
        factura = service.crear(
            db,
            _tactical("sell_in", [{"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje",
                                   "valor": "5"}], nombre="Factura %", fecha_desde=None, fecha_hasta=None),
            USUARIO,
        )  # fmt: skip
        bono = _bono_de(engine, factura.id)
        moneda_bono = db.get(service.SellInBonoMarca, bono).moneda
        otra = "ARS" if moneda_bono == "USD" else "USD"
        for moneda, estado, monto in ((moneda_bono, "activa", "40.50"), (moneda_bono, "anulada", "999"),
                                      (otra, "activa", "555")):  # fmt: skip
            [item] = w.compra(engine, [(2964, 1, monto)], moneda=moneda, tipo_cambio="1000" if moneda == "USD" else None,
                              estado=estado)  # fmt: skip
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE sell_in_compras SET origen = 'bono_marca', bono_id = :b "
                         "WHERE id = (SELECT compra_id FROM sell_in_compra_items WHERE id = :i)"),
                    {"b": bono, "i": item},
                )  # fmt: skip
        # Sell in invoice fixed total in USD at a fixed rate: its sales took ARS, shown in USD at its own rate.
        pedido_total = bw.pedido(engine, {2270: 5}, date(2026, 10, 12))
        total = service.crear(
            db,
            _tactical("sell_in", [{"alcance": "factura", "pedido_compra_id": pedido_total, "modo_monto": "monto_total",
                                   "valor": "300"}], nombre="Total USD", moneda="USD", tc_modo="fijo",
                      tipo_cambio="1000.5", fecha_desde=None, fecha_hasta=None),
            USUARIO,
        )  # fmt: skip
        for compra_item in _compras_de(engine, total.id):
            _consumo_compra(engine, compra_item, "1000.51")
        service.cobrar(db, costo.id, _cobro(), USUARIO)
        service.cobrar(db, total.id, _cobro(), USUARIO)
        db.expire_all()

        filtros = service.Filtros(tipos=TODOS)
        kpis = service.kpis(db, filtros, hoy=HOY)

        assert kpis == _segun_las_lineas(db, filtros)
        assert kpis["cobrados"]["cantidad"] == 2
        assert {m["moneda"] for m in kpis["pendientes"]["montos"]} == {"ARS", "USD"}
        assert sum(m["monto"] for m in kpis["cobrados"]["montos"] if m["moneda"] == "ARS") == Decimal("108.15")
        assert sum(m["monto"] for m in kpis["pendientes"]["montos"] if m["moneda"] == "ARS") >= Decimal("123.45")

    def test_voided_tacticals_with_the_anulados_filter(self, db, engine) -> None:
        """Advisory (3): `estado=anulados` keeps only voided ones, in the list, the collection filter and the KPIs."""
        vigente = service.crear(db, _tactical(nombre="Vigente"), USUARIO)
        anulado_cobrado = service.crear(db, _tactical(nombre="Anulado cobrado"), USUARIO)
        anulado_pendiente = service.crear(db, _tactical(nombre="Anulado pendiente"), USUARIO)
        _usado(engine, vigente.id, "5")
        _usado(engine, anulado_cobrado.id, "70")
        _usado(engine, anulado_pendiente.id, "30.25")
        service.cobrar(db, anulado_cobrado.id, _cobro(), USUARIO)
        service.anular(db, anulado_cobrado.id, USUARIO, None)
        service.anular(db, anulado_pendiente.id, USUARIO, None)

        def ids(**filtros) -> list[int]:
            return sorted(t.id for t in service.listar(db, service.Filtros(tipos=TODOS, **filtros), 1, 50, hoy=HOY)[1])

        assert ids(estado="anulados", cobranza="cobrados") == [anulado_cobrado.id]
        assert ids(estado="anulados", cobranza="pendientes") == [anulado_pendiente.id]
        filtros = service.Filtros(tipos=TODOS, estado="anulados")
        assert service.kpis(db, filtros, hoy=HOY) == {
            "pendientes": {"cantidad": 1, "montos": [{"moneda": "ARS", "monto": Decimal("30.25")}]},
            "cobrados": {"cantidad": 1, "montos": [{"moneda": "ARS", "monto": Decimal("70.00")}]},
        }
        assert service.kpis(db, filtros, hoy=HOY) == _segun_las_lineas(db, filtros)
