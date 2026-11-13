"""Tacticals service (`app.services.tacticals`, tacticals T1) on Postgres: each line becomes rows of the existing
engines, all or nothing; the read gives one line per child with what it used; voiding voids every child."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.offset_grupo import OffsetGrupo
from app.models.pedido_compra import PedidoCompra
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.sell_out import (
    SellOutCampana,
    SellOutCampanaGrupo,
    SellOutCampanaItem,
    SellOutConsumo,
    SellOutDirty,
    SellOutPrograma,
)
from app.models.tactical import TacticalCobranza, TacticalMarca, TacticalTienda
from app.schemas.sell_out import SellOutCampanaIn
from app.schemas.tacticals import TacticalIn
from app.services import tacticals as service
from app.services.sell_in import bonos
from app.services.sell_out import edicion_masiva, renovacion
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _bono_world as bw
from tests.services.sell_in import _world as w

pytestmark = pytest.mark.postgres

USUARIO = 7
TPLINK = bw.TPLINK
TABLES = [
    *bw.TABLES,
    MlTiendaOficial.__table__,
    TacticalTienda.__table__,
    TacticalMarca.__table__,
    TacticalCobranza.__table__,
    OffsetGrupo.__table__,
    OffsetGrupoFiltro.__table__,
    SellOutPrograma.__table__,
    SellOutCampana.__table__,
    SellOutCampanaGrupo.__table__,
    SellOutCampanaItem.__table__,
    SellOutConsumo.__table__,
    SellOutDirty.__table__,
]
STUBS = [*bw.STUBS, "CREATE TABLE offsets_ganancia (id INTEGER PRIMARY KEY)"]


def _install(engine: Engine) -> None:
    bw._install(engine)
    with engine.begin() as conn:
        # The engines load whole `PedidoCompra` rows: the stand-in gets the model's other columns, nullable, no FK.
        tiene = set(conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'pedidos_compra'"
        )).scalars())  # fmt: skip
        for columna in PedidoCompra.__table__.columns:
            if columna.name not in tiene:
                tipo = columna.type.compile(dialect=engine.dialect)
                conn.execute(text(f"ALTER TABLE pedidos_compra ADD COLUMN {columna.name} {tipo}"))
        conn.execute(text("UPDATE productos_erp SET categoria = 'Routers', iva = 21"))


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("tacticals_svc", TABLES, STUBS, after=_install) as engine:
        yield engine


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        with engine.begin() as conn:
            for table in ("sell_out_campanas", "offset_grupos", "auditoria"):
                conn.execute(text(f"DELETE FROM {table}"))
        bw.clean(engine)
        with engine.begin() as conn:
            conn.execute(text("UPDATE productos_erp SET categoria = 'Routers', iva = 21"))
            conn.execute(text("DELETE FROM tactical_tiendas"))
            conn.execute(text("DELETE FROM tactical_marcas"))
            conn.execute(text("DELETE FROM tacticals"))
            conn.execute(text("DELETE FROM ml_tiendas_oficiales"))
            conn.execute(text("DELETE FROM sell_out_dirty"))


def _contar(engine: Engine, tabla: str, where: str = "true") -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {tabla} WHERE {where}")).scalar()


def _tactical(tipo: str = "sell_out", lineas=None, **cabecera) -> TacticalIn:
    return TacticalIn(
        **{
            "tipo": tipo,
            "nombre": "Tactical noviembre",
            "marca": TPLINK,
            "fecha_desde": date(2026, 11, 1),
            "fecha_hasta": date(2026, 11, 30),
            "moneda": "ARS",
            "lineas": lineas or [{"alcance": "marca", "marca": TPLINK, "modo_monto": "por_unidad", "valor": "10"}],
            **cabecera,
        }
    )


class TestSellOut:
    def test_a_per_product_line_is_one_campaign_and_hidden_group_per_product(self, db, engine) -> None:
        data = _tactical(
            lineas=[
                {"alcance": "productos", "item_ids": [2964, 2270], "modo_monto": "por_unidad", "valor": "5",
                 "tope_unidades": 100, "tope_por_producto": True},
            ]
        )  # fmt: skip

        tactical = service.crear(db, data, USUARIO)

        with engine.connect() as conn:
            filas = conn.execute(
                text(
                    "SELECT c.tactical_id, c.tactical_linea, c.tope_unidades, g.oculto, f.item_id "
                    "FROM sell_out_campanas c JOIN sell_out_campana_grupos cg ON cg.campana_id = c.id "
                    "JOIN offset_grupos g ON g.id = cg.grupo_id JOIN offset_grupo_filtros f ON f.grupo_id = g.id "
                    "ORDER BY f.item_id"
                )
            ).all()
        assert [tuple(f) for f in filas] == [(tactical.id, 1, 100, True, 2270), (tactical.id, 1, 100, True, 2964)]
        [salida] = service.serializar(db, [tactical])
        assert [(x["linea"], x["tope_por_producto"], x["productos"][0]["item_id"]) for x in salida["lineas"]] == [
            (1, True, 2964),
            (1, True, 2270),
        ]
        assert salida["lineas"][0]["productos"][0]["descripcion"] == "Producto"

    def test_a_shared_line_is_one_campaign_with_the_line_s_usage(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        with engine.begin() as conn:
            cid = conn.execute(text("SELECT id FROM sell_out_campanas")).scalar()
            conn.execute(
                text(
                    "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
                    "VALUES (:c, 'fuera', 1, 2964, '2026-11-03', 3, 30), (:c, 'fuera', 2, 2270, '2026-11-04', 2, 20)"
                ),
                {"c": cid},
            )

        [linea] = service.serializar(db, [tactical])[0]["lineas"]
        assert (linea["alcance"], linea["marca"], linea["tope_por_producto"]) == ("marca", TPLINK, False)
        assert (linea["unidades_usadas"], linea["monto_usado"]) == (5, Decimal("50.00"))
        assert _contar(engine, "offset_grupos", "oculto") == 1

    def test_one_refused_line_stores_nothing(self, db, engine) -> None:
        data = _tactical(
            lineas=[
                {"alcance": "marca", "marca": TPLINK, "modo_monto": "por_unidad", "valor": "10"},
                {"alcance": "productos", "item_ids": [999999], "modo_monto": "por_unidad", "valor": "10"},
            ]
        )

        with pytest.raises(service.TacticalError, match="^Línea 2: no existen los productos 999999$"):
            service.crear(db, data, USUARIO)
        for tabla in ("tacticals", "sell_out_campanas", "offset_grupos", "auditoria"):
            assert _contar(engine, tabla) == 0

    def test_an_engine_refusal_names_its_line(self, db) -> None:
        data = _tactical(lineas=[{"alcance": "marca", "marca": TPLINK, "modo_monto": "monto_total", "valor": "900",
                                  "tope_unidades": 5}])  # fmt: skip

        with pytest.raises(service.TacticalError, match="^Línea 1: "):
            service.crear(db, data, USUARIO)

    def test_a_percentage_with_vat_flag_is_stored_without_it(self, db, engine) -> None:
        data = _tactical(incluye_iva=True, lineas=[{"alcance": "marca", "marca": TPLINK, "modo_monto": "porcentaje",
                                                    "valor": "3"}])  # fmt: skip

        service.crear(db, data, USUARIO)
        assert _contar(engine, "sell_out_campanas", "NOT monto_incluye_iva AND porcentaje = 3") == 1


class TestSellIn:
    def test_a_per_unit_cost_bonus_is_ars(self, db, engine) -> None:
        linea = {"alcance": "productos", "item_ids": [2964], "modo_monto": "por_unidad", "valor": "36"}

        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)
        assert _contar(engine, "sell_in_bonos_marca",
                       f"base = 'costo_venta' AND tipo = 'por_unidad' AND alcance = 'modelos' "
                       f"AND tactical_id = {tactical.id} AND tactical_linea = 1") == 1  # fmt: skip

        usd = _tactical("sell_in", [linea], moneda="USD")
        with pytest.raises(service.TacticalError, match="^Línea 1: una reducción de costo por unidad .* en pesos"):
            service.crear(db, usd, USUARIO)

    def test_an_invoice_tactical_takes_no_dates_and_its_bonus_takes_its_invoice_date(self, db, engine) -> None:
        """Tactical factura sin fecha S1/S2c: any invoice date; the header spans the oldest to the newest invoice."""
        vieja = bw.pedido(engine, {2964: 10}, date(2025, 3, 10))
        nueva = bw.pedido(engine, {2270: 5}, date(2026, 10, 10))
        lineas = [
            {"alcance": "factura", "pedido_compra_id": nueva, "modo_monto": "porcentaje", "valor": "5"},
            {"alcance": "factura", "pedido_compra_id": vieja, "modo_monto": "por_unidad", "valor": "2"},
        ]

        tactical = service.crear(db, _tactical("sell_in", lineas, fecha_desde=None, fecha_hasta=None), USUARIO)

        assert (tactical.fecha_desde, tactical.fecha_hasta) == (date(2025, 3, 10), date(2026, 10, 10))
        with engine.connect() as conn:
            fechas = conn.execute(
                text("SELECT pedido_id, fecha_desde, fecha_hasta FROM sell_in_bonos_marca ORDER BY tactical_linea")
            ).all()
        assert [tuple(f) for f in fechas] == [
            (nueva, date(2026, 10, 10), date(2026, 10, 10)),
            (vieja, date(2025, 3, 10), date(2025, 3, 10)),
        ]
        assert service.serializar(db, [tactical])[0]["por_factura"] is True

    def test_an_invoice_outside_the_dates_of_a_dated_tactical_is_accepted(self, db, engine) -> None:
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 10, 10))
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje", "valor": "5"}

        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)

        assert (tactical.fecha_desde, tactical.fecha_hasta) == (date(2026, 10, 10), date(2026, 10, 10))
        assert _contar(engine, "sell_in_bonos_marca", "fecha_desde = '2026-10-10' AND fecha_hasta = '2026-10-10'") == 1

    def test_a_mixed_tactical_needs_dates_and_keeps_them_for_its_other_lines(self, db, engine) -> None:
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 10, 10))
        lineas = [
            {"alcance": "marca", "marca": TPLINK, "modo_monto": "porcentaje", "valor": "3"},
            {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje", "valor": "5"},
        ]

        with pytest.raises(service.TacticalError) as exc:
            service.crear(db, _tactical("sell_in", lineas, fecha_desde=None, fecha_hasta=None), USUARIO)
        assert (
            str(exc.value)
            == "Las fechas son obligatorias: solo un tactical con todas sus líneas por factura va sin fechas"
        )

        tactical = service.crear(db, _tactical("sell_in", lineas), USUARIO)

        assert (tactical.fecha_desde, tactical.fecha_hasta) == (date(2026, 11, 1), date(2026, 11, 30))
        with engine.connect() as conn:
            fechas = conn.execute(
                text("SELECT alcance, fecha_desde, fecha_hasta FROM sell_in_bonos_marca ORDER BY tactical_linea")
            ).all()
        assert [tuple(f) for f in fechas] == [
            ("marca", date(2026, 11, 1), date(2026, 11, 30)),
            ("factura", date(2026, 10, 10), date(2026, 10, 10)),
        ]
        assert service.serializar(db, [tactical])[0]["por_factura"] is False

    def test_a_dated_line_still_needs_its_dates(self, db) -> None:
        linea = {"alcance": "marca", "marca": TPLINK, "modo_monto": "porcentaje", "valor": "3"}

        with pytest.raises(service.TacticalError, match="^Las fechas son obligatorias"):
            service.crear(db, _tactical("sell_in", [linea], fecha_hasta=None), USUARIO)
        with pytest.raises(service.TacticalError, match="^Las fechas son obligatorias"):
            service.crear(db, _tactical(fecha_desde=None, fecha_hasta=None), USUARIO)

    def test_a_corrected_invoice_date_moves_the_header_of_an_invoice_tactical(self, db, engine) -> None:
        """Verifier advisory on L6: the header keeps spanning its invoices (oldest..newest) after Compras corrects one;
        a mixed tactical's header keeps its own dates."""
        vieja = bw.pedido(engine, {2964: 10}, date(2026, 3, 10))
        nueva = bw.pedido(engine, {2270: 5}, date(2026, 10, 10))
        lineas = [
            {"alcance": "factura", "pedido_compra_id": vieja, "modo_monto": "porcentaje", "valor": "5"},
            {"alcance": "factura", "pedido_compra_id": nueva, "modo_monto": "por_unidad", "valor": "2"},
        ]
        factura = service.crear(db, _tactical("sell_in", lineas, fecha_desde=None, fecha_hasta=None), USUARIO)
        marca = {"alcance": "marca", "marca": TPLINK, "modo_monto": "porcentaje", "valor": "3"}
        mixto = service.crear(db, _tactical("sell_in", [marca, lineas[1]], nombre="Mixto"), USUARIO)
        bonos.reconciliar(db, pedido_ids=[vieja, nueva])
        db.commit()

        bw.update_pedido(engine, nueva, fecha_factura=date(2026, 12, 5))
        bonos.reconciliar(db, pedido_ids=[nueva])
        db.commit()

        with engine.connect() as conn:
            fechas = dict(
                (t, (d, h))
                for t, d, h in conn.execute(text("SELECT id, fecha_desde, fecha_hasta FROM tacticals")).all()
            )
        assert fechas[factura.id] == (date(2026, 3, 10), date(2026, 12, 5))
        assert fechas[mixto.id] == (date(2026, 11, 1), date(2026, 11, 30))

    def test_the_invoice_units_get_the_rebate_whenever_they_are_sold_until_they_run_out(self, db, engine) -> None:
        pedido = bw.pedido(engine, {2964: 700}, date(2026, 10, 10))
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "por_unidad", "valor": "2"}
        service.crear(db, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None), USUARIO)
        primera = w.venta(engine, "fuera", 2964, 500, date(2027, 6, 1))
        segunda = w.venta(engine, "fuera", 2964, 300, date(2028, 1, 15))
        tercera = w.venta(engine, "fuera", 2964, 10, date(2028, 2, 1))

        bonos.reconciliar(db, pedido_ids=[pedido])
        db.commit()

        assert [(c[2], c[4]) for c in w.consumos(engine)] == [(primera, 500), (segunda, 200)]
        assert tercera not in [c[2] for c in w.consumos(engine)]

    def test_an_invoice_percentage_is_an_invoice_bonus(self, db, engine) -> None:
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 11, 10), moneda="ARS", tipo_cambio=None)
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje", "valor": "5"}

        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)
        [salida] = service.serializar(db, [tactical])[0]["lineas"]
        assert (salida["origen"], salida["alcance"], salida["pedido_compra_id"]) == ("sell_in_bono", "factura", pedido)
        assert salida["pedido_numero"] == f"OC-{pedido}"

    def test_an_invoice_total_is_a_purchase_over_its_invoiced_lines(self, db, engine) -> None:
        pedido = bw.pedido(engine, {2964: 10, 950: 5}, date(2026, 11, 10), moneda="ARS")  # USD costs: its rate
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "monto_total", "valor": "15000"}

        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)
        with engine.connect() as conn:
            items = conn.execute(
                text(
                    "SELECT i.item_id, i.cantidad FROM sell_in_compra_items i JOIN sell_in_compras c ON c.id = i.compra_id "
                    "WHERE c.tactical_id = :t AND c.tactical_linea = 1 ORDER BY i.item_id"
                ),
                {"t": tactical.id},
            ).all()
        assert [tuple(i) for i in items] == [(950, 5), (2964, 10)]
        [salida] = service.serializar(db, [tactical])[0]["lineas"]
        assert (salida["origen"], salida["valor"], salida["unidades_usadas"]) == (
            "sell_in_compra", Decimal("15000.00"), 0,
        )  # fmt: skip

    def test_an_invoice_total_in_usd_needs_a_fixed_rate(self, db, engine) -> None:
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 11, 10))
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "monto_total", "valor": "100"}

        with pytest.raises(service.TacticalError, match="tipo de cambio fijo"):
            service.crear(db, _tactical("sell_in", [linea], moneda="USD"), USUARIO)


