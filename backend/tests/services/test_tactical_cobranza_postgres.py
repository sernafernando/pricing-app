"""Tactical collection check (tactical cobranza S1, S2, S4) on Postgres: one record per tactical, undo, the list's
Cobrados / Pendientes filter and its KPIs.

Owner, 2026-11-10: "Eso que se vaya marcando como cobrado, filtro de cobrados o pendientes y kpis de pendientes y
cobrados."
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.schemas.tacticals import TacticalCobranzaIn
from app.services import tacticals as service
from tests.services._aprobacion import aprobar_siempre  # noqa: F401 - the fixture, by name
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _bono_world as bw
from tests.services.sell_in import _world as w
from tests.services.test_tacticals_postgres import STUBS, TABLES, USUARIO, _install, _tactical, paso

# Written before tacticals approval: every load is approved right away (`_aprobacion.aprobar_siempre`).
pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("aprobar_siempre")]

HOY = date(2026, 11, 5)
TODOS = ["sell_in", "sell_out"]
GENERADO = "app.services.costo_si.generado"


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
                "costo_si_pasos",
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
                           "montos": [{"moneda": "ARS", "monto": Decimal("70.50"), "tope": None, "tope_parcial": False, "estimado": False},
                                      {"moneda": "USD", "monto": Decimal("7.00"), "tope": None, "tope_parcial": False, "estimado": False}]},
            "cobrados": {"cantidad": 1, "sin_tope": 1,
                         "montos": [{"moneda": "ARS", "monto": Decimal("100.00"), "tope": None, "tope_parcial": False, "estimado": False}]},
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
                "montos": [
                    {"moneda": "ARS", "monto": Decimal("10.00"), "tope": None, "tope_parcial": False, "estimado": False}
                ],
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
        sin_tope: set[str] = set()  # currencies with an uncapped line
        estimados: set[str] = set()  # currencies with an estimated line
        for t in grupo:
            for linea in t["lineas"]:
                if linea["monto_estimado"]:
                    estimados.add(linea["moneda"])
                montos[linea["moneda"]] = montos.get(linea["moneda"], Decimal(0)) + Decimal(linea["monto_usado"])
                if (tope := _tope_de(linea)) is not None:
                    topes[linea["moneda"]] = topes.get(linea["moneda"], Decimal(0)) + tope
                else:
                    sin_tope.add(linea["moneda"])
        salida[clave] = {
            "cantidad": len(grupo),
            "sin_tope": sum(1 for t in grupo if all(_tope_de(linea) is None for linea in t["lineas"])),
            "montos": [
                {
                    "moneda": m,
                    "monto": montos[m].quantize(Decimal("0.01")),
                    "tope": topes[m].quantize(Decimal("0.01")) if m in topes else None,
                    # Advisory on #2195: the cap covers only some of the generated lines.
                    "tope_parcial": m in topes and m in sin_tope,
                    # Tactical sell in USD S10: some line in this currency is still an estimate.
                    "estimado": m in estimados,
                }
                for m in ("ARS", "USD")
                if m in montos
            ],
        }
    return salida


def _compra_de(engine: Engine, tactical_id: int) -> int:
    """The invoice total's purchase (`sell_in_compras.id`): the `ref` of a 'compra' sell in on a costo SI step."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT id FROM sell_in_compras WHERE tactical_id = :t"), {"t": tactical_id}).scalar()


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
        # Sell in invoice fixed total in USD: what costo SI took off its invoice, in USD.
        total = total_usd("Total USD", bw.pedido(engine, {2270: 5}, date(2026, 10, 12)))
        # Caps (S6): a sell out line with a money cap. (A sell in cost total can no longer be loaded: T5 PR A, L25.)
        service.crear(db, _tactical(nombre="Tope", lineas=[{"alcance": "marca", "marca": bw.TPLINK,
                                                           "modo_monto": "por_unidad", "valor": "10", "tope_monto": "500"}]),
                      USUARIO)  # fmt: skip
        # Voided after they were used: a campaign, a cost bonus and an invoice total. The list still shows what each
        # used, so the KPIs count it too.
        campana_anulada = service.crear(db, _tactical(nombre="Campaña anulada"), USUARIO)
        _usado(engine, campana_anulada.id, "10.10")
        costo_anulado = service.crear(db, _tactical("sell_in", costo_linea, nombre="Costo anulado"), USUARIO)
        total_anulado = total_usd("Total USD anulado", bw.pedido(engine, {2964: 3}, date(2026, 10, 14)))
        for anulado in (campana_anulada, costo_anulado, total_anulado):
            service.anular(db, anulado.id, USUARIO, None)
        # What each sell in line used: the costo SI purchase steps that carry it (T5 PR B, L26). The cost bonus is
        # ARS on a USD product, at each ARS invoice's own rate: 2 x 3.605 x 1% x 1000 + 1 x 3.605 x 1% x 1000.
        bono = _bono_de(engine, costo.id)
        paso(engine, 2964, 1, 2, "3.605", [("bono", bono, "1.0000")], tipo_cambio=1000)
        paso(engine, 2964, 2, 1, "3.605", [("bono", bono, "1.0000")], tipo_cambio=1000)
        paso(engine, 2964, 3, 1, "2.02", [("bono", _bono_de(engine, costo_anulado.id), "1.0000")], tipo_cambio=1000)
        paso(engine, 2964, 4, 1, "2.50", [("compra", _compra_de(engine, total.id), "100.0000")])
        paso(engine, 2964, 5, 1, "0.50", [("compra", _compra_de(engine, total_anulado.id), "100.0000")])
        service.cobrar(db, costo.id, _cobro(), USUARIO)
        service.cobrar(db, total.id, _cobro(), USUARIO)
        service.cobrar(db, total_anulado.id, _cobro(), USUARIO)
        db.expire_all()

        filtros = service.Filtros(tipos=TODOS)
        kpis = service.kpis(db, filtros, hoy=HOY)

        assert kpis == _segun_las_lineas(db, filtros)
        assert kpis == {
            # Campaña 131,00 + Factura % 40,50 + Campaña anulada 10,10 + Costo anulado 20,20; Sin uso USD 0. Caps:
            # Tope 500; the other 5 have none.
            "pendientes": {"cantidad": 6, "sin_tope": 5,
                           "montos": [{"moneda": "ARS", "monto": Decimal("201.80"), "tope": Decimal("500.00"),
                                       "tope_parcial": True, "estimado": False},
                                      {"moneda": "USD", "monto": Decimal("0.00"), "tope": None, "tope_parcial": False, "estimado": False}]},
            # Costo 108,15; Total USD 2,50 + Total USD anulado 0,50, each capped by its USD 300 total; Costo has none.
            "cobrados": {"cantidad": 3, "sin_tope": 1,
                         "montos": [{"moneda": "ARS", "monto": Decimal("108.15"), "tope": None, "tope_parcial": False, "estimado": False},
                                    {"moneda": "USD", "monto": Decimal("3.00"), "tope": Decimal("600.00"),
                                     "tope_parcial": False, "estimado": False}]},
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
                "montos": [
                    {"moneda": "ARS", "monto": Decimal("30.25"), "tope": None, "tope_parcial": False, "estimado": False}
                ],
            },
            "cobrados": {
                "cantidad": 1,
                "sin_tope": 1,
                "montos": [
                    {"moneda": "ARS", "monto": Decimal("70.00"), "tope": None, "tope_parcial": False, "estimado": False}
                ],
            },
        }
        assert service.kpis(db, filtros, hoy=HOY) == _segun_las_lineas(db, filtros)


