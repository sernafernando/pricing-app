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
from app.schemas.tacticals import TacticalIn
from app.services import tacticals as service
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _bono_world as bw

pytestmark = pytest.mark.postgres

USUARIO = 7
TPLINK = bw.TPLINK
TABLES = [
    *bw.TABLES,
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
            conn.execute(text("DELETE FROM tacticals"))
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

    def test_an_invoice_outside_the_dates_is_refused(self, db) -> None:
        pedido = bw.pedido(db.get_bind(), {2964: 10}, date(2026, 10, 10))
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje", "valor": "5"}

        with pytest.raises(service.TacticalError, match="fuera de la vigencia"):
            service.crear(db, _tactical("sell_in", [linea]), USUARIO)

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