class TestAnular:
    def test_it_voids_every_child_once(self, db, engine) -> None:
        tactical = service.crear(
            db,
            _tactical(lineas=[{"alcance": "productos", "item_ids": [2964, 2270], "modo_monto": "por_unidad",
                               "valor": "5", "tope_por_producto": True}]),
            USUARIO,
        )  # fmt: skip

        anulado = service.anular(db, tactical.id, USUARIO, "Se cayó el acuerdo")

        assert anulado.estado == "anulado"
        assert _contar(engine, "sell_out_campanas", "estado = 'anulada'") == 2
        assert _contar(engine, "auditoria", "tipo_accion = 'TACTICAL_ANULADO'") == 1
        with pytest.raises(service.TacticalYaAnulado):
            service.anular(db, tactical.id, USUARIO, None)
        assert service.anular(db, 999999, USUARIO, None) is None


class TestListar:
    def test_filters(self, db) -> None:
        vigente = service.crear(db, _tactical(nombre="Hot sale"), USUARIO)
        vencido = service.crear(
            db, _tactical(nombre="Octubre", fecha_desde=date(2026, 10, 1), fecha_hasta=date(2026, 10, 31)), USUARIO
        )
        anulado = service.crear(db, _tactical("sell_in", nombre="Cancelado"), USUARIO)
        service.anular(db, anulado.id, USUARIO, None)
        hoy = date(2026, 11, 5)

        def ids(**filtros) -> list[int]:
            filtros = service.Filtros(**{"tipos": ["sell_in", "sell_out"], **filtros})
            return [t.id for t in service.listar(db, filtros, 1, 50, hoy=hoy)[1]]

        assert ids() == [anulado.id, vigente.id, vencido.id]  # newest start first, then newest
        assert ids(estado="vigentes") == [vigente.id]
        assert ids(estado="vencidos") == [vencido.id]
        assert ids(estado="anulados") == [anulado.id]
        assert ids(tipos=["sell_out"]) == [vigente.id, vencido.id]
        assert ids(q="hot") == [vigente.id]
        assert ids(desde=date(2026, 10, 15), hasta=date(2026, 10, 20)) == [vencido.id]

    def test_an_invoice_tactical_stays_current_after_its_invoice_dates(self, db, engine) -> None:
        """S4: an all-invoice tactical has no end: it is vigente until voided, never vencido."""
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 3, 10))
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje", "valor": "5"}
        factura = service.crear(db, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None), USUARIO)
        vencido = service.crear(
            db, _tactical(nombre="Octubre", fecha_desde=date(2026, 10, 1), fecha_hasta=date(2026, 10, 31)), USUARIO
        )

        def ids(**filtros) -> list[int]:
            filtros = service.Filtros(**{"tipos": ["sell_in", "sell_out"], **filtros})
            return [t.id for t in service.listar(db, filtros, 1, 50, hoy=date(2026, 11, 5))[1]]

        assert ids(estado="vigentes") == [factura.id]
        assert ids(estado="vencidos") == [vencido.id]

    def test_the_currency_filter_keeps_the_tacticals_in_that_currency(self, db) -> None:
        pesos = service.crear(db, _tactical(nombre="En pesos"), USUARIO)
        dolares = service.crear(db, _tactical(nombre="En dólares", moneda="USD", tc_modo="al_cobro"), USUARIO)

        def ids(**filtros) -> list[int]:
            filtros = service.Filtros(**{"tipos": ["sell_in", "sell_out"], **filtros})
            return sorted(t.id for t in service.listar(db, filtros, 1, 50, hoy=date(2026, 11, 5))[1])

        assert ids(moneda="ARS") == [pesos.id]
        assert ids(moneda="USD") == [dolares.id]
        assert ids() == sorted([pesos.id, dolares.id])


def _leido(db: Session, tactical_id: int) -> dict:
    return service.serializar(db, [db.get(service.Tactical, tactical_id)])[0]


