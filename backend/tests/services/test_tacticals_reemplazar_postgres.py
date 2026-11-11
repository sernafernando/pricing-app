"""Full edit of a tactical (`app.services.tacticals.reemplazar`, SISO S8) on Postgres.

Owner (S8): "Que la edición abra nuevamente el modal de creación y poder editar directamente todo ahí, por ejemplo si
se cargó un sell out y en realidad era sell in, cambiarlo directamente ahí como si lo estuvieramos haciendo de 0".
Rules (handoffs/moneda-t4-s8-decisiones.md, D1-D6 accepted in L15): the whole definition is replaced in one
transaction, the old children voided and detached, the new ones created; refused when voided, collected, or when it
would void an invoice total a manual cost mode names; a changed end date cannot be before today, an unchanged past
one stays; a set `al_cobro` rate carries while the currency and FX mode stay, else it is discarded; audited."""

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
from tests.services.test_tacticals_postgres import STUBS, TABLES, TPLINK, USUARIO, _contar, _install, _tactical

pytestmark = pytest.mark.postgres

HOY = date(2026, 11, 10)
MARCA = {"alcance": "marca", "marca": TPLINK, "modo_monto": "por_unidad", "valor": "10"}
PORCENTAJE = {"alcance": "marca", "marca": TPLINK, "modo_monto": "porcentaje", "valor": "3"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("tacticals_reemplazar", TABLES, STUBS, after=_install) as engine:
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


def _reemplazar(db: Session, tactical_id: int, data):
    return service.reemplazar(db, tactical_id, data, USUARIO, hoy=HOY)


def _filas(engine: Engine, sql: str, **params) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(f) for f in conn.execute(text(sql), params)]


