"""Costo SI end to end on Postgres (sell-in-costo-si T2): inputs read from the GBP mirror, Compras, sell ins and
Mercado Libre Full; the history stored with its breakdown; the recompute from a late sell in's date with a backup;
the queue triggers and the `sell.drain` pass. Spec: handoffs/sell-in-costo-si-feature.md S1-S12, S14 (engine only).
Invented data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.costo_si import foto, full_ml, fuentes, queue, recompute
from tests.services.costo_si import _world as w

pytestmark = pytest.mark.postgres

D = Decimal
P, OTRA_MARCA, COMBO, PC = 5101, 5102, 5103, 5104
HOY = date(2026, 11, 20)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("costo_si") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _recalcular(engine: Engine, item_id: int, motivo: str = "test") -> recompute.Resultado:
    with sessionmaker(bind=engine, autoflush=False)() as db:
        resultado = recompute.recalcular(db, item_id, ml=None, hoy=HOY, motivo=motivo)
        db.commit()
    return resultado


def _l1(engine: Engine) -> dict:
    """Alejandro's L1 table as GBP rows: 200 in stock at 25 when the first sell in applies (11-02); A 100 at 22 with
    2.5 %; a sale of 20; B 50 at 20 with 5 %; C 50 at 21 with 2 %. Each invoice enters the day it is dated."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 10, 15, 9, 0), "25")
    a = w.factura(engine, P, date(2026, 11, 2), datetime(2026, 11, 2, 10), 100, "22", previo=200, pedido=1)
    w.movimiento(engine, P, datetime(2026, 11, 2, 15), 20, previo=300)
    b = w.factura(engine, P, date(2026, 11, 3), datetime(2026, 11, 3, 10), 50, "20", previo=280, pedido=2)
    c = w.factura(engine, P, date(2026, 11, 4), datetime(2026, 11, 4, 10), 50, "21", previo=330, pedido=3)
    w.sell_in_compra(engine, P, 1, "2.5", date(2026, 11, 2))
    w.sell_in_compra(engine, P, 2, "5", date(2026, 11, 3))
    w.sell_in_compra(engine, P, 3, "2", date(2026, 11, 4))
    w.run(engine, "DELETE FROM costo_si_dirty")
    return {"a": a, "b": b, "c": c}


def test_alejandros_l1_table_comes_out_of_the_gbp_rows_exactly(engine: Engine) -> None:
    """S1 + S2: the start is the first sell in's date, at the list cost in force; then the three purchases."""
    _l1(engine)

    _recalcular(engine, P)

    assert w.pasos(engine, P) == [
        ("inicio", date(2026, 11, 2), 200, 200, D("25.00000"), D("25.00000")),
        ("compra", date(2026, 11, 2), 100, 200, D("21.45000"), D("23.81667")),
        ("compra", date(2026, 11, 3), 50, 280, D("19.00000"), D("23.08687")),
        ("compra", date(2026, 11, 4), 50, 330, D("20.58000"), D("22.75702")),
    ]


def test_the_start_cost_skips_a_same_day_typo_and_ignores_the_ppp(engine: Engine) -> None:
    """S2 (L2.1): the real list cost in force at 00:00 of the start day; a typo corrected minutes later never counts."""
    _l1(engine)
    w.costo_lista(engine, P, datetime(2026, 10, 20, 15, 24), "2632")
    w.costo_lista(engine, P, datetime(2026, 10, 20, 15, 26), "26")

    _recalcular(engine, P)

    assert w.pasos(engine, P)[0][-1] == D("26.00000")


