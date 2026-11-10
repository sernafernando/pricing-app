"""Editing a tactical (`app.services.tacticals.editar`, tacticals F1) on Postgres: only the name, the note, the end
date and the caps change, and each change reaches the child campaigns and bonuses through their engines' own edit
steps, audited like the create."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.schemas.tacticals import TacticalEditarIn
from app.services import tacticals as service
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _bono_world as bw
from tests.services.test_tacticals_postgres import STUBS, TABLES, USUARIO, _contar, _install, _tactical

pytestmark = pytest.mark.postgres

HOY = date(2026, 11, 10)
POR_PRODUCTO = {"alcance": "productos", "item_ids": [2964, 2270], "modo_monto": "por_unidad", "valor": "5",
                "tope_unidades": 100, "tope_por_producto": True}  # fmt: skip


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("tacticals_edit", TABLES, STUBS, after=_install) as engine:
        yield engine


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
        bw.clean(engine)
        with engine.begin() as conn:
            conn.execute(text("UPDATE productos_erp SET categoria = 'Routers', iva = 21"))
            conn.execute(text("DELETE FROM tacticals"))
            conn.execute(text("DELETE FROM sell_out_dirty"))


def _editar(db, tactical_id: int, **cambios):
    return service.editar(db, tactical_id, TacticalEditarIn(**cambios), USUARIO, hoy=HOY)


def _filas(engine: Engine, sql: str) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(f) for f in conn.execute(text(sql))]


class TestSellOut:
    def test_name_note_end_date_and_caps_reach_every_campaign_of_the_line(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(lineas=[POR_PRODUCTO]), USUARIO)
        grupos = _filas(engine, "SELECT campana_id, grupo_id FROM sell_out_campana_grupos ORDER BY campana_id")

        editado = _editar(db, tactical.id, nombre="Tactical diciembre", nota="Acuerdo extendido",
                          fecha_hasta=date(2026, 12, 15), lineas=[{"linea": 1, "tope_unidades": 150}])  # fmt: skip

        assert (editado.nombre, editado.nota, editado.fecha_hasta) == (
            "Tactical diciembre", "Acuerdo extendido", date(2026, 12, 15),
        )  # fmt: skip
        assert _filas(engine, "SELECT nombre, fecha_hasta, tope_unidades FROM sell_out_campanas ORDER BY id") == [
            ("Tactical diciembre · línea 1 · C2964", date(2026, 12, 15), 150),
            ("Tactical diciembre · línea 1 · C2270", date(2026, 12, 15), 150),
        ]
        assert _filas(engine, "SELECT campana_id, grupo_id FROM sell_out_campana_grupos ORDER BY campana_id") == grupos
        assert _contar(engine, "auditoria", "tipo_accion = 'SELL_OUT_CAMPANA_EDITADA'") == 2
        [(antes, despues)] = _filas(
            engine, "SELECT valores_anteriores, valores_nuevos FROM auditoria WHERE tipo_accion = 'TACTICAL_EDITADO'"
        )
        assert (antes["nombre"], despues["nombre"], despues["fecha_hasta"]) == (
            "Tactical noviembre", "Tactical diciembre", "2026-12-15",
        )  # fmt: skip
        assert despues["lineas"] == [{"linea": 1, "tope_unidades": 150}]

    def test_an_edited_campaign_is_queued_for_recompute(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM sell_out_dirty"))
        [(cid,)] = _filas(engine, "SELECT id FROM sell_out_campanas")

        _editar(db, tactical.id, lineas=[{"linea": 1, "tope_unidades": 40}])

        assert _filas(engine, "SELECT campana_id FROM sell_out_dirty") == [(cid,)]

    def test_a_child_refused_after_another_changed_leaves_nothing_edited(self, db, engine, monkeypatch) -> None:
        tactical = service.crear(db, _tactical(lineas=[POR_PRODUCTO]), USUARIO)
        antes = _filas(engine, "SELECT id, nombre, tope_unidades FROM sell_out_campanas ORDER BY id")
        editar = service.campanas.editar_campana_sin_commit
        vistas = []

        def _segunda_rechaza(db_, campana_id, *args, **kwargs):
            vistas.append(campana_id)
            if len(vistas) == 2:
                raise service.campanas.SellOutError("El motor rechazó la campaña")
            return editar(db_, campana_id, *args, **kwargs)

        monkeypatch.setattr(service.campanas, "editar_campana_sin_commit", _segunda_rechaza)
        with pytest.raises(service.TacticalError, match="^Línea 1: el motor rechazó la campaña$"):
            _editar(db, tactical.id, nombre="Otro", lineas=[{"linea": 1, "tope_unidades": 150}])

        assert len(vistas) == 2
        assert _filas(engine, "SELECT id, nombre, tope_unidades FROM sell_out_campanas ORDER BY id") == antes
        assert _filas(engine, f"SELECT nombre FROM tacticals WHERE id = {tactical.id}") == [("Tactical noviembre",)]
        assert _contar(engine, "auditoria", "tipo_accion IN ('SELL_OUT_CAMPANA_EDITADA', 'TACTICAL_EDITADO')") == 0

    def test_a_cap_below_what_was_used_is_refused_and_nothing_changes(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
                "SELECT id, 'fuera', 1, 2964, '2026-11-03', 5, 50 FROM sell_out_campanas"
            ))  # fmt: skip

        with pytest.raises(service.TacticalError) as exc:
            _editar(db, tactical.id, nombre="Otro", lineas=[{"linea": 1, "tope_unidades": 4, "tope_monto": "49"}])

        assert str(exc.value) == "Línea 1: el tope de unidades (4) no puede quedar debajo de lo ya usado (5)"
        assert _filas(engine, "SELECT nombre, tope_unidades FROM sell_out_campanas") == [
            ("Tactical noviembre · línea 1", None)
        ]
        assert _contar(engine, "auditoria", "tipo_accion = 'TACTICAL_EDITADO'") == 0

    def test_a_per_store_cap_may_go_down_to_what_its_most_used_store_used(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE tacticals SET tope_compartido = false WHERE id = {tactical.id}"))
            conn.execute(text(
                "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
                "SELECT id, 'fuera', 1, 2964, DATE '2026-11-03', 5, 50 FROM sell_out_campanas UNION ALL "
                "SELECT id, 'tn', 2, 2964, DATE '2026-11-04', 3, 30 FROM sell_out_campanas"
            ))  # fmt: skip

        _editar(db, tactical.id, lineas=[{"linea": 1, "tope_unidades": 6, "tope_monto": "50"}])

        assert _filas(engine, "SELECT tope_unidades, tope_monto FROM sell_out_campanas") == [(6, Decimal("50.00"))]

    def test_a_per_store_cap_below_what_its_most_used_store_used_is_refused(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE tacticals SET tope_compartido = false WHERE id = {tactical.id}"))
            conn.execute(text(
                "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
                "SELECT id, 'fuera', 1, 2964, DATE '2026-11-03', 5, 50 FROM sell_out_campanas UNION ALL "
                "SELECT id, 'tn', 2, 2964, DATE '2026-11-04', 3, 30 FROM sell_out_campanas"
            ))  # fmt: skip

        with pytest.raises(service.TacticalError) as exc:
            _editar(db, tactical.id, lineas=[{"linea": 1, "tope_unidades": 4}])

        assert str(exc.value) == (
            "Línea 1: el tope de unidades (4) no puede quedar debajo de lo ya usado en una tienda o canal (5)"
        )
        assert _filas(engine, "SELECT tope_unidades FROM sell_out_campanas") == [(None,)]

    def test_a_money_cap_below_what_was_used_is_refused(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
                "SELECT id, 'fuera', 1, 2964, '2026-11-03', 5, 50 FROM sell_out_campanas"
            ))  # fmt: skip

        with pytest.raises(service.TacticalError, match=r"^Línea 1: el tope de monto \(49\.00\) no puede quedar "):
            _editar(db, tactical.id, lineas=[{"linea": 1, "tope_monto": "49"}])

    def test_a_null_cap_removes_it(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(lineas=[POR_PRODUCTO]), USUARIO)

        _editar(db, tactical.id, lineas=[{"linea": 1, "tope_unidades": None}])

        assert _filas(engine, "SELECT DISTINCT tope_unidades FROM sell_out_campanas") == [(None,)]

    def test_the_end_date_never_goes_before_today_nor_before_the_start(self, db) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        with pytest.raises(service.TacticalError) as exc:
            _editar(db, tactical.id, fecha_hasta=date(2026, 11, 9))
        assert str(exc.value) == "La fecha hasta no puede ser anterior a hoy (10/11/2026)"

        with pytest.raises(service.TacticalError) as exc:
            service.editar(
                db, tactical.id, TacticalEditarIn(fecha_hasta=date(2026, 10, 30)), USUARIO, hoy=date(2026, 10, 20)
            )
        assert str(exc.value) == "La fecha hasta no puede ser anterior a la fecha desde (01/11/2026)"

    def test_an_unknown_line_and_an_empty_name_are_refused(self, db) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        with pytest.raises(service.TacticalError, match="^El tactical no tiene línea 3$"):
            _editar(db, tactical.id, lineas=[{"linea": 3, "tope_unidades": 10}])
        with pytest.raises(service.TacticalError, match="^Línea 1: el tope de monto debe ser mayor que cero$"):
            _editar(db, tactical.id, lineas=[{"linea": 1, "tope_monto": "0"}])
        with pytest.raises(service.TacticalError, match="^El nombre no puede quedar vacío$"):
            _editar(db, tactical.id, nombre="  ")

    def test_a_voided_tactical_is_not_edited(self, db) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        service.anular(db, tactical.id, USUARIO, None)

        with pytest.raises(service.TacticalYaAnulado):
            _editar(db, tactical.id, nombre="Otro")
        assert _editar(db, 999_999, nombre="Otro") is None


class TestSellIn:
    def test_end_date_and_caps_reach_the_cost_bonus_through_its_edit(self, db, engine) -> None:
        linea = {"alcance": "productos", "item_ids": [2964], "modo_monto": "por_unidad", "valor": "36",
                 "tope_unidades": 10}  # fmt: skip
        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)

        _editar(db, tactical.id, nombre="Rebate diciembre", fecha_hasta=date(2026, 12, 31),
                lineas=[{"linea": 1, "tope_unidades": 20, "tope_monto": "5000"}])  # fmt: skip

        assert _filas(engine, "SELECT descripcion, fecha_hasta, tope_unidades, tope_monto, monto_unit "
                              "FROM sell_in_bonos_marca") == [
            ("Rebate diciembre · línea 1 · C2964", date(2026, 12, 31), 20, Decimal("5000.00"), Decimal("36.00"))
        ]  # fmt: skip
        assert _contar(engine, "auditoria", "tipo_accion = 'SELL_IN_BONO_EDITADO'") == 1

    def test_a_cost_bonus_cap_is_checked_against_everything_it_used_even_with_a_per_store_flag(
        self, db, engine
    ) -> None:
        """S5: sell in has one cap over every store and channel, whatever cap mode its tactical stored."""
        linea = {"alcance": "productos", "item_ids": [2964], "modo_monto": "por_unidad", "valor": "10",
                 "tope_unidades": 10}  # fmt: skip
        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE tacticals SET tope_compartido = false WHERE id = {tactical.id}"))
            conn.execute(text(
                "INSERT INTO sell_in_bono_consumos (bono_id, canal, venta_ref, item_id, fecha_venta, unidades, "
                "descuento_ars) SELECT id, 'fuera', 1, 2964, DATE '2026-11-03', 5, 50 FROM sell_in_bonos_marca "
                "UNION ALL SELECT id, 'tn', 2, 2964, DATE '2026-11-04', 3, 30 FROM sell_in_bonos_marca"
            ))  # fmt: skip

        with pytest.raises(service.TacticalError) as exc:
            _editar(db, tactical.id, lineas=[{"linea": 1, "tope_unidades": 6}])  # above each store, below the total
        assert "(8)" in str(exc.value)

        _editar(db, tactical.id, lineas=[{"linea": 1, "tope_unidades": 8}])

        assert _filas(engine, "SELECT tope_unidades FROM sell_in_bonos_marca") == [(8,)]

    def test_an_invoice_tactical_has_no_end_date_to_edit(self, db, engine) -> None:
        """Tactical factura sin fecha S2c/S4: its dates are its invoices' own; only the safe fields move."""
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 11, 20))
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje", "valor": "5"}
        tactical = service.crear(db, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None), USUARIO)

        with pytest.raises(service.TacticalError) as exc:
            _editar(db, tactical.id, fecha_hasta=date(2026, 12, 15))

        assert str(exc.value) == (
            "Un tactical por factura no tiene fecha hasta: cada factura aplica hasta que se venden sus unidades"
        )
        assert _editar(db, tactical.id, nombre="Factura renombrada").nombre == "Factura renombrada"
        assert _filas(engine, "SELECT fecha_desde, fecha_hasta FROM sell_in_bonos_marca") == [
            (date(2026, 11, 20), date(2026, 11, 20))
        ]

    def test_a_mixed_tactical_end_date_moves_only_its_non_invoice_lines(self, db, engine) -> None:
        """S4: `_validar_facturas` no longer applies: the invoice line keeps its invoice's date."""
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 11, 20))
        lineas = [
            {"alcance": "marca", "marca": bw.TPLINK, "modo_monto": "porcentaje", "valor": "3"},
            {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje", "valor": "5"},
        ]
        tactical = service.crear(db, _tactical("sell_in", lineas), USUARIO)

        _editar(db, tactical.id, fecha_hasta=date(2026, 11, 15))

        assert _filas(
            engine, "SELECT alcance, fecha_desde, fecha_hasta FROM sell_in_bonos_marca ORDER BY tactical_linea"
        ) == [
            ("marca", date(2026, 11, 1), date(2026, 11, 15)),
            ("factura", date(2026, 11, 20), date(2026, 11, 20)),
        ]

    def test_an_invoice_total_takes_no_caps(self, db, engine) -> None:
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 11, 10))
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "monto_total", "valor": "1000"}
        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)

        with pytest.raises(service.TacticalError, match="^Línea 1: un monto total no lleva topes"):
            _editar(db, tactical.id, lineas=[{"linea": 1, "tope_unidades": 5}])
        assert _editar(db, tactical.id, nombre="Total renombrado").nombre == "Total renombrado"

    def test_a_usd_cost_reduction_takes_no_money_cap_as_on_create(self, db, engine) -> None:
        """The cost bonus is in ARS: a cap in the tactical's USD would be read as pesos."""
        linea = {"alcance": "marca", "marca": bw.TPLINK, "modo_monto": "porcentaje", "valor": "3"}
        tactical = service.crear(db, _tactical("sell_in", [linea], moneda="USD"), USUARIO)

        with pytest.raises(service.TacticalError, match="^Línea 1: una reducción de costo por unidad o con tope de "):
            _editar(db, tactical.id, lineas=[{"linea": 1, "tope_monto": "500"}])
        assert _filas(engine, "SELECT tope_monto FROM sell_in_bonos_marca") == [(None,)]
