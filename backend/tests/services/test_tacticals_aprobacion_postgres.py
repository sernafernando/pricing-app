"""Tacticals approval (handoffs/tacticals-aprobacion-plan.md S2-S8) on Postgres, through `app.services.tacticals`
and the engines it drives. Owner L30: "tienen que quedar con un filtro de pendientes de aprobación para que alejandro
los revise y los apruebe y que no apliquen de una". A load starts `pendiente` and applies to nothing; approving it
applies every line in one go; a money edit sends it back; the name, the note and the collection keep it approved.
Invented data, the world of `test_tacticals_postgres.py` (WITHOUT its auto-approval)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
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
from tests.services.test_tactical_cobranza_postgres import _usado
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
                "offsets_ganancia",
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


# --- S11, S12: the standalone pending loads and the KPIs ---------------------------------------------------------


def _insertar(engine: Engine, sql: str, **valores) -> int:
    with engine.begin() as conn:
        return conn.execute(text(sql), valores).scalar_one()


def _campana_suelta(engine: Engine, nombre: str, estado: str = "pendiente") -> int:
    return _insertar(
        engine,
        "INSERT INTO sell_out_campanas (nombre, fecha_desde, fecha_hasta, tipo, monto_unit, moneda, estado, "
        "usuario_id) VALUES (:n, '2026-11-01', '2026-11-30', 'por_unidad', 5, 'ARS', :e, 7) RETURNING id",
        n=nombre,
        e=estado,
    )


def _compra_suelta(engine: Engine, estado: str = "pendiente", **derivada) -> int:
    columnas = ", origen, bono_id" if derivada else ""
    valores = ", 'bono_marca', :b" if derivada else ""
    return _insertar(
        engine,
        f"INSERT INTO sell_in_compras (fecha_compra, cuenta_desde, moneda, monto_total, estado, usuario_id, "
        f"descripcion{columnas}) VALUES ('2026-11-05', 'compra', 'ARS', 1000, :e, 7, 'NC Epson'{valores}) RETURNING id",
        e=estado,
        **({"b": derivada["bono_id"]} if derivada else {}),
    )


def _offset(engine: Engine, estado: str = "pendiente", **valores) -> int:
    fila = {"marca": "EPSON", "descripcion": None, "moneda": "USD", "fecha_hasta": "2026-12-31", **valores}
    return _insertar(
        engine,
        "INSERT INTO offsets_ganancia (marca, descripcion, moneda, fecha_desde, fecha_hasta, estado, usuario_id) "
        "VALUES (:marca, :descripcion, :moneda, '2026-11-01', :fecha_hasta, :e, 7) RETURNING id",
        e=estado,
        **fila,
    )


def _sueltas(db: Session, tipos=("sell_in", "sell_out")) -> list[tuple[str, int]]:
    return [(c["origen"], c["id"]) for c in service.cargas_pendientes(db, list(tipos))]


class TestCargasSueltas:
    def test_the_pending_loads_of_no_tactical_are_listed_newest_first(self, db, engine) -> None:
        bono = bw.bono(engine, estado="pendiente")
        compra = _compra_suelta(engine)
        campana = _campana_suelta(engine, "Campaña suelta")

        assert _sueltas(db) == [("sell_out_campana", campana), ("sell_in_compra", compra), ("sell_in_bono", bono)]
        [c, k, b] = service.cargas_pendientes(db, ["sell_in", "sell_out"])
        assert (c["nombre"], c["moneda"], c["fecha_desde"], c["fecha_hasta"]) == (
            "Campaña suelta", "ARS", date(2026, 11, 1), date(2026, 11, 30),
        )  # fmt: skip
        assert (k["nombre"], k["fecha_desde"], k["fecha_hasta"]) == ("NC Epson", date(2026, 11, 5), date(2026, 11, 5))
        assert (b["nombre"], b["marca"], b["moneda"]) == (f"Bono {bw.TPLINK}", bw.TPLINK, "USD")
        assert {x["usuario_id"] for x in (c, k, b)} == {USUARIO}

    def test_approved_voided_derived_and_tactical_rows_are_not_listed(self, db, engine) -> None:
        activo = bw.bono(engine)
        bw.bono(engine, estado="anulada")
        _campana_suelta(engine, "Aprobada", estado="activa")
        _compra_suelta(engine, bono_id=activo)  # a bonus's purchase follows its bonus: not a load
        service.crear(db, _tactical(), USUARIO)  # its line is approved with the tactical, from its row

        assert _sueltas(db) == []

    def test_only_the_kinds_the_caller_may_read(self, db, engine) -> None:
        bono = bw.bono(engine, estado="pendiente")
        campana = _campana_suelta(engine, "Suelta")

        assert _sueltas(db, ["sell_in"]) == [("sell_in_bono", bono)]
        assert _sueltas(db, ["sell_out"]) == [("sell_out_campana", campana)]
        assert _sueltas(db, []) == []


class TestOffsetsSueltos:
    """S10 + S11: a legacy profit offset waiting for approval is a sell out load of its own in the inbox."""

    def test_a_pending_offset_is_listed_with_the_sell_out_loads(self, db, engine) -> None:
        _offset(engine, estado="activa")  # approved (every offset loaded before approval existed): not listed
        offset = _offset(engine)
        sin_fin = _offset(engine, marca=None, descripcion="Rebate Q4", moneda=None, fecha_hasta=None)

        assert _sueltas(db, ["sell_out"]) == [("offset_ganancia", sin_fin), ("offset_ganancia", offset)]
        assert _sueltas(db, ["sell_in"]) == []
        [s, o] = service.cargas_pendientes(db, ["sell_out"])
        assert (o["nombre"], o["marca"], o["moneda"], o["fecha_desde"], o["fecha_hasta"], o["usuario_id"]) == (
            "Offset EPSON", "EPSON", "USD", date(2026, 11, 1), date(2026, 12, 31), USUARIO,
        )  # fmt: skip
        assert (s["nombre"], s["marca"], s["moneda"], s["fecha_hasta"]) == ("Rebate Q4", None, "ARS", None)

    def test_the_count_adds_the_pending_offsets(self, db, engine) -> None:
        _offset(engine)
        _offset(engine, estado="activa")
        _campana_suelta(engine, "Suelta")

        filtros = service.Filtros(tipos=["sell_out"])
        assert service.contar_pendientes_aprobacion(db, filtros, hoy=HOY) == 2
        assert service.contar_pendientes_aprobacion(db, service.Filtros(tipos=["sell_in"]), hoy=HOY) == 0


class TestKpisSinPendientes:
    def _kpis(self, db, **filtros) -> dict:
        return service.kpis(db, service.Filtros(tipos=["sell_in", "sell_out"], **filtros), hoy=HOY)

    def test_the_money_kpis_leave_pending_tacticals_out_with_or_without_an_estado_filter(self, db, engine) -> None:
        aprobado = service.crear(db, _tactical(nombre="Aprobado"), USUARIO)
        service.aprobar(db, aprobado.id, APROBADOR)
        pendiente = service.crear(db, _tactical(nombre="Pendiente"), USUARIO)
        _usado(engine, aprobado.id, "50")
        _usado(engine, pendiente.id, "30")  # left over from before it went back to pending

        sin_filtro = self._kpis(db)
        assert (sin_filtro["pendientes"]["cantidad"], sin_filtro["pendientes"]["sin_tope"]) == (1, 1)
        assert [m["monto"] for m in sin_filtro["pendientes"]["montos"]] == [Decimal("50.00")]
        solo_pendientes = self._kpis(db, estado="pendientes_aprobacion")
        assert solo_pendientes["pendientes"] == {"cantidad": 0, "sin_tope": 0, "montos": []}

    def test_a_pending_line_adds_no_money(self, db, engine) -> None:
        aprobado = service.crear(db, _tactical(nombre="Aprobado"), USUARIO)
        service.aprobar(db, aprobado.id, APROBADOR)
        _usado(engine, aprobado.id, "50")
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE sell_out_campanas SET estado = 'pendiente' WHERE tactical_id = {aprobado.id}"))

        assert self._kpis(db)["pendientes"]["montos"] == []

    def test_approved_tacticals_keep_counting_as_before(self, db, engine) -> None:
        a = service.crear(db, _tactical(nombre="A"), USUARIO)
        b = service.crear(db, _tactical(nombre="B", moneda="USD", tc_modo="al_cobro"), USUARIO)
        for t in (a, b):
            service.aprobar(db, t.id, APROBADOR)
        _usado(engine, a.id, "20.5")
        _usado(engine, b.id, "7")

        assert self._kpis(db)["pendientes"] == {
            "cantidad": 2,
            "sin_tope": 2,
            "montos": [
                {"moneda": "ARS", "monto": Decimal("20.50"), "tope": None, "tope_parcial": False, "estimado": False},
                {"moneda": "USD", "monto": Decimal("7.00"), "tope": None, "tope_parcial": False, "estimado": False},
            ],
        }


class TestConteoPendientes:
    def test_it_counts_pending_tacticals_under_the_other_filters_plus_the_standalone_loads(self, db, engine) -> None:
        service.crear(db, _tactical(nombre="Hot sale"), USUARIO)
        service.crear(db, _tactical(nombre="Otro"), USUARIO)
        aprobado = service.crear(db, _tactical(nombre="Hot aprobado"), USUARIO)
        service.aprobar(db, aprobado.id, APROBADOR)
        bw.bono(engine, estado="pendiente")
        _campana_suelta(engine, "Suelta")

        def contar(tipos=("sell_in", "sell_out"), **filtros) -> int:
            return service.contar_pendientes_aprobacion(db, service.Filtros(tipos=list(tipos), **filtros), hoy=HOY)

        assert contar() == 4  # two tacticals, one bonus, one campaign
        assert contar(estado="vigentes") == 4  # the estado filter does not hide what waits for approval
        assert contar(q="hot") == 3  # the other filters narrow the tacticals; the standalone loads always show
        assert contar(tipos=["sell_in"]) == 1  # only the bonus: both tacticals are sell out