def test_loyalty_is_a_sell_in_on_every_invoice_of_the_brand_from_any_supplier(engine: Engine) -> None:
    """S5 + S6 + S7: loyalty 3.6 % reaches an invoice linked to Compras with a 5 % supplier sell in (100 -> 91.40) and
    an invoice from another supplier that is not in Compras (100 -> 96.40). Another brand gets nothing."""
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA, marca="OTRA")
    w.costo_lista(engine, P, datetime(2026, 9, 1), "100")
    w.costo_lista(engine, OTRA_MARCA, datetime(2026, 9, 1), "100")
    w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 12, 31))
    w.factura(engine, P, date(2026, 10, 5), datetime(2026, 10, 6), 10, "100", previo=0, supp_id=14, pedido=9)
    w.sell_in_compra(engine, P, 9, "5", date(2026, 10, 5))
    w.factura(engine, P, date(2026, 10, 8), datetime(2026, 10, 9), 10, "100", previo=10, supp_id=19)
    w.factura(engine, OTRA_MARCA, date(2026, 10, 8), datetime(2026, 10, 9), 10, "100", previo=0)

    _recalcular(engine, P)
    _recalcular(engine, OTRA_MARCA)

    netos = w.rows(
        engine,
        "SELECT costo_neto_neto_usd, sell_in_pct, en_compras, sell_ins FROM costo_si_pasos "
        "WHERE item_id = :i AND tipo = 'compra' ORDER BY orden",
        i=P,
    )
    assert [(n[0], n[1], n[2]) for n in netos] == [(D("91.40000"), D("8.6"), True), (D("96.40000"), D("3.6"), False)]
    assert [s["origen"] for s in netos[0][3]] == ["compra", "bono"]
    assert w.pasos(engine, P)[0][1] == date(2026, 10, 1)  # the bonus's fecha_desde is the first sell-in date
    assert w.pasos(engine, OTRA_MARCA) == []  # no sell in ever applied to it: no costo SI


def test_fx_is_the_pm_correction_then_the_compras_tc_then_the_invoice_date(engine: Engine) -> None:
    """S4 (L4.5): ARS invoices in USD."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "10")
    w.bono_marca(engine, "1", date(2026, 10, 1), date(2026, 12, 31))
    w.tipo_cambio(engine, date(2026, 10, 4), 1500)
    w.factura(
        engine, P, date(2026, 10, 5), datetime(2026, 10, 5), 1, "16000", previo=0, curr_id=1, pedido=4, tc_pedido="1600"
    )
    sin_pedido = w.factura(engine, P, date(2026, 10, 6), datetime(2026, 10, 6), 1, "15000", previo=1, curr_id=1)
    corregida = w.factura(engine, P, date(2026, 10, 7), datetime(2026, 10, 7), 1, "15500", previo=2, curr_id=1)
    w.run(engine, "INSERT INTO costo_si_factura_tc (ct_transaction, tipo_cambio) VALUES (:c, 1550)", c=corregida)

    _recalcular(engine, P)

    assert w.rows(
        engine,
        "SELECT ct_transaction, costo_neto_usd, tipo_cambio, fuente_tc FROM costo_si_pasos "
        "WHERE item_id = :i AND tipo = 'compra' ORDER BY orden",
        i=P,
    )[1:] == [
        (sin_pedido, D("10.00000"), D("1500"), "fecha_factura"),
        (corregida, D("10.00000"), D("1550"), "manual"),
    ]
    assert w.rows(
        engine, "SELECT costo_neto_usd, fuente_tc FROM costo_si_pasos WHERE item_id = :i AND orden = 1", i=P
    ) == [(D("10.00000"), "pedido")]


def test_negative_stock_at_a_purchase_restarts_the_average(engine: Engine) -> None:
    """S9 (L4.6): the depot was at -3 when the invoice came: the old stock does not exist."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "30")
    w.bono_marca(engine, "10", date(2026, 10, 1), date(2026, 12, 31))
    w.movimiento(engine, P, datetime(2026, 10, 1, 9), 5, previo=2)
    w.factura(engine, P, date(2026, 10, 3), datetime(2026, 10, 3, 9), 40, "20", previo=-3)

    _recalcular(engine, P)

    assert w.pasos(engine, P) == [
        ("inicio", date(2026, 10, 1), 2, 2, D("30.00000"), D("30.00000")),
        ("compra", date(2026, 10, 3), 40, -3, D("18.00000"), D("18.00000")),
    ]