_POR_UNIDAD_USD = {"alcance": "productos", "item_ids": [2964], "modo_monto": "por_unidad", "valor": "10.91",
                   "tope_unidades": 4}  # fmt: skip


def _usd(db, tc_modo: str = "al_cobro", lineas=None, **cabecera):
    return service.crear(
        db, _tactical("sell_in", lineas or [_POR_UNIDAD_USD], moneda="USD", tc_modo=tc_modo, **cabecera), USUARIO
    )


def _bono_de(engine: Engine, tactical_id: int) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM sell_in_bonos_marca WHERE tactical_id = :t"), {"t": tactical_id}
        ).scalar()


class TestTipoDeCambioDelCobro:
    """Owner: "Ponelo donde se carga el cobro." The rate the brand paid at is loaded with the collection; it is what
    a USD `al_cobro` cost line converts at from then on (tactical sell in USD S2, S8)."""

    # sell-in-costo-si T5 PR A, L24: nothing converts a cost bonus per sale any more, so no collection asks for it.
    def test_a_usd_al_cobro_sell_in_no_longer_asks_for_it_but_still_stores_one_given(self, db, engine) -> None:
        tactical = _usd(db)
        assert _leido(db, tactical.id)["pide_tc_cobro"] is False

        service.cobrar(db, tactical.id, _cobro(tipo_cambio=Decimal("1350.5")), USUARIO)

        assert _leido(db, tactical.id)["cobranza"]["tipo_cambio"] == Decimal("1350.500000")

    def test_without_it_the_collection_is_saved_and_a_stored_rate_is_kept(self, db, engine) -> None:
        tactical = _usd(db)

        service.cobrar(db, tactical.id, _cobro(), USUARIO)
        assert _leido(db, tactical.id)["cobranza"]["tipo_cambio"] is None

        service.cobrar(db, tactical.id, _cobro(tipo_cambio=Decimal("1350")), USUARIO)
        service.cobrar(db, tactical.id, _cobro(), USUARIO)
        assert _leido(db, tactical.id)["cobranza"]["tipo_cambio"] == Decimal("1350.000000")

    @pytest.mark.parametrize(
        "kind",
        ["ars", "fijo", "dia_venta", "sell_out", "al_cobro_sin_linea_usd", "al_cobro_solo_factura"],
    )
    def test_any_other_tactical_takes_no_rate_and_collects_as_before(self, db, engine, kind) -> None:
        porcentaje = {"alcance": "marca", "marca": bw.TPLINK, "modo_monto": "porcentaje", "valor": "3"}

        def factura() -> dict:
            pedido = bw.pedido(engine, {2964: 10}, date(2026, 10, 10))
            return {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje", "valor": "5"}

        tactical = {
            "ars": lambda: service.crear(db, _tactical("sell_in", [_POR_UNIDAD_USD]), USUARIO),
            "fijo": lambda: _usd(db, "fijo", tipo_cambio="1400"),
            "dia_venta": lambda: _usd(db, "dia_venta"),
            "sell_out": lambda: service.crear(db, _tactical(moneda="USD", tc_modo="al_cobro"), USUARIO),
            "al_cobro_sin_linea_usd": lambda: _usd(db, lineas=[porcentaje]),  # a % of the ARS cost: no rate needed
            # An invoice line carries the tactical's currency but discounts the invoice, not each sale's cost.
            "al_cobro_solo_factura": lambda: _usd(db, lineas=[factura()], fecha_desde=None, fecha_hasta=None),
        }[kind]()
        assert _leido(db, tactical.id)["pide_tc_cobro"] is False

        with pytest.raises(
            service.TacticalError, match="^Solo un tactical de sell in en USD con tipo de cambio al cobro"
        ):
            service.cobrar(db, tactical.id, _cobro(tipo_cambio=Decimal("1350")), USUARIO)
        service.cobrar(db, tactical.id, _cobro(), USUARIO)
        assert _leido(db, tactical.id)["cobranza"]["tipo_cambio"] is None

    def test_the_line_and_the_kpis_show_what_costo_si_took_off_its_invoices_whatever_the_collection_rate(
        self, db, engine
    ) -> None:
        """T5 PR B, L26: a USD cost line used what costo SI took off the invoices of its period, in USD; the rate the
        brand paid at converts nothing any more."""
        tactical = _usd(db)
        # USD 10.91 a unit on 2 units of USD 41.50: the step's % is 10.91 / 41.50.
        paso(engine, 2964, 1, 2, "41.50", [("bono", _bono_de(engine, tactical.id), "26.2892")])
        bw.tipo_cambio(engine, date(2026, 11, 1), 1200)
        service.cobrar(db, tactical.id, _cobro(tipo_cambio=Decimal("1350")), USUARIO)

        linea = _leido(db, tactical.id)["lineas"][0]
        kpis = service.kpis(db, service.Filtros(tipos=TODOS), hoy=HOY)

        assert (linea["moneda"], linea["unidades_usadas"], linea["monto_usado"]) == ("USD", 2, Decimal("21.82"))
        assert linea["monto_estimado"] is False
        assert kpis["cobrados"]["montos"] == [
            {"moneda": "USD", "monto": Decimal("21.82"), "tope": None, "tope_parcial": False, "estimado": False}
        ]


def _bonos_de(engine: Engine, tactical_id: int) -> list[int]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text("SELECT id FROM sell_in_bonos_marca WHERE tactical_id = :t ORDER BY tactical_linea"),
                {"t": tactical_id},
            ).scalars()
        )