class TestMarcas:
    """S3 (owner 2026-11-10): "lo mismo las marcas que se usan para el filtro hay que hacer un selector multiple"."""

    def test_a_tactical_keeps_every_brand_and_its_first_one_as_marca(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(marca=None, marcas=[bw.MERCUSYS, TPLINK]), USUARIO)

        assert tactical.marca == bw.MERCUSYS  # old readers keep a valid brand
        leido = _leido(db, tactical.id)
        assert (leido["marca"], leido["marcas"]) == (bw.MERCUSYS, [bw.MERCUSYS, TPLINK])
        assert _contar(engine, "tactical_marcas", f"tactical_id = {tactical.id}") == 2

    def test_an_old_client_sending_only_marca_gets_that_one_brand(self, db) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        assert _leido(db, tactical.id)["marcas"] == [TPLINK]

    def test_marca_and_marcas_together_must_agree(self, db, engine) -> None:
        with pytest.raises(service.TacticalError, match="La marca tiene que ser una de las marcas"):
            service.crear(db, _tactical(marca=TPLINK, marcas=[bw.MERCUSYS]), USUARIO)
        assert _contar(engine, "tacticals") == 0

    def test_the_marca_a_client_sends_with_marcas_stays_the_header_s(self, db) -> None:
        tactical = service.crear(db, _tactical(marca=TPLINK, marcas=[bw.MERCUSYS, TPLINK]), USUARIO)

        leido = _leido(db, tactical.id)
        assert (leido["marca"], leido["marcas"]) == (TPLINK, [bw.MERCUSYS, TPLINK])

    def test_the_brand_filter_still_finds_a_header_without_brand_rows(self, db, engine) -> None:
        """A header written by the code before 20261110_tacticals_marcas during a deploy has no `tactical_marcas`."""
        tactical = service.crear(db, _tactical(), USUARIO)
        db.commit()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM tactical_marcas WHERE tactical_id = :t"), {"t": tactical.id})

        filtros = service.Filtros(tipos=["sell_in", "sell_out"], marca=TPLINK)
        assert [t.id for t in service.listar(db, filtros, 1, 50, hoy=date(2026, 11, 5))[1]] == [tactical.id]

    def test_every_brand_needs_products_and_a_repeated_one_counts_once(self, db, engine) -> None:
        with pytest.raises(service.TacticalError, match="No hay productos de la marca NO EXISTE"):
            service.crear(db, _tactical(marca=None, marcas=[TPLINK, "NO EXISTE"]), USUARIO)
        tactical = service.crear(db, _tactical(marca=None, marcas=[TPLINK, " TP-LINK ", bw.MERCUSYS]), USUARIO)
        assert _leido(db, tactical.id)["marcas"] == [TPLINK, bw.MERCUSYS]

    def test_no_brand_is_refused(self, db) -> None:
        with pytest.raises(service.TacticalError, match="La marca es obligatoria"):
            service.crear(db, _tactical(marca=None, marcas=[]), USUARIO)

    def test_the_brand_filter_matches_any_of_its_brands(self, db) -> None:
        dos = service.crear(db, _tactical(nombre="Dos", marca=None, marcas=[TPLINK, bw.MERCUSYS]), USUARIO)
        una = service.crear(db, _tactical(nombre="Una"), USUARIO)

        def ids(marca: str) -> list[int]:
            filtros = service.Filtros(tipos=["sell_in", "sell_out"], marca=marca)
            return sorted(t.id for t in service.listar(db, filtros, 1, 50, hoy=date(2026, 11, 5))[1])

        assert ids(bw.MERCUSYS) == [dos.id]
        assert ids(TPLINK) == sorted([dos.id, una.id])


class TestRefusalsFromGGA:
    def test_an_invoice_bonus_does_not_take_a_fixed_rate(self, db, engine) -> None:
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 11, 10))
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje", "valor": "5"}
        data = _tactical("sell_in", [linea], moneda="USD", tc_modo="fijo", tipo_cambio="1400")

        with pytest.raises(service.TacticalError, match="^Línea 1: .*tipo de cambio de la operación"):
            service.crear(db, data, USUARIO)

    def test_a_deadlock_while_voiding_is_busy_not_a_crash(self, db, engine, monkeypatch) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        class _Deadlock(Exception):
            pgcode = "40P01"

        def _bloquear(*_args, **_kwargs):
            raise DBAPIError("SELECT ... FOR UPDATE", {}, _Deadlock())

        monkeypatch.setattr(service.campanas, "bloquear", _bloquear)
        with pytest.raises(service.TacticalOcupado):
            service.anular(db, tactical.id, USUARIO, None)
        assert _contar(engine, "tacticals", "estado = 'activo'") == 1