def test_principal_is_available_stock_not_physical(engine: Engine) -> None:
    """S3 (L4.1): physical 100 minus an order generated before the instant and invoiced after it (7) and an open order
    (5); a pending transfer to Full (customer 2849) does not reduce it; an order generated after it does not either."""
    w.producto(engine, P)
    t = datetime(2026, 10, 10)
    w.run(
        engine,
        "INSERT INTO tb_sale_order_header_history (comp_id, bra_id, soh_id, sohh_id, soh_cd, sohh_cd, cust_id) VALUES "
        "(1, 1, 41, 1, :c, :c, 10), (1, 1, 42, 2, :late, :late, 10)",
        c=datetime(2026, 10, 8),
        late=datetime(2026, 10, 11),
    )
    w.movimiento(engine, P, datetime(2026, 10, 12), 7, previo=100, soh_id=41)  # invoiced after t, ordered before
    w.movimiento(engine, P, datetime(2026, 10, 12, 1), 4, previo=93, soh_id=42)  # ordered after t
    w.run(
        engine,
        "INSERT INTO tb_sale_order_header (comp_id, bra_id, soh_id, soh_cd, soh_statusof, cust_id) VALUES "
        "(1, 1, 43, :c, NULL, 10), (1, 1, 44, :c, NULL, 2849)",
        c=datetime(2026, 10, 9),
    )
    w.run(
        engine,
        "INSERT INTO tb_sale_order_detail (comp_id, bra_id, soh_id, sod_id, item_id, sod_qty, stor_id) VALUES "
        "(1, 1, 43, 1, :i, 5, 1), (1, 1, 43, 2, :i, 5, 1), (1, 1, 44, 3, :i, 200, 1)",
        i=P,
    )  # a stale duplicate line

    with sessionmaker(bind=engine)() as db:
        assert fuentes.principal_disponible(db, P, t) == 100 - 7 - 5


def test_full_is_mercado_libres_stock_walked_back_never_gbp_depot_17(engine: Engine) -> None:
    """S3 (owner L8): Full today 30 at ML; 4 sold at Full after the instant (sale confirmation), 10 received before it.
    GBP depot 17 says 500 and is ignored."""
    w.producto(engine, P)
    w.publicacion_full(engine, "MLA1", P, "INV1", full_hoy=30)
    w.operacion_full(engine, "INV1", datetime(2026, 10, 9, 12, tzinfo=UTC), "INBOUND_RECEPTION", 10, 34)
    w.operacion_full(engine, "INV1", datetime(2026, 10, 15, 12, tzinfo=UTC), "SALE_CONFIRMATION", -4, 30)
    w.movimiento(engine, P, datetime(2026, 10, 20), 1, previo=500, stor_id=17)
    instante = datetime(2026, 10, 10, tzinfo=fuentes.ZONA)

    with sessionmaker(bind=engine)() as db:
        assert full_ml.full_disponible(db, P, instante) == 34
        assert full_ml.full_disponible(db, P, datetime(2026, 10, 1, tzinfo=fuentes.ZONA)) == 24
        assert full_ml.full_disponible(db, P, datetime(2026, 11, 1, tzinfo=fuentes.ZONA)) == 30
        assert fuentes.disponible(db, P, date(2026, 10, 10)) == 34  # principal 0 (no depot 1 rows) + Full


class _Ml:
    """ML's operations search, answered from a list; records every call."""

    def __init__(self, ops: list, status: int = 200) -> None:
        self.ops, self.status, self.calls = ops, status, []

    def get(self, family, path, params=None):
        self.calls.append(dict(params))
        desde, hasta = date.fromisoformat(params["date_from"]), date.fromisoformat(params["date_to"])
        found = [o for o in self.ops if desde <= date.fromisoformat(o["date_created"][:10]) < hasta]
        return type("R", (), {"status": self.status, "body": {"paging": {"scroll": None}, "results": found}})()


def test_full_operations_are_fetched_once_in_windows_of_60_days(engine: Engine) -> None:
    w.producto(engine, P)
    w.publicacion_full(engine, "MLA1", P, "INV1", full_hoy=30)
    ml = _Ml(
        [
            {
                "id": 1,
                "date_created": "2026-10-15T12:00:00Z",
                "type": "SALE_CONFIRMATION",
                "detail": {"available_quantity": -4},
                "result": {"available_quantity": 30},
            }
        ]
    )

    with sessionmaker(bind=engine)() as db:
        assert full_ml.sincronizar(db, ml, P, date(2026, 8, 1), HOY) == 1
        db.commit()
        assert [(c["date_from"], c["date_to"]) for c in ml.calls] == [
            ("2026-08-01", "2026-09-30"),
            ("2026-09-30", "2026-11-21"),
        ]
        ml.calls.clear()
        assert full_ml.sincronizar(db, ml, P, date(2026, 8, 1), HOY) == 0  # kept: only the last day again
        assert [(c["date_from"], c["date_to"]) for c in ml.calls] == [("2026-11-20", "2026-11-21")]
    assert w.rows(engine, "SELECT delta, disponible FROM costo_si_full_operaciones") == [(-4, 30)]


