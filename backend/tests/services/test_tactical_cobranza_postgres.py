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


def _usado(engine: Engine, tactical_id: int, monto: str, venta_ref: int = 1) -> None:
    """Sale `venta_ref` consumed `monto` of the tactical's only campaign: what the list shows as its money used."""
    with engine.begin() as conn:
        cid = conn.execute(text("SELECT id FROM sell_out_campanas WHERE tactical_id = :t"), {"t": tactical_id}).scalar()
        conn.execute(
            text(
                "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
                "VALUES (:c, 'fuera', :r, 2964, '2026-11-03', 1, :m)"
            ),
            {"c": cid, "r": venta_ref, "m": monto},
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
            "pendientes": {"cantidad": 3, "sin_tope": 3,
                           "montos": [{"moneda": "ARS", "monto": Decimal("70.50"), "tope": None},
                                      {"moneda": "USD", "monto": Decimal("7.00"), "tope": None}]},
            "cobrados": {"cantidad": 1, "sin_tope": 1,
                         "montos": [{"moneda": "ARS", "monto": Decimal("100.00"), "tope": None}]},
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
            "pendientes": {
                "cantidad": 1,
                "sin_tope": 1,
                "montos": [{"moneda": "ARS", "monto": Decimal("10.00"), "tope": None}],
            },
            "cobrados": {"cantidad": 0, "sin_tope": 0, "montos": []},
        }
        assert (solo_cobrados["pendientes"]["cantidad"], solo_cobrados["cobrados"]["cantidad"]) == (1, 1)


def _tope_de(linea: dict) -> Decimal | None:
    """A line's money cap as the list shows it: its `tope_monto`, or the total of a Monto total line (its own cap)."""
    if linea["tope_monto"] is not None:
        return Decimal(linea["tope_monto"])
    return Decimal(linea["valor"]) if linea["modo_monto"] == "monto_total" else None