class TestEditarCampanaDeUnTactical:
    def test_the_campaign_panel_s_edit_keeps_its_hidden_group(self, db, engine) -> None:
        """The panel lists no hidden group, so its PUT sends the campaign's groups without it."""
        service.crear(db, _tactical(), USUARIO)
        with engine.connect() as conn:
            cid, gid = conn.execute(text("SELECT campana_id, grupo_id FROM sell_out_campana_grupos")).one()
        edicion = SellOutCampanaIn(
            nombre="Renombrada", fecha_desde=date(2026, 11, 1), fecha_hasta=date(2026, 11, 30), tipo="por_unidad",
            monto_unit=Decimal("12"), moneda="ARS", grupo_ids=[],
        )  # fmt: skip

        service.campanas.editar_campana(db, cid, edicion, USUARIO)

        with engine.connect() as conn:
            assert conn.execute(text("SELECT grupo_id FROM sell_out_campana_grupos")).scalars().all() == [gid]
            assert conn.execute(text("SELECT monto_unit FROM sell_out_campanas")).scalar() == Decimal("12.00")

    def test_the_bulk_edit_keeps_its_hidden_group(self, db, engine) -> None:
        """The bulk edit rebuilds each campaign from its stored values, which no longer list the hidden group."""
        service.crear(db, _tactical(), USUARIO)
        with engine.connect() as conn:
            cid, gid = conn.execute(text("SELECT campana_id, grupo_id FROM sell_out_campana_grupos")).one()

        assert edicion_masiva.editar_campanas(db, [cid], {"fecha_hasta": date(2026, 11, 20)}, USUARIO) == ([cid], [])

        with engine.connect() as conn:
            assert conn.execute(text("SELECT grupo_id FROM sell_out_campana_grupos")).scalars().all() == [gid]
            assert conn.execute(text("SELECT fecha_hasta FROM sell_out_campanas")).scalar() == date(2026, 11, 20)

    def test_the_campaign_list_never_shows_a_hidden_group(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        campana = db.query(SellOutCampana).filter(SellOutCampana.tactical_id == tactical.id).one()

        [fila] = service.campanas.serializar(db, [campana])
        assert (fila["grupos"], fila["tactical_id"]) == ([], tactical.id)

    def test_a_renewal_draft_never_copies_a_hidden_group(self, db, engine) -> None:
        """Saving the draft is a plain create, which refuses a hidden group: the draft leaves it out."""
        tactical = service.crear(db, _tactical(), USUARIO)
        campana = db.query(SellOutCampana).filter(SellOutCampana.tactical_id == tactical.id).one()

        assert renovacion.borrador(db, campana.id).grupo_ids == []


class TestHiddenGroupsAreTheTacticalsOwn:
    def _oculto(self, db, engine) -> int:
        service.crear(db, _tactical(), USUARIO)
        with engine.connect() as conn:
            return conn.execute(text("SELECT grupo_id FROM sell_out_campana_grupos")).scalar()

    def _campana(self, grupo_ids: list[int]) -> SellOutCampanaIn:
        return SellOutCampanaIn(
            nombre="Ajena", fecha_desde=date(2026, 11, 1), fecha_hasta=date(2026, 11, 30), tipo="por_unidad",
            monto_unit=Decimal("3"), moneda="ARS", grupo_ids=grupo_ids,
        )  # fmt: skip

    def test_a_campaign_create_cannot_take_a_tactical_s_hidden_group(self, db, engine) -> None:
        gid = self._oculto(db, engine)

        with pytest.raises(service.campanas.SellOutError, match=f"^El grupo {gid} no existe$"):
            service.campanas.crear_campana(db, self._campana([gid]), USUARIO)
        assert _contar(engine, "sell_out_campanas") == 1

    def test_a_campaign_edit_cannot_take_another_tactical_s_hidden_group(self, db, engine) -> None:
        gid = self._oculto(db, engine)
        visible = OffsetGrupo(nombre="Visible", usuario_id=USUARIO)
        db.add(visible)
        db.commit()
        propia = service.campanas.crear_campana(db, self._campana([visible.id]), USUARIO)

        with pytest.raises(service.campanas.SellOutError, match=f"^El grupo {gid} no existe$"):
            service.campanas.editar_campana(db, propia.id, self._campana([visible.id, gid]), USUARIO)
        db.rollback()
        assert _contar(engine, "sell_out_campana_grupos", f"campana_id = {propia.id}") == 1


class TestChildrenCap:
    def test_a_create_past_the_children_cap_is_refused_before_storing(self, db, engine) -> None:
        linea = {"alcance": "productos", "modo_monto": "por_unidad", "valor": "5", "tope_por_producto": True}
        lineas = [{**linea, "item_ids": list(range(1, 301))}, {**linea, "item_ids": list(range(301, 601))}]

        with pytest.raises(service.TacticalError) as exc:
            service.crear(db, _tactical(lineas=lineas), USUARIO)
        assert str(exc.value) == (
            "Un tactical crea hasta 500 campañas o bonos y este crearía 600 (con tope por producto, cada producto "
            "es uno): partilo en varios tacticals"
        )
        assert _contar(engine, "tacticals") == 0


class TestSellOutMontoTotal:
    """A sell out `monto_total` line with its split criterion (tactical monto total S1/S2)."""

    def _linea(self, **values) -> dict:
        return {"alcance": "marca", "marca": TPLINK, "modo_monto": "monto_total", "valor": "900", **values}

    def _campana(self, db: Session) -> SellOutCampana:
        return db.query(SellOutCampana).one()

    def test_equal_parts_store_the_criterion_and_no_share(self, db, engine) -> None:
        [salida] = service.serializar(
            db, [service.crear(db, _tactical(lineas=[self._linea(reparto_criterio="iguales")]), USUARIO)]
        )

        campana = self._campana(db)
        assert (campana.tipo, campana.monto_total, campana.reparto_criterio) == (
            "monto_total",
            Decimal("900"),
            "iguales",
        )
        # Sell out equal parts go only to the products that sell (tactical iguales sell out S2): no fixed share.
        assert db.query(SellOutCampanaItem.item_id).all() == []
        assert [x["reparto_criterio"] for x in salida["lineas"]] == ["iguales"]
        assert _contar(engine, "sell_out_dirty") >= 1

    def test_by_units_stores_the_criterion_and_no_share(self, db) -> None:
        [salida] = service.serializar(
            db, [service.crear(db, _tactical(lineas=[self._linea(reparto_criterio="unidades")]), USUARIO)]
        )

        assert self._campana(db).reparto_criterio == "unidades"
        assert db.query(SellOutCampanaItem).count() == 0
        assert [x["reparto_criterio"] for x in salida["lineas"]] == ["unidades"]

    def test_a_monto_total_line_without_a_criterion_is_refused(self, db, engine) -> None:
        with pytest.raises(service.TacticalError, match="^Línea 1: elegí cómo repartir el monto total$"):
            service.crear(db, _tactical(lineas=[self._linea()]), USUARIO)
        assert _contar(engine, "sell_out_campanas") == 0

    def test_a_criterion_on_a_per_unit_line_is_refused(self, db) -> None:
        linea = {
            "alcance": "marca",
            "marca": TPLINK,
            "modo_monto": "por_unidad",
            "valor": "5",
            "reparto_criterio": "iguales",
        }
        with pytest.raises(service.TacticalError, match="^Línea 1: el reparto es solo para un monto total$"):
            service.crear(db, _tactical(lineas=[linea]), USUARIO)

    def test_a_monto_total_line_cannot_go_per_product(self, db) -> None:
        linea = self._linea(alcance="productos", marca=None, item_ids=[2964, 2270], reparto_criterio="iguales",
                            tope_por_producto=True)  # fmt: skip
        with pytest.raises(service.TacticalError, match="^Línea 1: un monto total se reparte entre los productos"):
            service.crear(db, _tactical(lineas=[linea]), USUARIO)

    def test_per_unit_and_percentage_lines_read_without_a_criterion(self, db) -> None:
        lineas = [
            {"alcance": "marca", "marca": TPLINK, "modo_monto": "por_unidad", "valor": "10"},
            {"alcance": "marca", "marca": TPLINK, "modo_monto": "porcentaje", "valor": "3"},
        ]
        [salida] = service.serializar(db, [service.crear(db, _tactical(lineas=lineas), USUARIO)])

        assert [(x["modo_monto"], x["reparto_criterio"]) for x in salida["lineas"]] == [
            ("por_unidad", None),
            ("porcentaje", None),
        ]

    @pytest.mark.parametrize("tope", [{"tope_unidades": 5}, {"tope_monto": "100"}])
    def test_a_monto_total_line_with_a_cap_is_refused(self, db, engine, tope: dict) -> None:
        linea = {"alcance": "marca", "marca": TPLINK, "modo_monto": "monto_total", "valor": "900",
                 "reparto_criterio": "iguales", **tope}  # fmt: skip
        with pytest.raises(
            service.TacticalError, match="^Línea 1: un monto total no lleva topes: el total es su tope$"
        ):
            service.crear(db, _tactical(lineas=[linea]), USUARIO)
        assert _contar(engine, "sell_out_campanas") == 0


class TestSellInMontoTotal:
    """A sell in `monto_total` line over products, a brand or a category (tactical monto total S4): one cost bonus
    split by the line's criterion; an invoice line's total stays a sell-in purchase."""

    def _linea(self, **values) -> dict:
        return {"alcance": "marca", "marca": TPLINK, "modo_monto": "monto_total", "valor": "1200",
                "reparto_criterio": "iguales", **values}  # fmt: skip

    def _bono(self, engine: Engine, tactical_id: int) -> tuple:
        with engine.connect() as conn:
            return tuple(
                conn.execute(
                    text(
                        "SELECT base, alcance, tipo, moneda, monto_total, reparto_criterio, monto_unit, porcentaje, "
                        "tope_unidades, tope_monto FROM sell_in_bonos_marca WHERE tactical_id = :t AND tactical_linea = 1"
                    ),
                    {"t": tactical_id},
                ).one()
            )

    def _repartos(self, engine: Engine) -> list:
        with engine.connect() as conn:
            return [tuple(r) for r in conn.execute(text("SELECT item_id, monto FROM sell_in_bono_repartos ORDER BY 1"))]

    def test_a_brand_line_is_one_cost_bonus_split_in_equal_parts(self, db, engine) -> None:
        tactical = service.crear(db, _tactical("sell_in", [self._linea()]), USUARIO)

        assert self._bono(engine, tactical.id) == (
            "costo_venta", "marca", "monto_total", "ARS", Decimal("1200.00"), "iguales", None, None, None, None,
        )  # fmt: skip
        assert self._repartos(engine) == [(2270, Decimal("600.00")), (2964, Decimal("600.00"))]
        [salida] = service.serializar(db, [tactical])[0]["lineas"]
        assert (salida["origen"], salida["modo_monto"], salida["valor"], salida["reparto_criterio"]) == (
            "sell_in_bono", "monto_total", Decimal("1200.00"), "iguales",
        )  # fmt: skip

    def test_a_products_line_by_units_stores_its_models_and_no_share(self, db, engine) -> None:
        linea = self._linea(alcance="productos", marca=None, item_ids=[2964, 950], reparto_criterio="unidades")

        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)

        assert self._bono(engine, tactical.id)[1:6] == (
            "modelos", "monto_total", "ARS", Decimal("1200.00"), "unidades",
        )  # fmt: skip
        assert self._repartos(engine) == []
        [salida] = service.serializar(db, [tactical])[0]["lineas"]
        assert [p["item_id"] for p in salida["productos"]] == [950, 2964]

    def test_a_category_line_by_cost_splits_by_each_product_s_cost(self, db, engine) -> None:
        bw.tipo_cambio(engine, date(2026, 10, 1), 1000)
        tactical = service.crear(
            db, _tactical("sell_in", [self._linea(alcance="categoria", marca=None, categoria="Routers",
                                                  reparto_criterio="costo", valor="10000")]), USUARIO
        )  # fmt: skip

        assert self._bono(engine, tactical.id)[1] == "categoria"
        # ARS costs: 2964 41.50 USD x 1000 = 41500, 2270 12000, 950 9.90 USD x 1000 = 9900; total weight 63400.
        assert self._repartos(engine) == [
            (950, Decimal("1561.51")), (2270, Decimal("1892.74")), (2964, Decimal("6545.75")),
        ]  # fmt: skip
        assert sum(m for _, m in self._repartos(engine)) == Decimal("10000.00")

    def test_without_a_criterion_it_is_refused(self, db, engine) -> None:
        with pytest.raises(service.TacticalError, match="^Línea 1: elegí cómo repartir el monto total$"):
            service.crear(db, _tactical("sell_in", [self._linea(reparto_criterio=None)]), USUARIO)
        assert _contar(engine, "tacticals") == 0

    @pytest.mark.parametrize("tope", [{"tope_unidades": 5}, {"tope_monto": "100"}])
    def test_with_a_cap_it_is_refused(self, db, engine, tope: dict) -> None:
        with pytest.raises(
            service.TacticalError, match="^Línea 1: un monto total no lleva topes: el total es su tope$"
        ):
            service.crear(db, _tactical("sell_in", [self._linea(**tope)]), USUARIO)
        assert _contar(engine, "sell_in_bonos_marca") == 0

    def test_per_product_it_is_refused(self, db) -> None:
        linea = self._linea(alcance="productos", marca=None, item_ids=[2964, 2270], tope_por_producto=True)
        with pytest.raises(service.TacticalError, match="^Línea 1: un monto total se reparte entre los productos"):
            service.crear(db, _tactical("sell_in", [linea]), USUARIO)

    def test_in_usd_with_a_fixed_rate_it_is_split_in_pesos_to_the_cent(self, db, engine) -> None:
        data = _tactical("sell_in", [self._linea(valor="1200.01")], moneda="USD", tc_modo="fijo", tipo_cambio="1000.5")

        tactical = service.crear(db, data, USUARIO)

        # USD 1200.01 x 1000.5 = 1200610.005 -> ARS 1200610.01, split in two equal parts.
        assert self._bono(engine, tactical.id)[2:6] == ("monto_total", "ARS", Decimal("1200610.01"), "iguales")
        repartos = self._repartos(engine)
        assert sorted(m for _, m in repartos) == [Decimal("600305.00"), Decimal("600305.01")]
        assert sum(m for _, m in repartos) == Decimal("1200610.01")
        salida = service.serializar(db, [tactical])[0]
        [linea] = salida["lineas"]
        assert (linea["valor"], linea["moneda"], linea["valor_usd"]) == (
            Decimal("1200610.01"),
            "ARS",
            Decimal("1200.01"),
        )
        assert (salida["moneda"], salida["tipo_cambio"]) == ("USD", Decimal("1000.5"))

    def test_in_usd_without_a_fixed_rate_it_is_refused(self, db, engine) -> None:
        data = _tactical("sell_in", [self._linea()], moneda="USD", tc_modo="al_cobro")
        with pytest.raises(
            service.TacticalError, match="^Línea 1: un monto total en USD necesita tipo de cambio fijo$"
        ):
            service.crear(db, data, USUARIO)
        assert _contar(engine, "tacticals") == 0

    def test_in_pesos_it_carries_no_usd_amount(self, db) -> None:
        tactical = service.crear(db, _tactical("sell_in", [self._linea()]), USUARIO)
        [linea] = service.serializar(db, [tactical])[0]["lineas"]
        assert linea["valor_usd"] is None

    def test_a_negative_total_is_refused(self, db) -> None:
        with pytest.raises(service.TacticalError, match="^Línea 1: el monto tiene que ser mayor a 0$"):
            service.crear(db, _tactical("sell_in", [self._linea(valor="-1200")]), USUARIO)

    def test_an_invoice_total_takes_no_criterion_and_stays_a_purchase(self, db, engine) -> None:
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 11, 10), moneda="ARS")
        factura = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "monto_total", "valor": "15000"}

        with pytest.raises(
            service.TacticalError,
            match="^Línea 1: una línea por factura reparte su monto total sobre lo facturado: no lleva criterio de "
            "reparto$",
        ):
            service.crear(db, _tactical("sell_in", [{**factura, "reparto_criterio": "iguales"}]), USUARIO)

        tactical = service.crear(db, _tactical("sell_in", [factura]), USUARIO)
        [salida] = service.serializar(db, [tactical])[0]["lineas"]
        assert (salida["origen"], salida["valor"], salida["reparto_criterio"]) == (
            "sell_in_compra", Decimal("15000.00"), None,
        )  # fmt: skip
        assert _contar(engine, "sell_in_bonos_marca") == 0

    def test_per_unit_and_percentage_sell_in_lines_are_unchanged(self, db, engine) -> None:
        lineas = [
            {"alcance": "marca", "marca": TPLINK, "modo_monto": "por_unidad", "valor": "36"},
            {"alcance": "marca", "marca": TPLINK, "modo_monto": "porcentaje", "valor": "3"},
        ]
        tactical = service.crear(db, _tactical("sell_in", lineas), USUARIO)

        [salida] = service.serializar(db, [tactical])
        assert [(x["modo_monto"], x["valor"], x["reparto_criterio"]) for x in salida["lineas"]] == [
            ("por_unidad", Decimal("36.00"), None),
            ("porcentaje", Decimal("3.0000"), None),
        ]
        assert _contar(engine, "sell_in_bonos_marca", "monto_total IS NULL AND reparto_criterio IS NULL") == 2
        assert self._repartos(engine) == []

    def test_editing_a_total_line_s_end_date_keeps_its_split(self, db, engine) -> None:
        tactical = service.crear(db, _tactical("sell_in", [self._linea()]), USUARIO)

        service.editar(db, tactical.id, service.TacticalEditarIn(fecha_hasta=date(2026, 12, 15)), USUARIO,
                       hoy=date(2026, 11, 6))  # fmt: skip

        assert self._bono(engine, tactical.id)[4:6] == (Decimal("1200.00"), "iguales")
        assert self._repartos(engine) == [(2270, Decimal("600.00")), (2964, Decimal("600.00"))]