def test_an_ml_failure_stops_the_recompute_instead_of_guessing_full(engine: Engine) -> None:
    w.producto(engine, P)
    w.publicacion_full(engine, "MLA1", P, "INV1", full_hoy=30)
    w.bono_marca(engine, "1", date(2026, 10, 1), date(2026, 12, 31))

    with sessionmaker(bind=engine)() as db, pytest.raises(full_ml.FullNoDisponible):
        recompute.recalcular(db, P, ml=_Ml([], status=429), hoy=HOY)


def test_combos_never_add_their_stock_to_the_components_and_have_no_history(engine: Engine) -> None:
    """S11 (L7.1): "No tenés que sumar stock del combo x cantidad": the combo's own Full publication (10 x 2 units)
    stays out of the component's stock; the combo gets no costo SI rows of its own; a PC is its own product."""
    w.producto(engine, P)
    w.producto(engine, COMBO)
    w.producto(engine, PC, cat_id=47)
    w.run(
        engine,
        "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :p, 2), (:pc, :p, 1)",
        c=COMBO,
        p=P,
        pc=PC,
    )
    w.costo_lista(engine, P, datetime(2026, 9, 1), "10")
    w.costo_lista(engine, PC, datetime(2026, 9, 1), "300")
    w.bono_marca(engine, "1", date(2026, 10, 1), date(2026, 12, 31))
    w.movimiento(engine, P, datetime(2026, 10, 2), 1, previo=50)
    w.publicacion_full(engine, "MLA-COMBO", COMBO, "INV-COMBO", full_hoy=10)

    for item in (P, COMBO, PC):
        _recalcular(engine, item)

    assert w.pasos(engine, P)[0][2] == 50
    assert w.pasos(engine, COMBO) == []
    assert w.pasos(engine, PC)[0][-1] == D("300.00000")


def test_a_late_sell_in_recomputes_from_its_date_and_backs_up_what_it_replaces(engine: Engine) -> None:
    """S8 (L2.4 / L2.5): a sell in loaded today for invoice B (11-03) queues the product from its date; the drain
    rewrites B and C and keeps the start and A exactly as they were; the replaced rows are in the backup first."""
    _l1(engine)
    w.run(
        engine,
        "DELETE FROM sell_in_compras WHERE id IN (SELECT compra_id FROM sell_in_compra_pedidos "
        "WHERE pedido_compra_id = 2)",
    )
    _recalcular(engine, P)
    antes = w.rows(
        engine,
        "SELECT id, orden, calculado_at, promedio_usd FROM costo_si_pasos WHERE item_id = :i ORDER BY orden",
        i=P,
    )
    w.run(engine, "DELETE FROM costo_si_dirty")

    w.sell_in_compra(engine, P, 2, "5", date(2026, 11, 3))

    assert w.encolados(engine) == [(P, date(2026, 11, 3))]
    drenado = queue.drenar(
        sessionmaker(bind=engine, autoflush=False),
        datetime.now(UTC) + timedelta(minutes=1),
        HOY,
        ml=None,
        is_transient=lambda exc: False,
    )
    assert (drenado.productos, drenado.cambiados, drenado.fallidos) == (1, 1, {})
    despues = w.rows(
        engine,
        "SELECT id, orden, calculado_at, promedio_usd FROM costo_si_pasos WHERE item_id = :i ORDER BY orden",
        i=P,
    )
    assert despues[:2] == antes[:2]  # untouched: same rows, same timestamps
    assert [r[3] for r in despues] == [D("25.00000"), D("23.81667"), D("23.08687"), D("22.75702")]
    (backup,) = w.rows(engine, "SELECT item_id, desde, motivo, pasos FROM costo_si_backups")
    assert backup[:3] == (P, date(2026, 11, 3), "recalculo desde 2026-11-03")
    assert [(p["orden"], p["promedio_usd"]) for p in backup[3]] == [(2, str(antes[2][3])), (3, str(antes[3][3]))]
    assert w.encolados(engine) == []