class TestCambiarDeTipo:
    def test_a_sell_out_loaded_by_mistake_becomes_sell_in_under_the_same_tactical(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        [(campana_id,)] = _filas(engine, "SELECT id FROM sell_out_campanas")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM sell_out_dirty"))

        editado = _reemplazar(db, tactical.id, _tactical("sell_in", [PORCENTAJE]))

        assert (editado.id, editado.tipo) == (tactical.id, "sell_in")
        # The old campaign is voided through its engine, detached, and queued so its credits are dropped.
        assert _filas(engine, "SELECT estado, tactical_id, tactical_linea FROM sell_out_campanas") == [
            ("anulada", None, None)
        ]
        assert _filas(engine, "SELECT campana_id FROM sell_out_dirty") == [(campana_id,)]
        assert _filas(
            engine, "SELECT base, alcance, marca, porcentaje, tactical_linea, estado FROM sell_in_bonos_marca"
        ) == [("costo_venta", "marca", TPLINK, Decimal("3.00"), 1, "activa")]
        [linea] = service.serializar(db, [editado])[0]["lineas"]
        assert (linea["origen"], linea["modo_monto"], linea["valor"]) == ("sell_in_bono", "porcentaje", Decimal("3"))

    def test_every_header_field_and_line_is_replaced_and_audited(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        editado = _reemplazar(
            db,
            tactical.id,
            _tactical(
                nombre="Tactical corregido",
                referencia="ACU-9",
                fecha_desde=date(2026, 10, 15),
                fecha_hasta=date(2026, 12, 31),
                acumulable=False,
                nota="Era desde octubre",
                lineas=[MARCA, {**MARCA, "valor": "4", "categoria": "Routers"}],
            ),
        )

        assert (editado.nombre, editado.referencia, editado.fecha_desde, editado.fecha_hasta, editado.nota) == (
            "Tactical corregido", "ACU-9", date(2026, 10, 15), date(2026, 12, 31), "Era desde octubre",
        )  # fmt: skip
        assert _filas(
            engine,
            "SELECT nombre, fecha_desde, monto_unit, acumulable, tactical_linea FROM sell_out_campanas "
            "WHERE estado = 'activa' ORDER BY tactical_linea",
        ) == [
            ("Tactical corregido · línea 1", date(2026, 10, 15), Decimal("10.00"), False, 1),
            ("Tactical corregido · línea 2", date(2026, 10, 15), Decimal("4.00"), False, 2),
        ]
        [(antes, despues)] = _filas(
            engine, "SELECT valores_anteriores, valores_nuevos FROM auditoria WHERE tipo_accion = 'TACTICAL_EDITADO'"
        )
        assert (antes["nombre"], antes["lineas"][0]["valor"]) == ("Tactical noviembre", "10.00")
        assert (despues["nombre"], len(despues["definicion"]["lineas"])) == ("Tactical corregido", 2)
        assert len(despues["reemplazados"]["campana_ids"]) == 1

    def test_a_refused_new_line_leaves_the_tactical_as_it_was(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        antes = _filas(engine, "SELECT id, estado, tactical_id FROM sell_out_campanas")

        with pytest.raises(service.TacticalError, match="^Línea 2: "):
            _reemplazar(db, tactical.id, _tactical(lineas=[MARCA, {**MARCA, "marca": "NO EXISTE"}]))

        assert _filas(engine, "SELECT id, estado, tactical_id FROM sell_out_campanas") == antes
        assert _contar(engine, "auditoria", "tipo_accion = 'TACTICAL_EDITADO'") == 0


class TestBloqueos:
    def test_a_voided_tactical_is_refused(self, db) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        service.anular(db, tactical.id, USUARIO, None)

        with pytest.raises(service.TacticalYaAnulado):
            _reemplazar(db, tactical.id, _tactical("sell_in", [PORCENTAJE]))

    def test_a_collected_tactical_is_refused_until_the_collection_is_undone(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        service.cobrar(db, tactical.id, TacticalCobranzaIn(fecha_cobro=HOY), USUARIO)

        with pytest.raises(service.TacticalCobrado, match="primero deshacé el cobro"):
            _reemplazar(db, tactical.id, _tactical("sell_in", [PORCENTAJE]))
        assert _filas(engine, "SELECT estado FROM sell_out_campanas") == [("activa",)]

        service.deshacer_cobro(db, tactical.id)
        assert _reemplazar(db, tactical.id, _tactical("sell_in", [PORCENTAJE])).tipo == "sell_in"

    def test_an_unchanged_past_end_date_stays_and_a_changed_one_cannot_be_before_today(self, db) -> None:
        octubre = {"fecha_desde": date(2026, 10, 1), "fecha_hasta": date(2026, 10, 31)}
        tactical = service.crear(db, _tactical(**octubre), USUARIO)

        assert _reemplazar(db, tactical.id, _tactical("sell_in", [PORCENTAJE], **octubre)).tipo == "sell_in"
        with pytest.raises(service.TacticalError, match=r"^La fecha hasta no puede ser anterior a hoy \(10/11/2026\)$"):
            _reemplazar(
                db, tactical.id, _tactical("sell_in", [PORCENTAJE], **{**octubre, "fecha_hasta": date(2026, 11, 9)})
            )


class TestFacturaConMontoTotal:
    def _linea(self, engine: Engine) -> dict:
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 11, 10), moneda="ARS")
        return {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "monto_total", "valor": "15000"}

    def test_an_unchanged_invoice_total_keeps_its_purchase(self, db, engine) -> None:
        linea = self._linea(engine)
        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)
        [(compra_id,)] = _filas(engine, "SELECT id FROM sell_in_compras")

        _reemplazar(db, tactical.id, _tactical("sell_in", [linea], nombre="Otro nombre"))

        assert _filas(engine, "SELECT id, estado, tactical_linea FROM sell_in_compras") == [(compra_id, "activa", 1)]

    def test_a_changed_invoice_total_named_by_a_manual_cost_mode_is_refused(self, db, engine) -> None:
        linea = self._linea(engine)
        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)
        [(compra_id,)] = _filas(engine, "SELECT id FROM sell_in_compras")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sell_in_modos_producto (item_id, modo, desde, cantidad, costo_unit, costo_base_unit, "
                    "origen, compra_id, usuario_id) VALUES (2964, 'manual', '2026-11-10', 10, 1, 1, 'carga', :c, 7)"
                ),
                {"c": compra_id},
            )

        with pytest.raises(service.TacticalError, match="^Línea 1: .*modo de costo manual"):
            _reemplazar(db, tactical.id, _tactical("sell_in", [{**linea, "valor": "9000"}]))
        assert _filas(engine, "SELECT estado FROM sell_in_compras") == [("activa",)]

    def test_a_changed_invoice_total_is_voided_and_loaded_again(self, db, engine) -> None:
        linea = self._linea(engine)
        tactical = service.crear(db, _tactical("sell_in", [linea]), USUARIO)

        _reemplazar(db, tactical.id, _tactical("sell_in", [{**linea, "valor": "9000"}]))

        assert _filas(engine, "SELECT estado, monto_total, tactical_linea FROM sell_in_compras ORDER BY id") == [
            ("anulada", Decimal("15000.00"), None),
            ("activa", Decimal("9000.00"), 1),
        ]


class TestTipoDeCambioAlCobro:
    USD = {"moneda": "USD", "tc_modo": "al_cobro"}

    def _con_tasa(self, db, engine):
        tactical = service.crear(db, _tactical(**self.USD), USUARIO)
        with engine.begin() as conn:
            conn.execute(text("UPDATE sell_out_campanas SET tipo_cambio = 1450, tc_definido_en = now()"))
        return tactical

    def test_the_read_shows_the_rate_already_set(self, db, engine) -> None:
        tactical = self._con_tasa(db, engine)

        [linea] = service.serializar(db, [tactical])[0]["lineas"]

        assert linea["tc_al_cobro"] == Decimal("1450.000000")

    def test_a_set_rate_carries_while_the_currency_and_mode_stay(self, db, engine) -> None:
        tactical = self._con_tasa(db, engine)

        _reemplazar(db, tactical.id, _tactical(lineas=[{**MARCA, "valor": "12"}], **self.USD))

        assert _filas(
            engine, "SELECT monto_unit, tipo_cambio, tc_definido_en IS NOT NULL FROM sell_out_campanas "
            "WHERE estado = 'activa'"
        ) == [(Decimal("12.00"), Decimal("1450.000000"), True)]  # fmt: skip

    def test_changing_the_currency_discards_it(self, db, engine) -> None:
        tactical = self._con_tasa(db, engine)

        _reemplazar(db, tactical.id, _tactical())

        assert _filas(
            engine, "SELECT moneda, tipo_cambio, tc_definido_en FROM sell_out_campanas WHERE estado = 'activa'"
        ) == [("ARS", None, None)]