class TestStoreScope:
    def test_scoped_create_persists_targets_and_shared_cap(self, db, engine) -> None:
        db.add(MlTiendaOficial(store_id=57997, nombre="GaussOnline", clave="gauss", orden=1, activa=True))
        db.add(MlTiendaOficial(store_id=2645, nombre="TP-Link", clave="tplink", orden=2, activa=True))
        db.flush()

        tactical = service.crear(
            db,
            _tactical(
                todas_tiendas=False,
                tope_compartido=True,
                tiendas=[
                    {"tipo": "oficial", "store_id": 57997},
                    {"tipo": "oficial", "store_id": 2645},
                    {"tipo": "tienda_nube"},
                ],
            ),
            USUARIO,
        )

        [salida] = service.serializar(db, [tactical])
        assert (salida["todas_tiendas"], salida["tope_compartido"]) == (False, True)
        assert salida["tiendas"] == [
            {"tipo": "oficial", "store_id": 57997},
            {"tipo": "oficial", "store_id": 2645},
            {"tipo": "tienda_nube", "store_id": None},
        ]
        assert _contar(engine, "tactical_tiendas") == 3

    def test_create_keeps_todays_reach(self, db, engine) -> None:
        """Before the store picker exists, a new tactical reaches what one reached before the scope did: every
        official store, outside sales and Tienda Nube, with one shared cap (the migration's backfill)."""
        tactical = service.crear(db, _tactical(), USUARIO)

        assert (tactical.todas_tiendas, tactical.tope_compartido) == (True, True)
        assert sorted(_filas(engine, tactical.id)) == [("fuera", None), ("tienda_nube", None)]


def _filas(engine: Engine, tactical_id: int) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(
            text("SELECT tipo, store_id FROM tactical_tiendas WHERE tactical_id = :t"), {"t": tactical_id}
        )]  # fmt: skip


class TestMarcaYCategoria:
    """SISO S3 (owner): "Que se puedan combinar marca y categoría porque hoy no se puede, si quiero aplicar a los
    routers solo de tp-link no puedo." A brand line may carry a category (L7 D1): it reaches only the brand's
    products of that category, in sell out and in sell in."""

    @pytest.fixture(autouse=True)
    def _switch(self, engine: Engine) -> None:
        with engine.begin() as conn:  # 2964 TP-LINK Routers, 2270 TP-LINK Switches, 950 MERCUSYS Routers
            conn.execute(text("UPDATE productos_erp SET categoria = 'Switches' WHERE item_id = 2270"))

    def _linea(self, **values) -> dict:
        return {"alcance": "marca", "marca": TPLINK, "categoria": "Routers", "modo_monto": "por_unidad",
                "valor": "10", **values}  # fmt: skip

    def test_a_sell_out_line_reaches_only_the_brand_s_products_of_the_category(self, db) -> None:
        from app.services.sell_out import alcance

        tactical = service.crear(db, _tactical(lineas=[self._linea()]), USUARIO)

        campana = db.query(SellOutCampana).one()
        assert set(alcance.productos(db, [campana.id])[campana.id]) == {2964}
        [salida] = service.serializar(db, [tactical])[0]["lineas"]
        assert (salida["alcance"], salida["marca"], salida["categoria"]) == ("marca", TPLINK, "Routers")

    def test_a_sell_in_total_line_splits_only_among_the_brand_s_products_of_the_category(self, db, engine) -> None:
        linea = self._linea(modo_monto="monto_total", valor="1200", reparto_criterio="iguales")

        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)

        with engine.connect() as conn:
            bono = conn.execute(
                text("SELECT alcance, marca, categoria FROM sell_in_bonos_marca WHERE tactical_id = :t"),
                {"t": tactical.id},
            ).one()
            repartos = [tuple(r) for r in conn.execute(text("SELECT item_id, monto FROM sell_in_bono_repartos"))]
        assert tuple(bono) == ("marca", TPLINK, "Routers")
        assert repartos == [(2964, Decimal("1200.00"))]
        [salida] = service.serializar(db, [tactical])[0]["lineas"]
        assert (salida["alcance"], salida["marca"], salida["categoria"]) == ("marca", TPLINK, "Routers")

    def test_a_brand_without_products_in_the_category_is_refused(self, db, engine) -> None:
        with pytest.raises(
            service.TacticalError, match="^Línea 1: no hay productos de la marca TP-LINK en la categoría Notebooks$"
        ):
            service.crear(db, _tactical(lineas=[self._linea(categoria="Notebooks")]), USUARIO)
        assert _contar(engine, "tacticals") == 0

    def test_a_category_line_still_takes_no_brand(self, db) -> None:
        with pytest.raises(service.TacticalError, match="^Línea 1: una línea por categoria no lleva marca$"):
            service.crear(db, _tactical(lineas=[self._linea(alcance="categoria")]), USUARIO)


def _vincular_al_commitear(db: Session, engine: Engine, pedido: int, fecha: date, lineas: dict) -> None:
    """Compras links the operation's invoice from another session while the save's transaction is still open: right
    before it commits, after it read the operation without its invoice (the window the triggers cannot see)."""
    from sqlalchemy import event

    def _vincular(_session: Session) -> None:
        with engine.begin() as conn:
            conn.execute(text("UPDATE pedidos_compra SET fecha_factura = :f WHERE id = :p"), {"f": fecha, "p": pedido})
            for item_id, cantidad in sorted(lineas.items()):
                conn.execute(
                    text(
                        "INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id, cantidad) VALUES (:p, :i, :q)"
                    ),
                    {"p": pedido, "i": item_id, "q": cantidad},
                )

    event.listen(db, "before_commit", _vincular, once=True)


def _vincular_tras_leer(monkeypatch, engine: Engine, pedido: int, fecha: date, lineas: dict) -> None:
    """Compras links the invoice from another session after the save read the operation without it (its lines are
    validated and stored, the audit row written) and before the save collects what to queue after its commit."""
    original = service._audit
    hecho: list[bool] = []

    def _audit(*args, **kwargs):
        original(*args, **kwargs)
        if hecho:
            return
        hecho.append(True)
        with engine.begin() as conn:
            conn.execute(text("UPDATE pedidos_compra SET fecha_factura = :f WHERE id = :p"), {"f": fecha, "p": pedido})
            for item_id, cantidad in sorted(lineas.items()):
                conn.execute(
                    text(
                        "INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id, cantidad) VALUES (:p, :i, :q)"
                    ),
                    {"p": pedido, "i": item_id, "q": cantidad},
                )

    monkeypatch.setattr(service, "_audit", _audit)


def _una_corrida_del_worker(monkeypatch, engine: Engine) -> None:
    from datetime import datetime, timedelta, timezone

    from app.workers.context import WorkerContext
    from app.workers.handlers.sell_in_bono import bono as handler

    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
    hasta = datetime.now(timezone.utc) + timedelta(seconds=30)
    assert handler.run(WorkerContext(deadline=hasta, worker_name="t")).success