def test_a_recompute_with_nothing_changed_writes_nothing(engine: Engine) -> None:
    _l1(engine)
    _recalcular(engine, P)

    assert _recalcular(engine, P).desde is None
    assert w.rows(engine, "SELECT count(*) FROM costo_si_backups") == [(0,)]


def test_triggers_queue_the_products_a_change_touches_from_its_date(engine: Engine) -> None:
    """S8: a brand bonus queues every product of its brand from fecha_desde; linking an invoice to Compras queues
    its products from the invoice date; a PM FX correction too."""
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA, marca="OTRA")
    ct = w.factura(engine, OTRA_MARCA, date(2026, 10, 7), datetime(2026, 10, 8), 3, "5", previo=0)

    w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 12, 31))
    assert w.encolados(engine) == [(P, date(2026, 10, 1))]

    w.run(engine, "INSERT INTO pedidos_compra (id) VALUES (77)")
    w.run(engine, "INSERT INTO pedido_compra_facturas (pedido_id, ct_transaction_id) VALUES (77, :c)", c=ct)
    assert w.encolados(engine) == [(P, date(2026, 10, 1)), (OTRA_MARCA, date(2026, 10, 7))]

    w.run(engine, "DELETE FROM costo_si_dirty")
    w.run(engine, "INSERT INTO costo_si_factura_tc (ct_transaction, tipo_cambio) VALUES (:c, 1500)", c=ct)
    assert w.encolados(engine) == [(OTRA_MARCA, date(2026, 10, 7))]


def test_a_failing_product_is_charged_and_the_rest_drain(engine: Engine) -> None:
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA)
    w.bono_marca(engine, "1", date(2026, 10, 1), date(2026, 12, 31))
    w.factura(engine, P, date(2026, 10, 5), datetime(2026, 10, 5), 1, "16000", previo=0, curr_id=1)  # no FX at all

    drenado = queue.drenar(
        sessionmaker(bind=engine, autoflush=False),
        datetime.now(UTC) + timedelta(minutes=1),
        HOY,
        ml=None,
        is_transient=lambda exc: False,
    )

    assert list(drenado.fallidos) == [P]
    assert w.rows(engine, "SELECT item_id, attempts FROM costo_si_dirty") == [(P, 1)]
    assert len(w.pasos(engine, OTRA_MARCA)) == 1


def test_the_daily_photo_is_read_instead_of_the_reconstruction(engine: Engine) -> None:
    """S3 decision: from now on a daily photo of available stock (principal + Full)."""
    _l1(engine)
    _recalcular(engine, P)
    w.publicacion_full(engine, "MLA1", P, "INV1", full_hoy=6)

    with sessionmaker(bind=engine)() as db:
        assert foto.tomar(db, date(2026, 11, 3), datetime(2026, 11, 20, 9, tzinfo=UTC)) == 1
        db.commit()
        # 00:00 of 11-03, the instant it stands for: 200 + A's 100 - the sale of 20; B entered later that day
        assert w.rows(engine, 'SELECT principal, "full" FROM costo_si_stock_diario') == [(280, 6)]
        w.movimiento(engine, P, datetime(2026, 11, 2, 18), 5, previo=280)  # a late mirror rewrite of a closed day
        assert fuentes.disponible(db, P, date(2026, 11, 3)) == 286  # the photo, not the reconstruction


def test_encolar_vigentes_queues_every_product_with_a_sell_in_or_a_costo_si(engine: Engine) -> None:
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA, marca="OTRA")
    w.bono_marca(engine, "1", date(2026, 10, 1), date(2026, 12, 31))
    w.run(engine, "DELETE FROM costo_si_dirty")

    with sessionmaker(bind=engine)() as db:
        assert queue.encolar_vigentes(db) == 1
        db.commit()
    assert w.encolados(engine) == [(P, None)]