class TestNadaEstimado:
    """T5 PR B, L26: what a line used is read off its invoices at each invoice's own rate, so no amount waits for the
    collection rate any more (tactical sell in USD S10's "estimado" is never set)."""

    _PORCENTAJE = {"alcance": "productos", "item_ids": [950], "modo_monto": "porcentaje", "valor": "3",
                   "tope_monto": "100"}  # fmt: skip

    def test_a_usd_percentage_line_with_usage_is_not_an_estimate_before_or_after_the_collection(
        self, db, engine
    ) -> None:
        tactical = _usd(db, lineas=[self._PORCENTAJE, _POR_UNIDAD_USD])
        porcentaje, por_unidad = _bonos_de(engine, tactical.id)
        # An ARS invoice of 950 (USD product) at its own rate 1200, and a USD one of 2964.
        paso(engine, 950, 1, 2, "9.90", [("bono", porcentaje, "3.0000")], tipo_cambio=1200)
        paso(engine, 2964, 1, 2, "41.50", [("bono", por_unidad, "26.2892")])

        for _ in ("before", "after"):
            lineas = sorted(_leido(db, tactical.id)["lineas"], key=lambda x: x["linea"])
            kpis = service.kpis(db, service.Filtros(tipos=TODOS), hoy=HOY)
            assert [(x["monto_usado"], x["monto_estimado"]) for x in lineas] == [
                (Decimal("0.59"), False),
                (Decimal("21.82"), False),
            ]
            assert all(not m["estimado"] for grupo in kpis.values() for m in grupo["montos"])
            assert kpis == _segun_las_lineas(db, service.Filtros(tipos=TODOS))
            service.cobrar(db, tactical.id, _cobro(tipo_cambio=Decimal("1350")), USUARIO)


