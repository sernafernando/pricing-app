"""Tacticals approval (handoffs/tacticals-aprobacion-plan.md S2-S8) on Postgres, through `app.services.tacticals`
and the engines it drives. Owner L30: "tienen que quedar con un filtro de pendientes de aprobación para que alejandro
los revise y los apruebe y que no apliquen de una". A load starts `pendiente` and applies to nothing; approving it
applies every line in one go; a money edit sends it back; the name, the note and the collection keep it approved.
Invented data, the world of `test_tacticals_postgres.py` (WITHOUT its auto-approval)."""

from __future__ import annotations

from datetime import date
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.schemas.tacticals import TacticalCobranzaIn, TacticalEditarIn
from app.services import tacticals as service
from app.services.sell_in import bonos, bonos_costo
from app.services.sell_out import asignacion
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _bono_world as bw
from tests.services.sell_in import _world as w
from tests.services.test_tacticals_postgres import STUBS, TABLES, USUARIO, _contar, _install, _sql, _tactical

pytestmark = pytest.mark.postgres

APROBADOR = 8
HOY = date(2026, 11, 2)
POR_UNIDAD = {"alcance": "productos", "item_ids": [2964], "modo_monto": "por_unidad", "valor": "36"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("tacticals_aprob", TABLES, STUBS, after=_install) as engine:
        yield engine


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session = sessionmaker(bind=engine)()
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
        bw.clean(engine)
        with engine.begin() as conn:
            for table in ("tactical_tiendas", "tactical_marcas", "tactical_cobranzas", "tacticals", "sell_out_dirty"):
                conn.execute(text(f"DELETE FROM {table}"))


def _estados(engine: Engine, tactical_id: int) -> dict:
    """The tactical's state and its lines' per engine."""
    salida = {"tactical": _sql(engine, f"SELECT estado FROM tacticals WHERE id = {tactical_id}")[0][0]}
    for tabla in ("sell_out_campanas", "sell_in_bonos_marca", "sell_in_compras"):
        salida[tabla] = sorted(
            r[0] for r in _sql(engine, f"SELECT estado FROM {tabla} WHERE tactical_id = {tactical_id}")
        )
    return salida


def _auditadas(engine: Engine) -> list[str]:
    return [
        r[0] for r in _sql(engine, "SELECT tipo_accion FROM auditoria WHERE tipo_accion LIKE 'TACTICAL_%' ORDER BY id")
    ]


def _recalcular_bonos(engine: Engine, bono_ids: list[int]) -> None:
    with sessionmaker(bind=engine)() as otra:
        bonos_costo.recalcular(otra, bono_ids=bono_ids)
        otra.commit()


def _bonos_de(engine: Engine, tactical_id: int) -> list[int]:
    return [r[0] for r in _sql(engine, f"SELECT id FROM sell_in_bonos_marca WHERE tactical_id = {tactical_id}")]


class TestCarga:
    def test_a_new_sell_out_tactical_is_pending_with_its_lines_and_queues_nothing(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        assert _estados(engine, tactical.id)["tactical"] == "pendiente"
        assert _estados(engine, tactical.id)["sell_out_campanas"] == ["pendiente"]
        assert _contar(engine, "sell_out_dirty") == 0  # nothing to rebuild: it applies to nothing
        leido = service.serializar(db, [tactical])[0]
        assert (leido["estado"], leido["aprobado_por"], leido["aprobado_at"]) == ("pendiente", None, None)
        assert [linea["estado"] for linea in leido["lineas"]] == ["pendiente"]

    def test_a_new_sell_in_tactical_is_pending_and_queues_no_reconcile(self, db, engine) -> None:
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 10, 10))
        bw.clear_queue(engine)
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "por_unidad", "valor": "2"}

        tactical = service.crear(db, _tactical("sell_in", [linea, POR_UNIDAD]), USUARIO)

        assert _estados(engine, tactical.id)["sell_in_bonos_marca"] == ["pendiente", "pendiente"]
        assert ("bono", _bonos_de(engine, tactical.id)[0]) not in bw.queued(engine)

    def test_an_invoice_total_is_a_pending_purchase_that_consumes_nothing(self, db, engine) -> None:
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 10, 10), moneda="ARS")
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "monto_total", "valor": "15000"}
        w.venta(engine, "fuera", 2964, 3, date(2026, 10, 20))

        tactical = service.crear(db, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None), USUARIO)

        assert _estados(engine, tactical.id)["sell_in_compras"] == ["pendiente"]
        assert w.consumos(engine) == []  # FIFO: a pending purchase discounts no sale