def test_the_daily_sync_fetches_each_products_full_from_its_start_and_skips_ml_failures(engine: Engine) -> None:
    """S3 (L8): `stock.snapshot` (the ML worker) keeps every product's Full operations from its first sell-in date;
    one product ML fails for does not stop the others."""
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA)
    w.bono_marca(engine, "1", date(2026, 10, 1), date(2026, 12, 31))
    w.publicacion_full(engine, "MLA1", P, "INV1", full_hoy=30)
    w.publicacion_full(engine, "MLA2", OTRA_MARCA, "INV2", full_hoy=5)

    class Mixto(_Ml):
        def get(self, family, path, params=None):
            if params["inventory_id"] == "INV2":
                return type("R", (), {"status": 500, "body": None})()
            return super().get(family, path, params)

    ml = Mixto(
        [
            {
                "id": 7,
                "date_created": "2026-10-15T12:00:00Z",
                "type": "SALE_CONFIRMATION",
                "detail": {"available_quantity": -1},
                "result": {"available_quantity": 30},
            }
        ]
    )
    guardadas, fallidos = full_ml.sincronizar_productos(
        sessionmaker(bind=engine), ml, [P, OTRA_MARCA], HOY, datetime.now(UTC) + timedelta(minutes=1), fuentes.inicio_de
    )

    assert (guardadas, list(fallidos)) == (1, [OTRA_MARCA])
    assert [c["date_from"] for c in ml.calls if c["inventory_id"] == "INV1"][0] == "2026-10-01"  # its start
    assert w.rows(engine, "SELECT inventory_id, desde, hasta FROM costo_si_full_cobertura") == [
        ("INV1", date(2026, 10, 1), date(2026, 11, 21))
    ]


def test_sell_drain_waits_for_the_full_operations_instead_of_guessing_them(engine: Engine) -> None:
    """S3 (L8), verifier B1: a loyalty loaded during the day queues a product with a Full publication before
    `stock.snapshot` fetched its operations. The drain stores nothing and charges nothing (today's Full is not the
    Full of 10-01); once the operations are kept from its start through today, it recomputes."""
    w.producto(engine, P)
    w.publicacion_full(engine, "MLA9", P, "INV9", full_hoy=30)
    w.costo_lista(engine, P, datetime(2026, 9, 15, 9), "25")
    w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 12, 31))

    def drenar() -> queue.Drenado:
        return queue.drenar(
            sessionmaker(bind=engine, autoflush=False),
            datetime.now(UTC) + timedelta(minutes=1),
            HOY,
            ml=None,
            is_transient=lambda exc: False,
        )

    drenado = drenar()
    assert (drenado.productos, drenado.fallidos, drenado.diferidos) == (0, {}, {P})
    assert w.pasos(engine, P) == []
    assert w.rows(engine, "SELECT item_id, attempts FROM costo_si_dirty") == [(P, 0)]

    w.run(  # kept, but only from 10-05: still a guess for 10-01
        engine,
        "INSERT INTO costo_si_full_cobertura (inventory_id, desde, hasta) VALUES ('INV9', :d, :h)",
        d=date(2026, 10, 5),
        h=HOY + timedelta(days=1),
    )
    assert drenar().diferidos == {P}

    w.run(engine, "UPDATE costo_si_full_cobertura SET desde = :d", d=date(2026, 10, 1))
    drenado = drenar()
    assert (drenado.productos, drenado.diferidos) == (1, set())
    assert w.pasos(engine, P)[0][2] == 30  # nothing moved at Full since: today's 30 is the stock of 10-01
    assert w.encolados(engine) == []