class TestFacturaPendiente:
    """Sell in factura pendiente S2-S6: an invoice line is saved before its operation has the supplier invoice, applies
    nothing while it waits, and once Compras links the invoice it applies exactly as if it was loaded with it."""

    def _bono(self, engine: Engine, tactical_id: int) -> tuple:
        with engine.connect() as conn:
            return tuple(
                conn.execute(
                    text("SELECT id, fecha_desde, fecha_hasta FROM sell_in_bonos_marca WHERE tactical_id = :t"),
                    {"t": tactical_id},
                ).one()
            )

    def _cabecera(self, engine: Engine, tactical_id: int) -> tuple:
        with engine.connect() as conn:
            return tuple(
                conn.execute(text("SELECT fecha_desde, fecha_hasta FROM tacticals WHERE id = :t"), {"t": tactical_id})
                .one()
            )  # fmt: skip

    def _crear(self, db: Session, pedido: int, modo: str = "por_unidad", valor: str = "2", **cabecera):
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": modo, "valor": valor}
        return service.crear(db, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None, **cabecera), USUARIO)

    def test_an_invoice_linked_while_the_save_commits_still_applies(self, db, engine, monkeypatch) -> None:
        """Orchestrator (factura pendiente total, window c): Compras links the invoice between the save's read and its
        commit; the save re-reads the operation after committing and queues it, so one worker run applies it."""
        factura = date(2026, 10, 10)
        pendiente = bw.pedido(engine, {}, None)
        bw.clear_queue(engine)
        _vincular_al_commitear(db, engine, pendiente, factura, {2964: 10, 950: 5})

        tactical = self._crear(db, pendiente, nombre="Carrera")

        assert ("pedido", pendiente) in bw.queued(engine)
        _una_corrida_del_worker(monkeypatch, engine)
        bono, *rango = self._bono(engine, tactical.id)
        assert rango == [factura, factura]
        assert bw.items_de(engine, bono, pendiente) != []
        db.expire_all()
        [salida] = service.serializar(db, [tactical])[0]["lineas"]
        assert salida["esperando_factura"] is False

    def test_an_invoice_linked_before_the_save_collects_its_queue_still_applies(self, db, engine, monkeypatch) -> None:
        """Verifier #2234: the invoice arrives after the line was read without it but before the save collects the
        operations to queue after its commit; it is queued anyway and one worker run applies it."""
        factura = date(2026, 10, 10)
        pendiente = bw.pedido(engine, {}, None)
        bw.clear_queue(engine)
        _vincular_tras_leer(monkeypatch, engine, pendiente, factura, {2964: 10, 950: 5})

        tactical = self._crear(db, pendiente, nombre="Carrera")

        assert ("pedido", pendiente) in bw.queued(engine)
        _una_corrida_del_worker(monkeypatch, engine)
        bono, *rango = self._bono(engine, tactical.id)
        assert rango == [factura, factura]
        assert bw.items_de(engine, bono, pendiente) != []

    def test_an_invoice_line_is_saved_without_the_invoice_and_waits_for_it(self, db, engine) -> None:
        pendiente = bw.pedido(engine, {}, None)

        tactical = self._crear(db, pendiente)

        [salida] = service.serializar(db, [tactical])[0]["lineas"]
        assert (salida["alcance"], salida["pedido_compra_id"], salida["esperando_factura"]) == (
            "factura",
            pendiente,
            True,
        )
        assert service.serializar(db, [tactical])[0]["por_factura"] is True

    def test_nothing_applies_while_the_invoice_is_missing(self, db, engine) -> None:
        pendiente = bw.pedido(engine, {}, None)
        self._crear(db, pendiente)

        bonos.reconciliar(db, pedido_ids=[pendiente])
        db.commit()

        assert bw.generadas(engine) == []

    def test_linking_the_invoice_applies_it_exactly_as_if_it_was_loaded_with_it(self, db, engine) -> None:
        factura = date(2026, 10, 10)
        con = bw.pedido(engine, {2964: 10, 950: 5}, factura)
        cargado = self._crear(db, con, nombre="Con factura")
        pendiente = bw.pedido(engine, {}, None)
        esperando = self._crear(db, pendiente, nombre="Sin factura")

        bw.update_pedido(engine, pendiente, fecha_factura=factura)
        bw.set_lineas(engine, pendiente, {2964: 10, 950: 5})
        bonos.reconciliar(db, pedido_ids=[con, pendiente])
        db.commit()

        bono_con, *rango_con = self._bono(engine, cargado.id)
        bono_esp, *rango_esp = self._bono(engine, esperando.id)
        assert rango_esp == rango_con == [factura, factura]
        assert self._cabecera(engine, esperando.id) == self._cabecera(engine, cargado.id) == (factura, factura)
        assert bw.items_de(engine, bono_esp, pendiente) == bw.items_de(engine, bono_con, con) != []
        generadas = {g[0]: g[2:] for g in bw.generadas(engine)}
        assert generadas[bono_esp] == generadas[bono_con]
        [salida] = service.serializar(db, [esperando])[0]["lineas"]
        assert salida["esperando_factura"] is False

    def test_a_corrected_invoice_date_still_moves_the_dates_after_it_arrived(self, db, engine) -> None:
        pendiente = bw.pedido(engine, {}, None)
        esperando = self._crear(db, pendiente)
        bw.update_pedido(engine, pendiente, fecha_factura=date(2026, 10, 10))
        bw.set_lineas(engine, pendiente, {2964: 10})
        bonos.reconciliar(db, pedido_ids=[pendiente])
        db.commit()

        bw.update_pedido(engine, pendiente, fecha_factura=date(2026, 12, 5))
        bonos.reconciliar(db, pedido_ids=[pendiente])
        db.commit()

        bono_id, *rango = self._bono(engine, esperando.id)
        assert rango == [date(2026, 12, 5), date(2026, 12, 5)]
        assert [(g[2], g[6]) for g in bw.generadas(engine)] == [("activa", date(2026, 12, 5))]

    def test_end_to_end_the_queue_worker_applies_a_linked_invoice_like_one_loaded_with_it(
        self, db, engine, monkeypatch
    ) -> None:
        """Verifier ask on #2229: pending line saved -> Compras links the invoice (header date and invoiced lines in
        one transaction, like `erp_matching_service`) -> the live triggers queue it -> one `sell_in.bono` run ->
        the persisted rows equal those of a tactical loaded with the invoice."""
        from datetime import datetime, timedelta, timezone

        from app.workers.context import WorkerContext
        from app.workers.handlers.sell_in_bono import bono as handler

        monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))

        def _worker() -> None:
            hasta = datetime.now(timezone.utc) + timedelta(seconds=30)
            assert handler.run(WorkerContext(deadline=hasta, worker_name="t")).success

        factura = date(2026, 10, 10)
        pendiente = bw.pedido(engine, {}, None)
        esperando = self._crear(db, pendiente, nombre="Sin factura")
        _worker()
        assert bw.generadas(engine) == []  # nothing while the invoice is missing
        bw.clear_queue(engine)

        # Compras links the invoice; no other bonus covers its date, so only the new gate can queue it.
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE pedidos_compra SET fecha_factura = :f WHERE id = :p"), {"f": factura, "p": pendiente}
            )
            for item_id, cantidad in ((950, 5), (2964, 10)):
                conn.execute(
                    text(
                        "INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id, cantidad) VALUES (:p, :i, :q)"
                    ),
                    {"p": pendiente, "i": item_id, "q": cantidad},
                )
        assert ("pedido", pendiente) in bw.queued(engine)
        _worker()

        # The same invoice loaded with a tactical that already has it.
        con = bw.pedido(engine, {2964: 10, 950: 5}, factura)
        cargado = self._crear(db, con, nombre="Con factura")
        _worker()

        bono_con, *rango_con = self._bono(engine, cargado.id)
        bono_esp, *rango_esp = self._bono(engine, esperando.id)
        assert rango_esp == rango_con == [factura, factura]
        assert self._cabecera(engine, esperando.id) == self._cabecera(engine, cargado.id) == (factura, factura)
        assert bw.items_de(engine, bono_esp, pendiente) == bw.items_de(engine, bono_con, con) != []
        generadas = {g[0]: g[2:] for g in bw.generadas(engine)}
        assert generadas[bono_esp] == generadas[bono_con]
        db.expire_all()
        [salida] = service.serializar(db, [esperando])[0]["lineas"]
        assert salida["esperando_factura"] is False