class TestPasoSinCosto:
    """Interfaz §7: a costo SI step whose cost is unknown has no amount. It is left out of what the line used and of
    the KPIs, never counted as 0, and logged with its item and date."""

    def test_a_step_with_no_cost_is_left_out_of_the_line_and_the_kpis_and_logged(self, db, engine, caplog) -> None:
        tactical = _usd(db)
        bono = _bono_de(engine, tactical.id)
        paso(engine, 2964, 1, 2, "41.50", [("bono", bono, "26.2892")])
        paso(engine, 2964, 2, 3, None, [("bono", bono, "26.2892")], fecha=date(2026, 11, 4))

        with caplog.at_level(logging.WARNING, logger=GENERADO):
            linea = _leido(db, tactical.id)["lineas"][0]
            kpis = service.kpis(db, service.Filtros(tipos=TODOS), hoy=HOY)

        assert linea["monto_usado"] == Decimal("21.82")
        assert [m["monto"] for m in kpis["pendientes"]["montos"]] == [Decimal("21.82")]
        avisos = [r.getMessage() for r in caplog.records if r.name == GENERADO]
        # One from the line (its bonus's reader), one from the KPIs' SQL.
        assert len(avisos) == 2
        assert all(f"bono {bono}" in a and "item 2964 on 2026-11-04" in a for a in avisos)