def test_an_invoice_whose_goods_entered_before_its_date_is_not_counted_twice(engine: Engine) -> None:
    """S3 (T1 §2), verifier note 1: dated 11-03, entered depot 1 on 11-02; the stock before it is 0, not its own 100."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 10, 15, 9), "25")
    w.bono_marca(engine, "1", date(2026, 11, 1), date(2026, 12, 31))
    w.factura(engine, P, date(2026, 11, 3), datetime(2026, 11, 2, 10), 100, "20", previo=0)

    _recalcular(engine, P)

    assert w.pasos(engine, P)[1] == ("compra", date(2026, 11, 3), 100, 0, D("19.80000"), D("19.80000"))


def test_a_product_whose_daily_sync_breaks_does_not_stop_the_others(engine: Engine) -> None:
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA)
    w.bono_marca(engine, "1", date(2026, 10, 1), date(2026, 12, 31))
    w.publicacion_full(engine, "MLA2", OTRA_MARCA, "INV2", full_hoy=5)

    def inicio_de(db, item_id):
        if item_id == P:
            raise RuntimeError("broken")
        return fuentes.inicio_de(db, item_id)

    guardadas, fallidos = full_ml.sincronizar_productos(
        sessionmaker(bind=engine), _Ml([]), [P, OTRA_MARCA], HOY, datetime.now(UTC) + timedelta(minutes=1), inicio_de
    )

    assert (guardadas, fallidos) == (0, {P: "RuntimeError: broken"})
    assert w.rows(engine, "SELECT inventory_id FROM costo_si_full_cobertura") == [("INV2",)]


def test_a_photo_cut_by_the_deadline_keeps_the_rest_of_the_days_photo(engine: Engine) -> None:
    _l1(engine)
    _recalcular(engine, P)
    w.run(
        engine,
        'INSERT INTO costo_si_stock_diario (fecha, item_id, principal, "full", tomado_at) VALUES (:f, :i, 7, 0, now())',
        f=date(2026, 11, 3),
        i=P,
    )

    with sessionmaker(bind=engine)() as db:
        assert foto.tomar(db, date(2026, 11, 3), datetime.now(UTC), datetime.now(UTC) - timedelta(seconds=1)) == 0
        db.commit()

    assert w.rows(engine, "SELECT principal FROM costo_si_stock_diario") == [(7,)]


def test_the_daily_sync_starts_with_the_products_synced_least_recently(engine: Engine) -> None:
    """A run cut by its deadline reaches next day the products it left out: never synced first, then the oldest."""
    for item, inv in ((P, "INV1"), (OTRA_MARCA, "INV2"), (COMBO, "INV3")):
        w.producto(engine, item)
        w.publicacion_full(engine, f"MLA-{inv}", item, inv, full_hoy=1)
    w.run(
        engine,
        "INSERT INTO costo_si_full_cobertura (inventory_id, desde, hasta) VALUES ('INV1', :d, :h1), ('INV2', :d, :h2)",
        d=date(2026, 10, 1),
        h1=HOY + timedelta(days=1),
        h2=HOY - timedelta(days=3),
    )

    with sessionmaker(bind=engine)() as db:
        assert full_ml.por_antiguedad(db, [P, OTRA_MARCA, COMBO, PC]) == [COMBO, OTRA_MARCA, P, PC]


def test_a_credit_note_linked_to_compras_never_moves_the_start(engine: Engine) -> None:
    """S2 + S4: only invoices that enter the average date the first sell in; a linked credit note of 10-02 does not."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "25")
    nc = w.factura(engine, P, date(2026, 10, 2), datetime(2026, 10, 2), 1, "22", previo=10, pedido=5)
    w.run(
        engine, "UPDATE v_facturas_compra_vigentes SET clasificacion = 'NOTA_CREDITO' WHERE ct_transaction = :c", c=nc
    )
    w.factura(engine, P, date(2026, 10, 9), datetime(2026, 10, 9), 5, "22", previo=9, pedido=6)
    w.sell_in_compra(engine, P, 5, "2", date(2026, 10, 2))
    w.sell_in_compra(engine, P, 6, "2", date(2026, 10, 9))

    _recalcular(engine, P)

    assert [p[1] for p in w.pasos(engine, P)] == [date(2026, 10, 9), date(2026, 10, 9)]


def test_moving_a_compras_link_queues_the_products_of_both_sell_ins(engine: Engine) -> None:
    """S8: an UPDATE of `sell_in_compra_pedidos` re-dates the sell in it leaves and the one it joins."""
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA, marca="OTRA")
    w.run(engine, "INSERT INTO pedidos_compra (id) VALUES (1), (2)")
    w.sell_in_compra(engine, P, 1, "2", date(2026, 10, 3))
    destino = w.sell_in_compra(engine, OTRA_MARCA, 2, "2", date(2026, 10, 9))
    w.run(engine, "DELETE FROM costo_si_dirty")

    w.run(engine, "UPDATE sell_in_compra_pedidos SET compra_id = :d WHERE pedido_compra_id = 1", d=destino)

    assert w.encolados(engine) == [(P, date(2026, 10, 3)), (OTRA_MARCA, date(2026, 10, 9))]