class TestAprobar:
    def test_approving_applies_every_line_and_records_who_and_when(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        aprobado = service.aprobar(db, tactical.id, APROBADOR)

        assert _estados(engine, tactical.id)["sell_out_campanas"] == ["activa"]
        assert (aprobado.estado, aprobado.aprobado_por) == ("activo", APROBADOR)
        assert aprobado.aprobado_at is not None
        assert _sql(engine, "SELECT count(*) FROM sell_out_dirty") == [(1,)]  # queued for sell_out.drain
        assert _auditadas(engine) == ["TACTICAL_CREADO", "TACTICAL_APROBADO"]

    def test_its_author_may_approve_it(self, db, engine) -> None:
        """L31: "el va a poder aprobar sus propios tacticals"."""
        tactical = service.crear(db, _tactical(), USUARIO)

        assert service.aprobar(db, tactical.id, USUARIO).aprobado_por == USUARIO

    def test_a_second_approval_or_a_voided_tactical_is_refused(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        service.aprobar(db, tactical.id, APROBADOR)
        with pytest.raises(service.TacticalYaAprobado):
            service.aprobar(db, tactical.id, APROBADOR)

        otro = service.crear(db, _tactical(nombre="Otro"), USUARIO)
        service.anular(db, otro.id, USUARIO, None)
        with pytest.raises(service.TacticalYaAnulado):
            service.aprobar(db, otro.id, APROBADOR)
        assert service.aprobar(db, 999999, APROBADOR) is None

    def test_a_cost_bonus_gives_nothing_until_approved(self, db, engine) -> None:
        """Per-sale cost bonuses (`bonos_costo`): a pending line takes no sale; approved, it does."""
        tactical = service.crear(db, _tactical("sell_in", [POR_UNIDAD]), USUARIO)
        w.venta(engine, "fuera", 2964, 3, date(2026, 11, 10))
        bono_ids = _bonos_de(engine, tactical.id)

        _recalcular_bonos(engine, bono_ids)
        assert bw.bono_consumos(engine) == []

        service.aprobar(db, tactical.id, APROBADOR)
        _recalcular_bonos(engine, bono_ids)
        assert [(c[0], c[5]) for c in bw.bono_consumos(engine)] == [(bono_ids[0], 3)]

    def test_an_invoice_bonus_generates_its_purchases_only_once_approved(self, db, engine) -> None:
        """The bonus reconcile (and the purchases it derives, `origen = 'bono_marca'`) follow the bonus."""
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 10, 10))
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "por_unidad", "valor": "2"}
        tactical = service.crear(db, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None), USUARIO)

        bonos.reconciliar(db, pedido_ids=[pedido])
        db.commit()
        assert bw.generadas(engine) == []

        service.aprobar(db, tactical.id, APROBADOR)
        assert ("bono", _bonos_de(engine, tactical.id)[0]) in bw.queued(engine)  # its trigger queued the reconcile
        bonos.reconciliar(db, pedido_ids=[pedido])
        db.commit()
        assert [g[2] for g in bw.generadas(engine)] == ["activa"]

        service.a_pendiente(db, tactical.id, USUARIO, "prueba")
        db.commit()
        bonos.reconciliar(db, pedido_ids=[pedido])
        db.commit()
        assert [g[2] for g in bw.generadas(engine)] == ["anulada"]  # back to pending: what it derived is voided

    def test_an_invoice_total_starts_consuming_once_approved(self, db, engine) -> None:
        """FIFO: the approval recomputes the purchase's products in the same transaction."""
        pedido = bw.pedido(engine, {2964: 10}, date(2026, 10, 10), moneda="ARS")
        linea = {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "monto_total", "valor": "15000"}
        w.venta(engine, "fuera", 2964, 3, date(2026, 10, 20))
        tactical = service.crear(db, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None), USUARIO)

        service.aprobar(db, tactical.id, APROBADOR)

        assert [c[4] for c in w.consumos(engine)] == [3]

    def test_a_waiting_invoice_total_follows_its_tactical(self, db, engine) -> None:
        """The purchase a waiting total becomes when its invoice arrives is pending under a pending tactical and
        active under an approved one."""
        pendiente = bw.pedido(engine, {}, None, moneda="ARS")
        linea = {"alcance": "factura", "pedido_compra_id": pendiente, "modo_monto": "monto_total", "valor": "15000"}
        tactical = service.crear(db, _tactical("sell_in", [linea], fecha_desde=None, fecha_hasta=None), USUARIO)
        bw.update_pedido(engine, pendiente, fecha_factura=date(2026, 10, 10))
        bw.set_lineas(engine, pendiente, {2964: 10})

        assert service.aplicar_facturas_pendientes(db, [pendiente]) == 1
        db.commit()
        assert _estados(engine, tactical.id)["sell_in_compras"] == ["pendiente"]

        service.aprobar(db, tactical.id, APROBADOR)
        assert _estados(engine, tactical.id)["sell_in_compras"] == ["activa"]

    def test_a_sell_out_campaign_rebuilds_nothing_while_pending(self, db, engine) -> None:
        """Sell out (`asignacion.recalcular`): a pending campaign gets no consumptions."""
        tactical = service.crear(db, _tactical(lineas=[POR_UNIDAD]), USUARIO)
        w.venta(engine, "fuera", 2964, 3, date(2026, 11, 10))
        [(cid,)] = _sql(engine, f"SELECT id FROM sell_out_campanas WHERE tactical_id = {tactical.id}")

        with sessionmaker(bind=engine)() as otra:
            asignacion.recalcular(otra, [cid])
            otra.commit()
        assert _contar(engine, "sell_out_consumos") == 0

        service.aprobar(db, tactical.id, APROBADOR)
        with sessionmaker(bind=engine)() as otra:
            asignacion.recalcular(otra, [cid])
            otra.commit()
        assert _contar(engine, "sell_out_consumos") == 1