class TestFacturaPendienteTotal:
    """Sell in factura pendiente, monto total (orchestrator: "pending table, worker applies with the SAME
    _total_de_factura, exact parity; existing totals untouched"): a total line is saved before its operation's invoice,
    applies nothing while it waits, and once Compras links the invoice the queue worker creates the same purchase a
    tactical loaded with the invoice has."""

    @pytest.fixture(autouse=True)
    def _worker_db(self, engine, monkeypatch) -> None:
        monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))

    def _worker(self) -> None:
        from datetime import datetime, timedelta, timezone

        from app.workers.context import WorkerContext
        from app.workers.handlers.sell_in_bono import bono as handler

        hasta = datetime.now(timezone.utc) + timedelta(seconds=30)
        assert handler.run(WorkerContext(deadline=hasta, worker_name="t")).success

    def _crear(self, db: Session, pedido: int, valor: str = "15000", **cabecera):
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "monto_total", "valor": valor}
        return service.crear(db, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None, **cabecera), USUARIO)

    def _vincular(self, engine: Engine, pedido: int, fecha: date, lineas: dict) -> None:
        """What Compras does when it links the supplier invoice: the header's date and the invoiced lines, one tx."""
        with engine.begin() as conn:
            conn.execute(text("UPDATE pedidos_compra SET fecha_factura = :f WHERE id = :p"), {"f": fecha, "p": pedido})
            for item_id, cantidad in sorted(lineas.items()):
                conn.execute(
                    text(
                        "INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id, cantidad) VALUES (:p, :i, :q)"
                    ),
                    {"p": pedido, "i": item_id, "q": cantidad},
                )

    def _compras(self, engine: Engine, tactical_id: int) -> list[tuple]:
        """What a tactical's invoice totals persisted, without ids: header and items of each purchase."""
        with engine.connect() as conn:
            filas = conn.execute(
                text(
                    "SELECT c.id, c.estado, c.moneda, c.tipo, c.monto_total, c.tipo_cambio, c.formula, c.fecha_compra, "
                    "c.descripcion, c.tactical_linea, p.pedido_compra_id FROM sell_in_compras c "
                    "JOIN sell_in_compra_pedidos p ON p.compra_id = c.id WHERE c.tactical_id = :t ORDER BY c.id"
                ),
                {"t": tactical_id},
            ).all()
            salida = []
            for fila in filas:
                items = conn.execute(
                    text(
                        "SELECT item_id, cantidad, monto_asignado FROM sell_in_compra_items WHERE compra_id = :c "
                        "ORDER BY item_id"
                    ),
                    {"c": fila[0]},
                ).all()
                salida.append((tuple(fila[1:]), [tuple(i) for i in items]))
            return salida

    def _pendientes(self, engine: Engine, tactical_id: int) -> list[tuple]:
        with engine.connect() as conn:
            return [
                tuple(r)
                for r in conn.execute(
                    text(
                        "SELECT tactical_linea, pedido_id, estado FROM tactical_facturas_pendientes "
                        "WHERE tactical_id = :t ORDER BY id"
                    ),
                    {"t": tactical_id},
                )
            ]

    def test_an_invoice_linked_while_the_save_commits_still_applies(self, db, engine, monkeypatch) -> None:
        """Orchestrator (window c): Compras links the invoice between the save's read and its commit; the save
        re-reads the operation after committing and queues it, so one worker run applies the total."""
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        bw.clear_queue(engine)
        _vincular_al_commitear(db, engine, pendiente, date(2026, 10, 10), {2964: 10, 950: 5})

        tactical = self._crear(db, pendiente)

        assert ("pedido", pendiente) in bw.queued(engine)
        _una_corrida_del_worker(monkeypatch, engine)
        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "aplicada")]
        assert len(self._compras(engine, tactical.id)) == 1

    def test_an_invoice_linked_before_the_save_collects_its_queue_still_applies(self, db, engine, monkeypatch) -> None:
        """Verifier #2234, monto total: linked after the line was read without its invoice, before the save collects
        what to queue; queued anyway, applied after one worker run."""
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        bw.clear_queue(engine)
        _vincular_tras_leer(monkeypatch, engine, pendiente, date(2026, 10, 10), {2964: 10, 950: 5})

        tactical = self._crear(db, pendiente)

        assert ("pedido", pendiente) in bw.queued(engine)
        _una_corrida_del_worker(monkeypatch, engine)
        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "aplicada")]
        assert len(self._compras(engine, tactical.id)) == 1

    def test_an_operation_still_without_its_invoice_is_not_queued_by_the_save(self, db, engine) -> None:
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        bw.clear_queue(engine)

        self._crear(db, pendiente)

        assert ("pedido", pendiente) not in bw.queued(engine)

    def test_a_total_line_is_saved_without_the_invoice_and_waits_for_it(self, db, engine) -> None:
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")

        tactical = self._crear(db, pendiente)

        assert self._compras(engine, tactical.id) == []
        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "pendiente")]
        leido = service.serializar(db, [tactical])[0]
        [salida] = leido["lineas"]
        assert (salida["origen"], salida["estado"], salida["alcance"], salida["modo_monto"]) == (
            "sell_in_factura_pendiente",
            "activa",
            "factura",
            "monto_total",
        )
        assert (salida["pedido_compra_id"], salida["pedido_numero"], salida["valor"]) == (
            pendiente,
            f"OC-{pendiente}",
            Decimal("15000"),
        )
        assert (salida["esperando_factura"], leido["esperando_factura"], leido["por_factura"]) == (True, True, True)

    def test_nothing_applies_while_the_invoice_is_missing(self, db, engine) -> None:
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        tactical = self._crear(db, pendiente)

        bw.update_pedido(engine, pendiente, estado="aprobado")
        self._worker()

        assert self._compras(engine, tactical.id) == []
        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "pendiente")]

    def test_linking_the_invoice_applies_it_exactly_as_if_it_was_loaded_with_it(self, db, engine) -> None:
        factura = date(2026, 10, 10)
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        esperando = self._crear(db, pendiente, nombre="Rebate")
        bw.clear_queue(engine)

        self._vincular(engine, pendiente, factura, {2964: 10, 950: 5})
        assert ("pedido", pendiente) in bw.queued(engine)  # no bonus covers it: only the pending row gates it in
        self._worker()

        con = bw.pedido(engine, {2964: 10, 950: 5}, factura, moneda="ARS")
        cargado = self._crear(db, con, nombre="Rebate")

        [(cabecera_esp, items_esp)] = self._compras(engine, esperando.id)
        [(cabecera_con, items_con)] = self._compras(engine, cargado.id)
        assert cabecera_esp[:-1] == cabecera_con[:-1]  # all but the operation
        assert (cabecera_esp[-1], cabecera_con[-1]) == (pendiente, con)
        assert items_esp == items_con != []
        assert self._pendientes(engine, esperando.id) == [(1, pendiente, "aplicada")]
        with engine.connect() as conn:
            cabeceras = dict(
                (t, (d, h)) for t, d, h in conn.execute(text("SELECT id, fecha_desde, fecha_hasta FROM tacticals"))
            )
        assert cabeceras[esperando.id] == cabeceras[cargado.id] == (factura, factura)
        db.expire_all()
        leido = service.serializar(db, [esperando])[0]
        [salida] = leido["lineas"]
        assert (salida["origen"], salida["esperando_factura"], leido["esperando_factura"]) == (
            "sell_in_compra",
            False,
            False,
        )

    def test_invoiced_lines_arriving_after_the_date_still_apply_it(self, db, engine) -> None:
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        tactical = self._crear(db, pendiente)
        self._vincular(engine, pendiente, date(2026, 10, 10), {})
        self._worker()
        assert self._compras(engine, tactical.id) == []  # a date without invoiced lines: still waiting

        bw.set_lineas(engine, pendiente, {2964: 10})
        self._worker()

        assert [c[0][0] for c in self._compras(engine, tactical.id)] == ["activa"]
        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "aplicada")]

    def test_a_voided_tactical_never_applies_its_pending_total(self, db, engine) -> None:
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        tactical = self._crear(db, pendiente)

        anulado = service.anular(db, tactical.id, USUARIO, "Se cayó el acuerdo")
        [salida] = service.serializar(db, [anulado])[0]["lineas"]
        assert (salida["origen"], salida["estado"]) == ("sell_in_factura_pendiente", "anulada")
        self._vincular(engine, pendiente, date(2026, 10, 10), {2964: 10})
        self._worker()

        assert self._compras(engine, tactical.id) == []
        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "anulada")]

    def test_one_failing_pending_total_does_not_block_the_others(self, db, engine, monkeypatch) -> None:
        """A pending total whose purchase cannot be built charges its own operation and keeps waiting; the other
        operation claimed with it still applies (the handler retries a failed batch key by key)."""
        factura = date(2026, 10, 10)
        falla, sana = bw.pedido(engine, {}, None, moneda="ARS"), bw.pedido(engine, {}, None, moneda="ARS")
        t_falla, t_sana = self._crear(db, falla, nombre="Falla"), self._crear(db, sana, nombre="Sana")
        bw.clear_queue(engine)
        original = service._compra_de_factura

        def _compra(db_, clave, pedido, *args):
            if pedido.id == falla:
                raise service.compras.SellInError("La compra no se pudo armar")
            return original(db_, clave, pedido, *args)

        monkeypatch.setattr(service, "_compra_de_factura", _compra)
        self._vincular(engine, falla, factura, {2964: 10})
        self._vincular(engine, sana, factura, {950: 5})
        self._worker()

        assert self._pendientes(engine, t_falla.id) == [(1, falla, "pendiente")]
        assert self._pendientes(engine, t_sana.id) == [(1, sana, "aplicada")]
        assert len(self._compras(engine, t_sana.id)) == 1
        [(tipo, ref, intentos, error)] = [r for r in bw.queue_rows(engine) if r[:2] == ("pedido", falla)]
        assert intentos == 1 and "La compra no se pudo armar" in error
        assert ("pedido", sana) not in bw.queued(engine)

    def test_voiding_after_the_invoice_applied_voids_its_purchase(self, db, engine) -> None:
        """A total the worker already applied is voided as the purchase it became, and its row stays `aplicada`."""
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        tactical = self._crear(db, pendiente)
        self._vincular(engine, pendiente, date(2026, 10, 10), {2964: 10})
        self._worker()

        db.expire_all()
        service.anular(db, tactical.id, USUARIO, "Se cayó el acuerdo")

        [(cabecera, _)] = self._compras(engine, tactical.id)
        assert cabecera[0] == "anulada"
        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "aplicada")]

    def test_voiding_while_the_worker_applies_waits_and_voids_the_new_purchase(self, db, engine) -> None:
        """The worker holds the tactical (FK) and the waiting row while it builds the purchase; anular waits for it and
        then voids that purchase, instead of missing it and leaving a voided tactical with an active purchase."""
        import threading

        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        tactical = self._crear(db, pendiente)
        self._vincular(engine, pendiente, date(2026, 10, 10), {2964: 10})
        worker = sessionmaker(bind=engine)()
        assert service.aplicar_facturas_pendientes(worker, [pendiente]) == 1  # row locked, purchase not committed
        errores: list[BaseException] = []

        def _anular() -> None:
            otra = sessionmaker(bind=engine)()
            try:
                service.anular(otra, tactical.id, USUARIO, "Se cayó el acuerdo")
            except BaseException as exc:  # noqa: BLE001 - surfaced by the assert below
                errores.append(exc)
            finally:
                otra.close()

        hilo = threading.Thread(target=_anular)
        hilo.start()
        hilo.join(timeout=1)
        assert hilo.is_alive()  # anular waits on the worker's lock
        worker.commit()
        worker.close()
        hilo.join(timeout=10)

        assert not hilo.is_alive() and errores == []
        [(cabecera, _)] = self._compras(engine, tactical.id)
        assert cabecera[0] == "anulada"
        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "aplicada")]

    def test_the_worker_waits_for_a_void_that_locked_the_tactical_first(self, db, engine) -> None:
        """The other order: anular holds the tactical (FOR UPDATE) and is about to void the waiting row; the worker
        must wait for it without locking that row first (no deadlock), then find nothing left to apply."""
        import threading

        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        tactical = self._crear(db, pendiente)
        self._vincular(engine, pendiente, date(2026, 10, 10), {2964: 10})
        anulando = engine.connect()
        tx = anulando.begin()
        anulando.execute(text("SELECT id FROM tacticals WHERE id = :t FOR UPDATE"), {"t": tactical.id})
        resultado: list = []

        def _aplicar() -> None:
            worker = sessionmaker(bind=engine)()
            try:
                resultado.append(service.aplicar_facturas_pendientes(worker, [pendiente]))
                worker.commit()
            except BaseException as exc:  # noqa: BLE001 - surfaced by the assert below
                resultado.append(exc)
            finally:
                worker.close()

        hilo = threading.Thread(target=_aplicar)
        hilo.start()
        hilo.join(timeout=1)
        anulando.execute(text("SET LOCAL lock_timeout = '3s'"))
        anulando.execute(
            text("UPDATE tactical_facturas_pendientes SET estado = 'anulada' WHERE tactical_id = :t"),
            {"t": tactical.id},
        )
        tx.commit()
        anulando.close()
        hilo.join(timeout=10)

        assert resultado == [0]
        assert self._compras(engine, tactical.id) == []
        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "anulada")]

    def test_editing_the_name_keeps_the_pending_total(self, db, engine) -> None:
        from app.schemas.tacticals import TacticalEditarIn

        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        tactical = self._crear(db, pendiente)

        service.editar(db, tactical.id, TacticalEditarIn(nombre="Rebate nuevo"), USUARIO)

        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "pendiente")]
        self._vincular(engine, pendiente, date(2026, 10, 10), {2964: 10})
        self._worker()
        assert [c[0][0] for c in self._compras(engine, tactical.id)] == ["activa"]

    def test_replacing_keeps_an_unchanged_pending_total_and_replaces_a_changed_one(self, db, engine) -> None:
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        tactical = self._crear(db, pendiente)
        linea = {"alcance": "factura", "pedido_compra_id": pendiente, "modo_monto": "monto_total", "valor": "15000"}
        igual = _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None)

        service.reemplazar(db, tactical.id, igual, USUARIO)
        with engine.connect() as conn:
            antes = conn.execute(text("SELECT id FROM tactical_facturas_pendientes")).scalars().all()
        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "pendiente")]

        otro = _tactical("sell_in", [{**linea, "valor": "9000"}], fecha_desde=None, fecha_hasta=None)
        service.reemplazar(db, tactical.id, otro, USUARIO)

        assert self._pendientes(engine, tactical.id) == [(1, pendiente, "pendiente")]
        [salida] = service.serializar(db, [db.get(type(tactical), tactical.id)])[0]["lineas"]
        assert salida["valor"] == Decimal("9000")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT id FROM tactical_facturas_pendientes")).scalars().all() != antes
        self._vincular(engine, pendiente, date(2026, 10, 10), {2964: 10})
        self._worker()
        [(cabecera, _)] = self._compras(engine, tactical.id)
        assert (cabecera[0], cabecera[3]) == ("activa", Decimal("9000.00"))

    def test_an_invoice_linked_while_a_replace_commits_still_applies(self, db, engine, monkeypatch) -> None:
        """Window c on the other save that creates lines: Editar moves the line to another operation (reemplazar),
        so no committed row the triggers could see points at the one Compras links."""
        anterior, pendiente = bw.pedido(engine, {}, None, moneda="ARS"), bw.pedido(engine, {}, None, moneda="ARS")
        tactical = self._crear(db, anterior)
        bw.clear_queue(engine)
        linea = {"alcance": "factura", "pedido_compra_id": pendiente, "modo_monto": "monto_total", "valor": "9000"}
        _vincular_al_commitear(db, engine, pendiente, date(2026, 10, 10), {2964: 10})

        service.reemplazar(db, tactical.id, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None), USUARIO)

        assert ("pedido", pendiente) in bw.queued(engine)
        _una_corrida_del_worker(monkeypatch, engine)
        [(cabecera, _)] = self._compras(engine, tactical.id)
        assert (cabecera[0], cabecera[3]) == ("activa", Decimal("9000.00"))

    def test_a_renewal_of_a_voided_tactical_gets_its_own_pending_total(self, db, engine) -> None:
        """Renovar is the new-tactical form filled from the old one (frontend `tacticalRenovar.js`): a new create."""
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        viejo = self._crear(db, pendiente)
        service.anular(db, viejo.id, USUARIO, None)

        nuevo = self._crear(db, pendiente, nombre="Rebate renovado")
        self._vincular(engine, pendiente, date(2026, 10, 10), {2964: 10})
        self._worker()

        assert self._compras(engine, viejo.id) == []
        assert [c[0][0] for c in self._compras(engine, nuevo.id)] == ["activa"]
        assert self._pendientes(engine, nuevo.id) == [(1, pendiente, "aplicada")]

    def test_a_total_still_takes_no_caps_while_it_waits(self, db, engine) -> None:
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        linea = {"alcance": "factura", "pedido_compra_id": pendiente, "modo_monto": "monto_total", "valor": "15000",
                 "tope_unidades": 5}  # fmt: skip

        with pytest.raises(service.TacticalError, match="^Línea 1: un monto total no lleva topes"):
            service.crear(db, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None), USUARIO)
        assert _contar(engine, "tacticals") == 0