def test_a_compras_tc_edit_queues_the_products_of_its_invoices_from_their_date(engine: Engine) -> None:
    """S4: the pedido TC (manual first) is an invoice's FX; editing it re-dates the invoice. The same value is no
    change."""
    w.producto(engine, P)
    w.factura(
        engine, P, date(2026, 10, 7), datetime(2026, 10, 7), 1, "15000", previo=0, curr_id=1, pedido=4, tc_pedido="1500"
    )
    w.run(engine, "DELETE FROM costo_si_dirty")

    w.run(engine, "UPDATE pedidos_compra SET tipo_cambio = 1500 WHERE id = 4")
    assert w.encolados(engine) == []

    w.run(engine, "UPDATE pedidos_compra SET tipo_cambio_manual = 1550 WHERE id = 4")
    assert w.encolados(engine) == [(P, date(2026, 10, 7))]

    w.run(engine, "DELETE FROM costo_si_dirty")
    w.run(engine, "UPDATE pedidos_compra SET tipo_cambio = 1520 WHERE id = 4")
    assert w.encolados(engine) == [(P, date(2026, 10, 7))]


def test_a_brand_or_category_change_queues_the_product_for_its_whole_history(engine: Engine) -> None:
    """S6: loyalty reaches a product by its brand (and category); any other product edit is no change."""
    w.producto(engine, P)
    w.run(engine, "DELETE FROM costo_si_dirty")

    w.run(engine, "UPDATE productos_erp SET subcategoria_id = 99 WHERE item_id = :i", i=P)
    w.run(engine, "UPDATE productos_erp SET marca = marca, categoria = categoria WHERE item_id = :i", i=P)
    assert w.encolados(engine) == []  # the sync rewriting the same brand is no change

    w.run(engine, "UPDATE productos_erp SET marca = 'OTRA' WHERE item_id = :i", i=P)
    assert w.encolados(engine) == [(P, None)]

    w.run(engine, "DELETE FROM costo_si_dirty")
    w.run(engine, "UPDATE productos_erp SET categoria = 'OTRA' WHERE item_id = :i", i=P)
    assert w.encolados(engine) == [(P, None)]


@pytest.mark.parametrize("monedas", [(3,), (1, 2)], ids=["unknown", "mixed"])
def test_an_invoice_in_an_unknown_or_mixed_currency_reports_the_product(engine: Engine, monedas: tuple) -> None:
    """S4: only USD and ARS are converted; anything else is reported and the product skipped, never treated as
    ARS."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "10")
    w.bono_marca(engine, "1", date(2026, 10, 1), date(2026, 12, 31))
    w.tipo_cambio(engine, date(2026, 10, 4), 1500)
    ct = w.factura(engine, P, date(2026, 10, 5), datetime(2026, 10, 5), 2, "16000", previo=0, curr_id=monedas[0])
    if len(monedas) > 1:
        w.run(
            engine,
            "INSERT INTO tb_item_transactions (it_transaction, ct_transaction, item_id, it_qty, it_price, "
            "curr_id, stor_id, it_cd) SELECT max(it_transaction) + 1, :ct, :i, 1, 10, :c, 1, :cd "
            "FROM tb_item_transactions",
            ct=ct,
            i=P,
            c=monedas[1],
            cd=datetime(2026, 10, 5),
        )

    drenado = queue.drenar(
        sessionmaker(bind=engine, autoflush=False),
        datetime.now(UTC) + timedelta(minutes=1),
        HOY,
        ml=None,
        is_transient=lambda exc: False,
    )

    assert list(drenado.fallidos) == [P]
    assert drenado.fallidos[P].startswith("MonedaNoSoportada")
    assert w.pasos(engine, P) == []


def test_a_supplier_credit_note_never_enters_the_cost(engine: Engine) -> None:
    """L10: "los descuentos van por sell in": a supplier NC (with or without goods returned) changes nothing."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "25")
    w.factura(engine, P, date(2026, 10, 9), datetime(2026, 10, 9), 10, "100", previo=0, pedido=6)
    w.sell_in_compra(engine, P, 6, "2", date(2026, 10, 9))
    _recalcular(engine, P)
    sin_nc = w.pasos(engine, P)

    for qty in (10, 0):  # a return of goods, then a value-only credit
        nc = w.factura(engine, P, date(2026, 10, 20), datetime(2026, 10, 20), qty, "5", previo=10)
        w.run(engine, "UPDATE v_facturas_compra_vigentes SET clasificacion = 'NC' WHERE ct_transaction = :c", c=nc)
    _recalcular(engine, P)

    assert w.pasos(engine, P) == sin_nc