class TestEdicion:
    def _aprobado(self, db, **cabecera):
        tactical = service.crear(db, _tactical(lineas=[{**POR_UNIDAD, "tope_unidades": 50}], **cabecera), USUARIO)
        return service.aprobar(db, tactical.id, APROBADOR)

    def test_a_new_end_date_or_cap_sends_it_back_to_pending(self, db, engine) -> None:
        tactical = self._aprobado(db)

        service.editar(db, tactical.id, TacticalEditarIn(fecha_hasta=date(2026, 12, 15)), USUARIO, hoy=HOY)

        assert _estados(engine, tactical.id) == {
            "tactical": "pendiente", "sell_out_campanas": ["pendiente"], "sell_in_bonos_marca": [],
            "sell_in_compras": [],
        }  # fmt: skip
        assert _sql(engine, f"SELECT aprobado_por, aprobado_at FROM tacticals WHERE id = {tactical.id}") == [
            (None, None)
        ]
        assert _auditadas(engine)[-1] == "TACTICAL_A_PENDIENTE"

        otro = self._aprobado(db, nombre="Otro")
        service.editar(db, otro.id, TacticalEditarIn(lineas=[{"linea": 1, "tope_unidades": 80}]), USUARIO, hoy=HOY)
        assert _estados(engine, otro.id)["tactical"] == "pendiente"

    def test_the_name_or_the_note_keeps_it_approved(self, db, engine) -> None:
        tactical = self._aprobado(db)

        service.editar(db, tactical.id, TacticalEditarIn(nombre="Tactical renombrado", nota="ok"), USUARIO, hoy=HOY)

        assert _estados(engine, tactical.id)["tactical"] == "activo"
        assert _estados(engine, tactical.id)["sell_out_campanas"] == ["activa"]
        assert _sql(engine, f"SELECT aprobado_por FROM tacticals WHERE id = {tactical.id}") == [(APROBADOR,)]

    def test_replacing_with_new_amounts_sends_it_back_and_its_new_lines_wait(self, db, engine) -> None:
        tactical = self._aprobado(db)

        service.reemplazar(db, tactical.id, _tactical(lineas=[{**POR_UNIDAD, "valor": "40", "tope_unidades": 50}]),
                           USUARIO, hoy=HOY)  # fmt: skip

        estados = _estados(engine, tactical.id)
        assert (estados["tactical"], estados["sell_out_campanas"]) == ("pendiente", ["pendiente"])

    def test_replacing_with_only_a_new_name_keeps_it_approved(self, db, engine) -> None:
        tactical = self._aprobado(db)

        service.reemplazar(db, tactical.id, _tactical(nombre="Nuevo nombre", lineas=[{**POR_UNIDAD, "tope_unidades": 50}]),
                           USUARIO, hoy=HOY)  # fmt: skip

        estados = _estados(engine, tactical.id)
        assert (estados["tactical"], estados["sell_out_campanas"]) == ("activo", ["activa"])

    def test_a_pending_tactical_edited_stays_pending(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        service.editar(db, tactical.id, TacticalEditarIn(fecha_hasta=date(2026, 12, 15)), USUARIO, hoy=HOY)

        assert _estados(engine, tactical.id)["sell_out_campanas"] == ["pendiente"]
        assert "TACTICAL_A_PENDIENTE" not in _auditadas(engine)

    def test_the_collection_keeps_it_approved(self, db, engine) -> None:
        """S5: "cobranza edits do not" send it back."""
        tactical = self._aprobado(db)

        service.cobrar(db, tactical.id, TacticalCobranzaIn(fecha_cobro=date(2026, 12, 1)), USUARIO)
        assert service.deshacer_cobro(db, tactical.id)

        assert _estados(engine, tactical.id)["tactical"] == "activo"

    def test_a_pending_tactical_can_be_voided(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)

        service.anular(db, tactical.id, USUARIO, None)

        assert _estados(engine, tactical.id) == {
            "tactical": "anulado", "sell_out_campanas": ["anulada"], "sell_in_bonos_marca": [], "sell_in_compras": [],
        }  # fmt: skip


class TestListado:
    def test_the_pending_filter_lists_only_what_waits_for_approval(self, db, engine) -> None:
        pendiente = service.crear(db, _tactical(nombre="Pendiente"), USUARIO)
        aprobado = service.crear(db, _tactical(nombre="Aprobado"), USUARIO)
        service.aprobar(db, aprobado.id, APROBADOR)

        def ids(estado):
            total, filas = service.listar(
                db, service.Filtros(tipos=["sell_in", "sell_out"], estado=estado), 1, 50, hoy=HOY
            )
            return sorted(t.id for t in filas)

        assert ids("pendientes_aprobacion") == [pendiente.id]
        assert ids("vigentes") == [aprobado.id]  # a pending one is not current: it applies nothing yet
        assert ids(None) == sorted([pendiente.id, aprobado.id])

    def test_the_read_names_the_approver(self, db, engine) -> None:
        tactical = service.crear(db, _tactical(), USUARIO)
        service.aprobar(db, tactical.id, APROBADOR)
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS nombre TEXT"))
            conn.execute(text(f"UPDATE usuarios SET nombre = 'Alejandro' WHERE id = {APROBADOR}"))

        [leido] = service.con_aprobadores(db, service.serializar(db, [tactical]))

        assert (leido["aprobado_por"], leido["aprobado_por_nombre"]) == (APROBADOR, "Alejandro")
        assert (
            service.con_aprobadores(db, service.serializar(db, [service.crear(db, _tactical(), USUARIO)]))[0][
                "aprobado_por_nombre"
            ]
            is None
        )