class TestVariasFacturas:
    """Sell in invoice line over an operation with several invoices, S2 (owner 2026-11-13: "por defecto tendría que
    aplicar a todas las facturas el sell in"): the line covers every invoice of the operation, the loaded and the
    pending path alike, and an invoice linked later is covered too. The invoiced-lines snapshot holds the operation's
    units over all its invoices (`reconciliar_lineas_facturadas`), so a second invoice is more units on the
    snapshot. A fixed total is split once over all the invoiced lines and re-split when another invoice links; it is
    never applied once per invoice."""

    PRIMERA = {2964: 10}  # first invoice
    TODAS = {2964: 10, 950: 5}  # first and second invoice

    @pytest.fixture(autouse=True)
    def _worker_db(self, engine, monkeypatch) -> None:
        monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))

    def _worker(self) -> None:
        TestFacturaPendienteTotal._worker(self)

    def _crear(self, db: Session, pedido: int, modo: str, valor: str, **cabecera):
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": modo, "valor": valor}
        return service.crear(db, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None, **cabecera), USUARIO)

    def _compras(self, engine: Engine, tactical_id: int) -> list[tuple]:
        return TestFacturaPendienteTotal._compras(self, engine, tactical_id)

    def _activas(self, engine: Engine, tactical_id: int) -> list[tuple]:
        return [(cabecera, items) for cabecera, items in self._compras(engine, tactical_id) if cabecera[0] == "activa"]

    def _bono(self, engine: Engine, tactical_id: int) -> int:
        return TestFacturaPendiente._bono(self, engine, tactical_id)[0]

    def _items(self, items: list[tuple]) -> dict[int, int]:
        return {item_id: cantidad for item_id, cantidad, _ in items}

    # default: all invoices, loaded and pending

    @pytest.mark.parametrize("modo", ["por_unidad", "porcentaje"])
    def test_a_bonus_line_loaded_with_two_invoices_covers_both(self, db, engine, modo) -> None:
        pedido = bw.pedido(engine, self.TODAS, date(2026, 10, 10))
        bw.set_importe(engine, pedido, 2964, "41500.00", "USD")
        bw.set_importe(engine, pedido, 950, "4950.00", "USD")
        tactical = self._crear(db, pedido, modo, "2")
        self._worker()

        assert self._items(bw.items_de(engine, self._bono(engine, tactical.id), pedido)) == self.TODAS

    def test_a_bonus_line_waiting_for_two_invoices_covers_both(self, db, engine) -> None:
        pedido = bw.pedido(engine, {}, None)
        tactical = self._crear(db, pedido, "por_unidad", "2")

        bw.update_pedido(engine, pedido, fecha_factura=date(2026, 10, 10))
        bw.set_lineas(engine, pedido, self.TODAS)
        self._worker()

        assert self._items(bw.items_de(engine, self._bono(engine, tactical.id), pedido)) == self.TODAS

    def test_a_total_loaded_with_two_invoices_is_one_purchase_over_both(self, db, engine) -> None:
        pedido = bw.pedido(engine, self.TODAS, date(2026, 10, 10), moneda="ARS")
        tactical = self._crear(db, pedido, "monto_total", "15000")

        [(cabecera, items)] = self._compras(engine, tactical.id)
        assert cabecera[3] == Decimal("15000")
        assert self._items(items) == self.TODAS
        assert sum(m for _, _, m in items) == Decimal("15000")

    def test_a_total_waiting_for_two_invoices_is_one_purchase_over_both(self, db, engine) -> None:
        pedido = bw.pedido(engine, {}, None, moneda="ARS")
        tactical = self._crear(db, pedido, "monto_total", "15000")

        bw.update_pedido(engine, pedido, fecha_factura=date(2026, 10, 10))
        bw.set_lineas(engine, pedido, self.TODAS)
        self._worker()

        [(cabecera, items)] = self._compras(engine, tactical.id)
        assert (cabecera[0], cabecera[3]) == ("activa", Decimal("15000"))
        assert self._items(items) == self.TODAS

    # an invoice linked later

    def test_a_bonus_line_covers_an_invoice_linked_later(self, db, engine) -> None:
        pedido = bw.pedido(engine, self.PRIMERA, date(2026, 10, 10))
        tactical = self._crear(db, pedido, "por_unidad", "2")
        self._worker()
        bono = self._bono(engine, tactical.id)
        assert self._items(bw.items_de(engine, bono, pedido)) == self.PRIMERA

        bw.set_lineas(engine, pedido, self.TODAS)
        assert ("pedido", pedido) in bw.queued(engine)
        self._worker()

        assert self._items(bw.items_de(engine, bono, pedido)) == self.TODAS

    def test_a_loaded_total_is_re_split_when_another_invoice_links(self, db, engine) -> None:
        pedido = bw.pedido(engine, self.PRIMERA, date(2026, 10, 10), moneda="ARS")
        tactical = self._crear(db, pedido, "monto_total", "15000")
        [(antes, _)] = self._compras(engine, tactical.id)
        bw.clear_queue(engine)

        bw.set_lineas(engine, pedido, self.TODAS)
        assert ("pedido", pedido) in bw.queued(engine)  # no bonus covers it: only the applied total gates it in
        self._worker()

        [(despues, items)] = self._compras(engine, tactical.id)  # the same purchase, never a second one
        assert despues == antes  # header: still active, same total, currency, operation
        assert self._items(items) == self.TODAS
        assert sum(m for _, _, m in items) == Decimal("15000")

    def test_a_pending_total_is_re_split_when_a_second_invoice_links(self, db, engine) -> None:
        pedido = bw.pedido(engine, {}, None, moneda="ARS")
        tactical = self._crear(db, pedido, "monto_total", "15000")
        bw.update_pedido(engine, pedido, fecha_factura=date(2026, 10, 10))
        bw.set_lineas(engine, pedido, self.PRIMERA)
        self._worker()
        [(_, items)] = self._compras(engine, tactical.id)
        assert self._items(items) == self.PRIMERA

        bw.set_lineas(engine, pedido, self.TODAS)
        self._worker()

        [(cabecera, items)] = self._compras(engine, tactical.id)
        assert (cabecera[0], cabecera[3]) == ("activa", Decimal("15000"))
        assert self._items(items) == self.TODAS
        assert sum(m for _, _, m in items) == Decimal("15000")
        assert TestFacturaPendienteTotal._pendientes(self, engine, tactical.id) == [(1, pedido, "aplicada")]

    def test_the_re_split_keeps_the_existing_lines_cost_and_matches_a_total_loaded_with_both(self, db, engine) -> None:
        tarde = bw.pedido(engine, self.PRIMERA, date(2026, 10, 10), moneda="ARS")
        partido = self._crear(db, tarde, "monto_total", "15000", nombre="Rebate")
        bw.set_lineas(engine, tarde, self.TODAS)
        self._worker()
        juntas = bw.pedido(engine, self.TODAS, date(2026, 10, 10), moneda="ARS")
        cargado = self._crear(db, juntas, "monto_total", "15000", nombre="Rebate")

        [(_, items_tarde)] = self._compras(engine, partido.id)
        [(_, items_juntas)] = self._compras(engine, cargado.id)
        assert items_tarde == items_juntas  # costs unchanged in between: same split as loaded with both

    # parity: a single invoice is unchanged

    def test_requeueing_an_unchanged_single_invoice_leaves_its_total_as_is(self, db, engine) -> None:
        pedido = bw.pedido(engine, self.PRIMERA, date(2026, 10, 10), moneda="ARS")
        tactical = self._crear(db, pedido, "monto_total", "15000")
        antes = self._compras(engine, tactical.id)
        with engine.connect() as conn:
            auditadas = conn.execute(text("SELECT count(*) FROM auditoria")).scalar()

        with engine.begin() as conn:
            conn.execute(text("INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES ('pedido', :p)"), {"p": pedido})
        self._worker()

        assert self._compras(engine, tactical.id) == antes
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM auditoria")).scalar() == auditadas