def _segun_las_lineas(db: Session, filtros: service.Filtros) -> dict:
    """The KPIs the slow way: every filtered tactical serialized, its lines' `monto_usado` summed per currency (what
    the list's Avance column shows) and their money caps (S6). The SQL aggregate must give exactly these numbers."""
    tacticals = service.listar(db, filtros, 1, 500, hoy=HOY)[1]
    salida = {}
    for clave, cobrados in (("pendientes", False), ("cobrados", True)):
        grupo = [t for t in service.serializar(db, tacticals) if (t["cobranza"] is not None) == cobrados]
        montos: dict[str, Decimal] = {}
        topes: dict[str, Decimal] = {}
        for t in grupo:
            for linea in t["lineas"]:
                montos[linea["moneda"]] = montos.get(linea["moneda"], Decimal(0)) + Decimal(linea["monto_usado"])
                if (tope := _tope_de(linea)) is not None:
                    topes[linea["moneda"]] = topes.get(linea["moneda"], Decimal(0)) + tope
        salida[clave] = {
            "cantidad": len(grupo),
            "sin_tope": sum(1 for t in grupo if all(_tope_de(linea) is None for linea in t["lineas"])),
            "montos": [
                {
                    "moneda": m,
                    "monto": montos[m].quantize(Decimal("0.01")),
                    "tope": topes[m].quantize(Decimal("0.01")) if m in topes else None,
                }
                for m in ("ARS", "USD")
                if m in montos
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


def _consumo_bono(engine: Engine, bono_id: int, *ventas: tuple[int, int, str]) -> None:
    """Sales `(venta_ref, unidades, descuento_ars)` a cost bonus lowered."""
    with engine.begin() as conn:
        for ref, unidades, ars in ventas:
            conn.execute(
                text(
                    "INSERT INTO sell_in_bono_consumos (bono_id, canal, venta_ref, item_id, fecha_venta, unidades, "
                    "descuento_ars) VALUES (:b, 'fuera', :r, 2964, '2026-11-03', :u, :m)"
                ),
                {"b": bono_id, "r": ref, "u": unidades, "m": ars},
            )


def _bono_de(engine: Engine, tactical_id: int) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM sell_in_bonos_marca WHERE tactical_id = :t"), {"t": tactical_id}
        ).scalar()


class TestKpisEnSql:
    """Advisory (1) on #2182: the KPIs are one SQL aggregate, with the very numbers the lines show, every engine."""

    def test_every_engine_gives_the_numbers_the_lines_show(self, db, engine) -> None:
        costo_linea = [{"alcance": "productos", "item_ids": [2964], "modo_monto": "por_unidad", "valor": "36"}]

        def total_usd(nombre: str, pedido_id: int) -> service.Tactical:
            linea = {"alcance": "factura", "pedido_compra_id": pedido_id, "modo_monto": "monto_total", "valor": "300"}
            return service.crear(
                db,
                _tactical("sell_in", [linea], nombre=nombre, moneda="USD", tc_modo="fijo", tipo_cambio="1000.5",
                          fecha_desde=None, fecha_hasta=None),
                USUARIO,
            )  # fmt: skip

        # Sell out campaign, ARS, with two sales; and one in USD with no usage (a 0 line still names its currency).
        campana = service.crear(db, _tactical(nombre="Campaña"), USUARIO)
        _usado(engine, campana.id, "123.45", venta_ref=1)
        _usado(engine, campana.id, "7.55", venta_ref=2)
        service.crear(db, _tactical(nombre="Sin uso", moneda="USD", tc_modo="al_cobro"), USUARIO)
        # Sell in cost bonus (ARS) with what its sales got.
        costo = service.crear(db, _tactical("sell_in", costo_linea, nombre="Costo"), USUARIO)
        # Sell in invoice percentage bonus (the tactical's ARS): its active ARS purchases count; a voided one and one
        # in USD do not.
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 10, 10))
        factura = service.crear(
            db,
            _tactical("sell_in", [{"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje",
                                   "valor": "5"}], nombre="Factura %", fecha_desde=None, fecha_hasta=None),
            USUARIO,
        )  # fmt: skip
        bono = _bono_de(engine, factura.id)
        assert db.get(service.SellInBonoMarca, bono).moneda == "ARS"
        for moneda, estado, monto in (("ARS", "activa", "40.50"), ("ARS", "anulada", "999"), ("USD", "activa", "555")):
            [item] = w.compra(engine, [(2964, 1, monto)], moneda=moneda, tipo_cambio="1000" if moneda == "USD" else None,
                              estado=estado)  # fmt: skip
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE sell_in_compras SET origen = 'bono_marca', bono_id = :b "
                         "WHERE id = (SELECT compra_id FROM sell_in_compra_items WHERE id = :i)"),
                    {"b": bono, "i": item},
                )  # fmt: skip
        # Sell in invoice fixed total in USD at a fixed rate: its sales took ARS, shown in USD at its own rate
        # (ARS 2.501,25 / 1.000,5 = USD 2,50).
        total = total_usd("Total USD", bw.pedido(engine, {2270: 5}, date(2026, 10, 12)))
        # Caps (S6): a sell out line with a money cap, and a sell in cost total loaded in USD, whose bonus keeps the
        # ARS total at the fixed rate (USD 2 x 1.000,5 = ARS 2.001), so its cap counts in ARS as its usage does.
        service.crear(db, _tactical(nombre="Tope", lineas=[{"alcance": "marca", "marca": bw.TPLINK,
                                                           "modo_monto": "por_unidad", "valor": "10", "tope_monto": "500"}]),
                      USUARIO)  # fmt: skip
        service.crear(
            db,
            _tactical("sell_in", [{"alcance": "productos", "item_ids": [2964], "modo_monto": "monto_total", "valor": "2",
                                   "reparto_criterio": "iguales"}], nombre="Costo total USD", moneda="USD",
                      tc_modo="fijo", tipo_cambio="1000.5"),
            USUARIO,
        )  # fmt: skip
        # Voided after they were used: a campaign, a cost bonus and an invoice total. The list still shows what each
        # used, so the KPIs count it too.
        campana_anulada = service.crear(db, _tactical(nombre="Campaña anulada"), USUARIO)
        _usado(engine, campana_anulada.id, "10.10")
        costo_anulado = service.crear(db, _tactical("sell_in", costo_linea, nombre="Costo anulado"), USUARIO)
        total_anulado = total_usd("Total USD anulado", bw.pedido(engine, {2964: 3}, date(2026, 10, 14)))
        for anulado in (campana_anulada, costo_anulado, total_anulado):
            service.anular(db, anulado.id, USUARIO, None)
        # The sell in usage rows stand in for what the FIFO drain wrote; they go in after the voids, since voiding a
        # bonus or a purchase queues a recompute that rebuilds them (to nothing here, with no real sales).
        _consumo_bono(engine, _bono_de(engine, costo.id), (1, 2, "72.10"), (2, 1, "36.05"))
        _consumo_bono(engine, _bono_de(engine, costo_anulado.id), (3, 1, "20.20"))
        [compra_item] = _compras_de(engine, total.id)
        _consumo_compra(engine, compra_item, "2501.25")
        [compra_item] = _compras_de(engine, total_anulado.id)
        _consumo_compra(engine, compra_item, "500.25")  # USD 0,50
        service.cobrar(db, costo.id, _cobro(), USUARIO)
        service.cobrar(db, total.id, _cobro(), USUARIO)
        service.cobrar(db, total_anulado.id, _cobro(), USUARIO)
        db.expire_all()

        filtros = service.Filtros(tipos=TODOS)
        kpis = service.kpis(db, filtros, hoy=HOY)

        assert kpis == _segun_las_lineas(db, filtros)
        assert kpis == {
            # Campaña 131,00 + Factura % 40,50 + Campaña anulada 10,10 + Costo anulado 20,20; Sin uso USD 0. Caps:
            # Tope 500 + Costo total USD 2.001; the other 5 have none.
            "pendientes": {"cantidad": 7, "sin_tope": 5,
                           "montos": [{"moneda": "ARS", "monto": Decimal("201.80"), "tope": Decimal("2501.00")},
                                      {"moneda": "USD", "monto": Decimal("0.00"), "tope": None}]},
            # Costo 108,15; Total USD 2,50 + Total USD anulado 0,50, each capped by its USD 300 total; Costo has none.
            "cobrados": {"cantidad": 3, "sin_tope": 1,
                         "montos": [{"moneda": "ARS", "monto": Decimal("108.15"), "tope": None},
                                    {"moneda": "USD", "monto": Decimal("3.00"), "tope": Decimal("600.00")}]},
        }  # fmt: skip

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
            "pendientes": {
                "cantidad": 1,
                "sin_tope": 1,
                "montos": [{"moneda": "ARS", "monto": Decimal("30.25"), "tope": None}],
            },
            "cobrados": {
                "cantidad": 1,
                "sin_tope": 1,
                "montos": [{"moneda": "ARS", "monto": Decimal("70.00"), "tope": None}],
            },
        }
        assert service.kpis(db, filtros, hoy=HOY) == _segun_las_lineas(db, filtros)
