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
        resultado = recompute.recalcular(db, item_id, motivo=motivo)
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


@pytest.mark.parametrize("lista", ["0", "-1"])
def test_a_zero_or_negative_start_list_cost_is_unknown_never_a_zero_cost(engine: Engine, lista: str) -> None:
    """S2 (T4 dry-run, items 4576, 4745-4751): a list row <= 0 is no cost, like the reader: the start is unknown and
    the first purchase starts the average at its own net-net instead of averaging it with 0."""
    _l1(engine)
    w.costo_lista(engine, P, datetime(2026, 10, 20, 9, 0), lista)

    _recalcular(engine, P)

    pasos = w.pasos(engine, P)
    assert pasos[0] == ("inicio", date(2026, 11, 2), 200, 200, None, None)
    assert pasos[1][-1] == D("21.45000")


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
    # no sell in ever applied to it: L21's start (11-01, list cost 100, the 10 in stock), no discount
    assert w.pasos(engine, OTRA_MARCA) == [("inicio", date(2026, 11, 1), 10, 10, D("100.00000"), D("100.00000"))]


def test_a_loyalty_loaded_through_a_tactical_is_a_sell_in_on_every_invoice_of_the_brand(engine: Engine) -> None:
    """S6 (L5, L7.2: "El loyalty es por marca, aplica a cualquier proveedor"): on prod the TP-Link loyalty is bono 94,
    a line of tactical 38. Being a tactical's line does not take it out of the average: the invoice gets its 3.6 %,
    the product starts on the bonus's date and the daily pass queues it."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "100")
    tactical = w.tactical(engine, date(2026, 10, 1), date(2026, 12, 31))
    w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 12, 31), tactical_id=tactical)
    w.factura(engine, P, date(2026, 10, 8), datetime(2026, 10, 9), 10, "100", previo=0, supp_id=19)
    with sessionmaker(bind=engine)() as db:
        assert queue.productos_vigentes(db) == [P]  # the daily pass reaches it through the bonus alone

    _recalcular(engine, P)

    assert w.pasos(engine, P) == [
        ("inicio", date(2026, 10, 1), 0, 0, D("100.00000"), D("100.00000")),
        ("compra", date(2026, 10, 8), 10, 0, D("96.40000"), D("96.40000")),
    ]


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


def test_full_is_walked_back_from_our_own_ml_stock_sales_and_shipments(engine: Engine) -> None:
    """S3 (owner L8, L11: "tenemos tanto el stock actual de full como las ventas de full de los últimos días"): Full
    today 30 at ML; Full sales after the instant add back (4 on 10-15; a cancelled one and a sale shipped from our own
    depot do not), GBP's remito of 10 units into Full on 10-09 takes them out before it. GBP depot 17's balance (500)
    and its other movements are never read as Full stock."""
    w.producto(engine, P)
    w.publicacion_full(engine, "MLA1", P, "INV1", full_hoy=30)
    w.movimiento(engine, P, datetime(2026, 10, 9, 9), 10, previo=490, sd_id=102, stor_id=17)
    w.venta_ml(engine, "MLA1", datetime(2026, 10, 15, 12, tzinfo=UTC), 4)
    w.venta_ml(engine, "MLA1", datetime(2026, 10, 16, 12, tzinfo=UTC), 2, status="cancelled")
    w.venta_ml(engine, "MLA1", datetime(2026, 10, 17, 12, tzinfo=UTC), 5, logistic_type="self_service")
    w.movimiento(engine, P, datetime(2026, 10, 20), 1, previo=500, stor_id=17)

    with sessionmaker(bind=engine)() as db:
        assert full_ml.full_disponible(db, P, datetime(2026, 10, 10, tzinfo=fuentes.ZONA)) == 34
        assert full_ml.full_disponible(db, P, datetime(2026, 10, 1, tzinfo=fuentes.ZONA)) == 24
        assert full_ml.full_disponible(db, P, datetime(2026, 11, 1, tzinfo=fuentes.ZONA)) == 30
        assert fuentes.disponible(db, P, date(2026, 10, 10)) == 34  # principal 0 (no depot 1 rows) + Full


def test_full_of_a_product_linked_per_variation_is_its_variations_full(engine: Engine) -> None:
    """S3 (L8, L11): a product linked to one variation of a publication with variations (the Auditoría photo counts
    it the same way). Its Full is that variation's user product, 12 today, plus that variation's Full sales after the
    instant (3); the sibling variation, linked to another product, never counts (50 at Full, 5 sold)."""
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA, marca="OTRA")
    w.publicacion_full_variacion(engine, "MLA9", 7, P, full_hoy=12)
    w.publicacion_full_variacion(engine, "MLA9", 8, OTRA_MARCA, full_hoy=50)
    w.venta_ml(engine, "MLA9", datetime(2026, 10, 15, 12, tzinfo=UTC), 3, variation_id=7)
    w.venta_ml(engine, "MLA9", datetime(2026, 10, 15, 12, tzinfo=UTC), 5, variation_id=8)

    with sessionmaker(bind=engine)() as db:
        assert full_ml.full_disponible(db, P, datetime(2026, 10, 10, tzinfo=fuentes.ZONA)) == 15
        assert full_ml.full_disponible(db, P, datetime(2026, 11, 1, tzinfo=fuentes.ZONA)) == 12
        assert full_ml.full_disponible(db, OTRA_MARCA, datetime(2026, 10, 10, tzinfo=fuentes.ZONA)) == 55


def test_full_is_walked_back_from_the_next_daily_photo_not_from_today(engine: Engine) -> None:
    """S3 (L11): ML received 200 units today whose GBP remito is not issued yet (RE200 on 2026-11-20). Walking back
    from today's 230 would put them in every past day; the walk starts at the first daily photo after the instant
    (06:00 local), and from today's stock only after the last photo."""
    w.producto(engine, P)
    w.publicacion_full(engine, "MLA1", P, "INV1", full_hoy=230)
    w.foto_ml(engine, P, date(2026, 11, 18), 69)
    w.foto_ml(engine, P, date(2026, 11, 20), 41)
    w.venta_ml(engine, "MLA1", datetime(2026, 11, 17, 15, tzinfo=UTC), 3)
    w.venta_ml(engine, "MLA1", datetime(2026, 11, 18, 15, tzinfo=UTC), 28)

    with sessionmaker(bind=engine)() as db:
        assert full_ml.full_disponible(db, P, datetime(2026, 11, 17, tzinfo=fuentes.ZONA)) == 72  # 69 + 3
        assert full_ml.full_disponible(db, P, datetime(2026, 11, 18, 7, tzinfo=fuentes.ZONA)) == 69  # 41 + 28
        assert full_ml.full_disponible(db, P, datetime(2026, 11, 20, 12, tzinfo=fuentes.ZONA)) == 230


def test_combos_never_add_their_stock_to_the_components_and_have_no_history(engine: Engine) -> None:
    """S11 (L7.1): "No tenés que sumar stock del combo x cantidad": the combo's own Full publication (10 x 2 units)
    stays out of the component's stock; neither the combo nor the PC gets costo SI rows of its own (L22: a PC is the
    sum of its components, like a combo)."""
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
    assert w.pasos(engine, PC) == []


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


def test_encolar_vigentes_queues_every_product_with_or_without_a_sell_in(engine: Engine) -> None:
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA, marca="OTRA")
    w.bono_marca(engine, "1", date(2026, 10, 1), date(2026, 12, 31))
    w.run(engine, "DELETE FROM costo_si_dirty")

    with sessionmaker(bind=engine)() as db:
        assert queue.encolar_vigentes(db) == 2
        db.commit()
    assert w.encolados(engine) == [(P, None), (OTRA_MARCA, None)]  # L21: a product without sell in too


def test_sell_drain_recomputes_a_full_product_without_any_ml_call(engine: Engine) -> None:
    """S3 (L11), and the follow-up of the T2 validation: a loyalty loaded during the day queues a product with a Full
    publication; the drain recomputes it right away from our own data (nothing at Full moved since 10-01: today's
    30), instead of waiting for Mercado Libre's operations."""
    w.producto(engine, P)
    w.publicacion_full(engine, "MLA9", P, "INV9", full_hoy=30)
    w.costo_lista(engine, P, datetime(2026, 9, 15, 9), "25")
    w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 12, 31))

    drenado = queue.drenar(
        sessionmaker(bind=engine, autoflush=False),
        datetime.now(UTC) + timedelta(minutes=1),
        is_transient=lambda exc: False,
    )

    assert (drenado.productos, drenado.fallidos) == (1, {})
    assert w.pasos(engine, P)[0][2] == 30
    assert w.encolados(engine) == []


def test_an_invoice_whose_goods_entered_before_its_date_is_not_counted_twice(engine: Engine) -> None:
    """S3 (T1 §2), verifier note 1: dated 11-03, entered depot 1 on 11-02; the stock before it is 0, not its own 100."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 10, 15, 9), "25")
    w.bono_marca(engine, "1", date(2026, 11, 1), date(2026, 12, 31))
    w.factura(engine, P, date(2026, 11, 3), datetime(2026, 11, 2, 10), 100, "20", previo=0)

    _recalcular(engine, P)

    assert w.pasos(engine, P)[1] == ("compra", date(2026, 11, 3), 100, 0, D("19.80000"), D("19.80000"))


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


def test_a_credit_note_linked_to_compras_never_moves_the_start(engine: Engine) -> None:
    """S2 + S4: only invoices that enter the average date the first sell in; a linked credit note of 10-02 does not."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "25")
    nc = w.factura(engine, P, date(2026, 10, 2), datetime(2026, 10, 2), 1, "22", previo=10, pedido=5)
    w.run(engine, "UPDATE v_facturas_compra_vigentes SET clasificacion = 'NC' WHERE ct_transaction = :c", c=nc)
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


# ------------------------------------------------------------------------------------------------ L15: every input edit
# Owner L15: "si alguien edita por alguna razón el sell in de cualquier factura o loyalty o lo que fuera, se tienen que
# recalcular todos los costos posteriores y los promedios claramente". Each change queues the products it touches from
# the earliest date it moves (NULL = the whole history); the drain then rebuilds the whole history and rewrites it from
# the first step that differs (`recompute.guardar`), so every later average follows.


def _vaciar_cola(engine: Engine) -> None:
    w.run(engine, "DELETE FROM costo_si_dirty")


def test_every_loyalty_change_queues_its_products_from_the_earliest_date_it_touches(engine: Engine) -> None:
    """L15 + S6: a loyalty created by a tactical, its % edited, its range moved either way, its brand changed (both
    brands' products), voided and deleted."""
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA, marca="OTRA")
    tactical = w.tactical(engine, date(2026, 10, 1), date(2026, 12, 31))

    bono = w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 12, 31), tactical_id=tactical)
    assert w.encolados(engine) == [(P, date(2026, 10, 1))]

    cambios = [
        ("porcentaje = 4", [(P, date(2026, 10, 1))]),
        ("fecha_desde = DATE '2026-09-15'", [(P, date(2026, 9, 15))]),  # moved earlier: from the new date
        ("fecha_desde = DATE '2026-10-10'", [(P, date(2026, 9, 15))]),  # moved later: from the old date
        ("fecha_hasta = DATE '2026-11-30'", [(P, date(2026, 10, 10))]),
        ("marca = 'OTRA'", [(P, date(2026, 10, 10)), (OTRA_MARCA, date(2026, 10, 10))]),
        ("estado = 'anulada'", [(OTRA_MARCA, date(2026, 10, 10))]),
    ]
    for cambio, esperado in cambios:
        _vaciar_cola(engine)
        w.run(engine, f"UPDATE sell_in_bonos_marca SET {cambio} WHERE id = :b", b=bono)
        assert w.encolados(engine) == esperado, cambio

    _vaciar_cola(engine)
    w.run(engine, "DELETE FROM sell_in_bonos_marca WHERE id = :b", b=bono)
    assert w.encolados(engine) == [(OTRA_MARCA, date(2026, 10, 10))]


def test_every_compras_sell_in_change_queues_its_products_from_the_earliest_date_it_touches(engine: Engine) -> None:
    """L15 + S5: an invoice's Compras sell in edited (%, purchase date, voided), its product line removed, the whole
    sell in deleted (whole history: its date is gone with it), and an operation linked to it or unlinked."""
    w.producto(engine, P)
    w.run(engine, "INSERT INTO pedidos_compra (id) VALUES (1), (2)")
    compra = w.sell_in_compra(engine, P, 1, "2", date(2026, 10, 3))
    assert w.encolados(engine) == [(P, date(2026, 10, 3))]

    for cambio, esperado in (
        ("porcentaje = 3", date(2026, 10, 3)),
        ("fecha_compra = DATE '2026-09-20'", date(2026, 9, 20)),
        ("estado = 'anulada'", date(2026, 9, 20)),
    ):
        _vaciar_cola(engine)
        w.run(engine, f"UPDATE sell_in_compras SET {cambio} WHERE id = :c", c=compra)
        assert w.encolados(engine) == [(P, esperado)], cambio

    _vaciar_cola(engine)
    w.run(engine, "INSERT INTO sell_in_compra_pedidos (compra_id, pedido_compra_id) VALUES (:c, 2)", c=compra)
    assert w.encolados(engine) == [(P, date(2026, 9, 20))]
    _vaciar_cola(engine)
    w.run(engine, "DELETE FROM sell_in_compra_pedidos WHERE pedido_compra_id = 2")
    assert w.encolados(engine) == [(P, date(2026, 9, 20))]

    _vaciar_cola(engine)
    w.run(engine, "DELETE FROM sell_in_compra_items WHERE compra_id = :c", c=compra)
    assert w.encolados(engine) == [(P, date(2026, 9, 20))]

    otra = w.sell_in_compra(engine, P, 2, "1", date(2026, 10, 5))
    _vaciar_cola(engine)
    w.run(engine, "DELETE FROM sell_in_compras WHERE id = :c", c=otra)
    assert w.encolados(engine) == [(P, None)]


def test_unlinking_an_invoice_or_editing_its_fx_queues_its_products_from_its_date(engine: Engine) -> None:
    """L15 + S4 / S7: an invoice unlinked from its Compras operation, and a PM FX correction edited or removed."""
    w.producto(engine, P)
    ct = w.factura(engine, P, date(2026, 10, 7), datetime(2026, 10, 8), 3, "5", previo=0)
    w.run(engine, "INSERT INTO pedidos_compra (id) VALUES (77)")
    w.run(engine, "INSERT INTO pedido_compra_facturas (pedido_id, ct_transaction_id) VALUES (77, :c)", c=ct)
    w.run(engine, "INSERT INTO costo_si_factura_tc (ct_transaction, tipo_cambio) VALUES (:c, 1500)", c=ct)

    for sql in (
        "DELETE FROM pedido_compra_facturas WHERE ct_transaction_id = :c",
        "UPDATE costo_si_factura_tc SET tipo_cambio = 1510 WHERE ct_transaction = :c",
        "DELETE FROM costo_si_factura_tc WHERE ct_transaction = :c",
    ):
        _vaciar_cola(engine)
        w.run(engine, sql, c=ct)
        assert w.encolados(engine) == [(P, date(2026, 10, 7))], sql


def test_editing_a_loyalty_recomputes_every_average_from_its_date_on_and_keeps_the_ones_before(engine: Engine) -> None:
    """L15 end to end: Alejandro's L1 product with a 1 % loyalty from 11-03; the PM edits it to 2 %. The drain
    rewrites B (11-03) and C (11-04) and every average after them, backs them up first, and leaves the start and A
    (11-02, before the loyalty) exactly as they were."""
    _l1(engine)
    bono = w.bono_marca(engine, "1", date(2026, 11, 3), date(2026, 12, 31))
    _recalcular(engine, P)
    antes = w.rows(
        engine,
        "SELECT id, calculado_at, costo_neto_neto_usd, promedio_usd FROM costo_si_pasos WHERE item_id = :i "
        "ORDER BY orden",
        i=P,
    )
    _vaciar_cola(engine)

    w.run(engine, "UPDATE sell_in_bonos_marca SET porcentaje = 2 WHERE id = :b", b=bono)
    drenado = queue.drenar(
        sessionmaker(bind=engine, autoflush=False),
        datetime.now(UTC) + timedelta(minutes=1),
        is_transient=lambda exc: False,
    )

    despues = w.rows(
        engine,
        "SELECT id, calculado_at, costo_neto_neto_usd, promedio_usd FROM costo_si_pasos WHERE item_id = :i "
        "ORDER BY orden",
        i=P,
    )
    assert (drenado.productos, drenado.cambiados) == (1, 1)
    assert despues[:2] == antes[:2]  # the start and A: same rows, same timestamps
    assert [r[2] for r in despues[2:]] == [D("18.60000"), D("20.16000")]  # 20 x (1 - 5 % - 2 %), 21 x (1 - 2 % - 2 %)
    assert all(d[3] < a[3] for d, a in zip(despues[2:], antes[2:]))  # every later average goes down
    (backup,) = w.rows(engine, "SELECT desde, pasos FROM costo_si_backups")
    assert backup[0] == date(2026, 11, 3)
    assert [p["orden"] for p in backup[1]] == [2, 3]


# ------------------------------------------------------------------- tactical sell-in lines (orchestrator decision)
# L4.2: "si algo se cargo por sell in, es sell in, no se discute": every sell-in line, % or per unit, lowers the cost
# of the purchases in its scope and range, its topes consumed over the invoices in date order; sell out never does.


def _nn(engine: Engine, item_id: int) -> list:
    """The net-net of each purchase step."""
    return [r[4] for r in w.pasos(engine, item_id) if r[0] == "compra"]


def test_a_capped_percentage_line_covers_only_its_first_units_in_date_order(engine: Engine) -> None:
    """Tactical 41-like: 6 % on one model, tope 15 units. The first invoice (10 u) takes it whole, the second (10 u)
    only on 5 of them, so the cap runs out mid-invoice (6 % x 5 / 10 = 3 %), and the third gets nothing."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "100")
    w.bono_modelos(engine, [P], "porcentaje", "6", date(2026, 10, 1), date(2026, 12, 31), tope_unidades=15)
    for dia in (8, 15, 22):
        w.factura(engine, P, date(2026, 10, dia), datetime(2026, 10, dia), 10, "100", previo=0)

    _recalcular(engine, P)

    assert _nn(engine, P) == [D("94.00000"), D("97.00000"), D("100.00000")]


def test_a_cap_shared_by_several_models_goes_to_whichever_was_invoiced_first(engine: Engine) -> None:
    """The same line over two models: the other model's 10 units invoiced on 10-05 use 10 of the 15, so this
    product's first invoice gets the % on 5 of its 10 units and the next one nothing."""
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA, marca="OTRA")
    w.costo_lista(engine, P, datetime(2026, 9, 1), "100")
    w.bono_modelos(engine, [P, OTRA_MARCA], "porcentaje", "6", date(2026, 10, 1), date(2026, 12, 31), tope_unidades=15)
    w.factura(engine, OTRA_MARCA, date(2026, 10, 5), datetime(2026, 10, 5), 10, "100", previo=0)
    w.factura(engine, P, date(2026, 10, 8), datetime(2026, 10, 8), 10, "100", previo=0)
    w.factura(engine, P, date(2026, 10, 15), datetime(2026, 10, 15), 10, "100", previo=0)

    _recalcular(engine, P)

    assert _nn(engine, P) == [D("97.00000"), D("100.00000")]


def test_a_money_cap_stops_the_line_once_its_amount_is_used(engine: Engine) -> None:
    """10 % with tope USD 150: 100 USD off the first invoice (10 u x 100), the 50 left off the second (5 %), nothing
    off the third."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "100")
    tactical = w.tactical(engine, date(2026, 10, 1), date(2026, 12, 31))
    w.bono_modelos(
        engine,
        [P],
        "porcentaje",
        "10",
        date(2026, 10, 1),
        date(2026, 12, 31),
        tope_monto="150",
        moneda="USD",
        tactical_id=tactical,
    )
    for dia in (8, 15, 22):
        w.factura(engine, P, date(2026, 10, dia), datetime(2026, 10, dia), 10, "100", previo=0)

    _recalcular(engine, P)

    assert _nn(engine, P) == [D("90.00000"), D("95.00000"), D("100.00000")]


def test_a_per_unit_line_takes_its_amount_off_every_purchased_unit(engine: Engine) -> None:
    """Tactical 54-like (HP BPS, loaded as sell in: T-c): USD 170 per unit of one model. A USD invoice at 1000 ->
    830; an ARS invoice at the operation's TC 1500 (1,500,000 ARS = 1000 USD) -> 830 too. The daily pass reaches the
    product through the line alone."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "1000")
    tactical = w.tactical(engine, date(2026, 10, 1), date(2026, 12, 31))
    w.bono_modelos(
        engine, [P], "por_unidad", "170", date(2026, 10, 1), date(2026, 12, 31), moneda="USD", tactical_id=tactical
    )
    w.factura(engine, P, date(2026, 10, 8), datetime(2026, 10, 8), 10, "1000", previo=0)
    w.factura(
        engine,
        P,
        date(2026, 10, 15),
        datetime(2026, 10, 15),
        10,
        "1500000",
        previo=0,
        curr_id=1,
        pedido=5,
        tc_pedido="1500",
    )
    with sessionmaker(bind=engine)() as db:
        assert queue.productos_vigentes(db) == [P]

    _recalcular(engine, P)

    assert _nn(engine, P) == [D("830.00000"), D("830.00000")]


def test_a_per_unit_amount_with_vat_comes_off_without_it(engine: Engine) -> None:
    """An ARS per-unit line of 121 with VAT (21 %) is 100 ARS net: at the invoice date's rate (1000) 0.10 USD off a
    10 USD unit."""
    w.producto(engine, P)
    w.run(engine, "UPDATE productos_erp SET iva = 21 WHERE item_id = :i", i=P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "10")
    w.tipo_cambio(engine, date(2026, 10, 1), 1000)
    w.bono_modelos(engine, [P], "por_unidad", "121", date(2026, 10, 1), date(2026, 12, 31), incluye_iva=True)
    w.factura(engine, P, date(2026, 10, 8), datetime(2026, 10, 8), 10, "10", previo=0)

    _recalcular(engine, P)

    assert _nn(engine, P) == [D("9.90000")]


def test_a_loyalty_without_topes_applies_on_every_invoice_of_its_range_from_any_supplier(engine: Engine) -> None:
    """T-a (L5, L7.2): no topes is the loyalty: every invoice of the brand dated in its range, whatever the supplier,
    and none after it."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "100")
    w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 10, 31))
    w.factura(engine, P, date(2026, 10, 8), datetime(2026, 10, 8), 10, "100", previo=0, supp_id=14)
    w.factura(engine, P, date(2026, 10, 20), datetime(2026, 10, 20), 500, "100", previo=0, supp_id=19)
    w.factura(engine, P, date(2026, 11, 5), datetime(2026, 11, 5), 10, "100", previo=0, supp_id=14)

    _recalcular(engine, P)

    assert _nn(engine, P) == [D("96.40000"), D("96.40000"), D("100.00000")]


def test_a_tactical_sell_out_line_never_touches_the_cost(engine: Engine) -> None:
    """T-d (L12: "SO va en la venta, como ganancia adicional"): a tactical's sell-out line (40/35/36 on prod) is on
    the sale. Loading it queues nothing and the invoice keeps only its sell in (a 1 % loyalty)."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "100")
    w.bono_marca(engine, "1", date(2026, 10, 1), date(2026, 12, 31))
    w.factura(engine, P, date(2026, 10, 8), datetime(2026, 10, 8), 10, "100", previo=0)
    _vaciar_cola(engine)

    w.sell_out_tactical(
        engine, w.tactical(engine, date(2026, 10, 1), date(2026, 12, 31)), "10", date(2026, 10, 1), date(2026, 12, 31)
    )
    assert w.encolados(engine) == []

    _recalcular(engine, P)
    assert _nn(engine, P) == [D("99.00000")]


def test_editing_a_tope_or_a_per_unit_line_queues_its_products_from_its_date(engine: Engine) -> None:
    """L15: a tope edit moves which invoices the line covers; a per-unit line is a sell in like a % one."""
    w.producto(engine, P)
    w.producto(engine, OTRA_MARCA, marca="OTRA")
    capado = w.bono_modelos(engine, [P], "porcentaje", "6", date(2026, 10, 1), date(2026, 12, 31), tope_unidades=15)
    for cambio in ("tope_unidades = 20", "tope_monto = 1000"):
        _vaciar_cola(engine)
        w.run(engine, f"UPDATE sell_in_bonos_marca SET {cambio} WHERE id = :b", b=capado)
        assert w.encolados(engine) == [(P, date(2026, 10, 1))], cambio

    _vaciar_cola(engine)
    tactical = w.tactical(engine, date(2026, 10, 5), date(2026, 12, 31))
    unidad = w.bono_modelos(
        engine,
        [OTRA_MARCA],
        "por_unidad",
        "170",
        date(2026, 10, 5),
        date(2026, 12, 31),
        moneda="USD",
        tactical_id=tactical,
    )
    assert w.encolados(engine) == [(OTRA_MARCA, date(2026, 10, 5))]
    _vaciar_cola(engine)
    w.run(engine, "UPDATE sell_in_bonos_marca SET monto_unit = 180 WHERE id = :b", b=unidad)
    assert w.encolados(engine) == [(OTRA_MARCA, date(2026, 10, 5))]


@pytest.mark.parametrize("capado", [False, True], ids=["loyalty", "capped"])
def test_a_percentage_with_vat_comes_off_without_it_like_on_the_sale(engine: Engine, capado: bool) -> None:
    """S33 (the sale-cost path's rule: "a la cuenta siempre debería llegar 2,71"): a 3.28 % line with VAT on a 21 %
    product is 3.28 / 1.21 = 2.7107 % of the net, on a plain line and on a capped one alike."""
    w.producto(engine, P)
    w.run(engine, "UPDATE productos_erp SET iva = 21 WHERE item_id = :i", i=P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "100")
    if capado:
        w.bono_modelos(
            engine, [P], "porcentaje", "3.28", date(2026, 10, 1), date(2026, 12, 31), tope_unidades=50, incluye_iva=True
        )
    else:
        w.bono_marca(engine, "3.28", date(2026, 10, 1), date(2026, 12, 31), incluye_iva=True)
    w.factura(engine, P, date(2026, 10, 8), datetime(2026, 10, 8), 10, "100", previo=0)

    _recalcular(engine, P)

    assert _nn(engine, P) == [D("97.28930")]


def test_a_line_never_takes_more_than_the_purchase_and_a_money_cap_counts_only_what_it_took(engine: Engine) -> None:
    """USD 170 per unit on a USD 100 unit takes the whole 100 (net-net 0, the % stays 100); with a USD 1500 cap the
    first invoice (10 u) uses 1000 of it, so the 500 left still come off the next one (5 % of 10 x 1000)."""
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "100")
    tactical = w.tactical(engine, date(2026, 10, 1), date(2026, 12, 31))
    w.bono_modelos(
        engine,
        [P],
        "por_unidad",
        "170",
        date(2026, 10, 1),
        date(2026, 12, 31),
        tope_monto="1500",
        moneda="USD",
        tactical_id=tactical,
    )
    w.factura(engine, P, date(2026, 10, 8), datetime(2026, 10, 8), 10, "100", previo=0)
    w.factura(engine, P, date(2026, 10, 15), datetime(2026, 10, 15), 10, "1000", previo=0)

    _recalcular(engine, P)

    assert _nn(engine, P) == [D("0.00000"), D("950.00000")]


# --- L21: a product no sell in ever reached also gets a costo SI, from 2026-11-01 00:00 -----------------------------

SIN_SELL_IN = 5105


def _sin_sell_in(engine: Engine) -> None:
    """No sell in, no bonus: list cost 25 since 10-15; an invoice at 30 on 10-20 (in stock by 11-01: 200 then) and,
    since 11-01, one at 22 on 11-05 linked to a Compras order without any sell in."""
    w.producto(engine, SIN_SELL_IN)
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 10, 15, 9, 0), "25")
    w.factura(engine, SIN_SELL_IN, date(2026, 10, 20), datetime(2026, 10, 20, 10), 50, "30", previo=150)
    w.factura(engine, SIN_SELL_IN, date(2026, 11, 5), datetime(2026, 11, 5, 10), 100, "22", previo=200, pedido=7)
    w.run(engine, "DELETE FROM costo_si_dirty")


def test_l21_a_product_without_sell_in_starts_on_11_01_and_averages_every_invoice_after_it(engine: Engine) -> None:
    """L21: the start is 2026-11-01 00:00 at that instant's list cost and available stock (S2/S3); the invoice before
    it only counts as stock; the one after it enters the average with no discount."""
    _sin_sell_in(engine)

    _recalcular(engine, SIN_SELL_IN)

    assert w.pasos(engine, SIN_SELL_IN) == [
        ("inicio", date(2026, 11, 1), 200, 200, D("25.00000"), D("25.00000")),
        ("compra", date(2026, 11, 5), 100, 200, D("22.00000"), D("24.00000")),
    ]
    assert w.rows(
        engine, "SELECT sell_in_pct, sell_ins FROM costo_si_pasos WHERE item_id = :i AND tipo = 'compra'", i=SIN_SELL_IN
    ) == [(D("0"), [])]


def test_l21_without_an_invoice_since_11_01_the_costo_si_is_the_start_cost(engine: Engine) -> None:
    w.producto(engine, SIN_SELL_IN)
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 10, 15, 9, 0), "25")
    w.factura(engine, SIN_SELL_IN, date(2026, 10, 20), datetime(2026, 10, 20, 10), 50, "30", previo=150)

    _recalcular(engine, SIN_SELL_IN)

    assert w.pasos(engine, SIN_SELL_IN) == [("inicio", date(2026, 11, 1), 200, 200, D("25.00000"), D("25.00000"))]


def test_l21_the_reader_says_costo_si_for_a_product_without_sell_in(engine: Engine) -> None:
    """S5: once computed, the reader's source is the costo SI (24 USD), no longer the list cost."""
    from app.services.costo_si import lote

    _sin_sell_in(engine)
    _recalcular(engine, SIN_SELL_IN)

    with sessionmaker(bind=engine)() as db:
        costo = lote.actuales(db, [SIN_SELL_IN], tipo_cambio=1000)[SIN_SELL_IN]
    assert (costo.fuente, costo.costo, costo.moneda, costo.costo_si_desde) == (
        lote.FUENTE_COSTO_SI,
        D("24.00000"),
        "USD",
        date(2026, 11, 5),
    )


def test_l21_without_a_list_cost_or_an_invoice_the_cost_stays_unknown_never_0(engine: Engine) -> None:
    """Interfaz §7: no start cost and nothing bought since 11-01: no average is stored, the reader never says 0."""
    from app.services.costo_si import lote

    w.producto(engine, SIN_SELL_IN)

    _recalcular(engine, SIN_SELL_IN)

    assert [p[5] for p in w.pasos(engine, SIN_SELL_IN)] in ([], [None])
    with sessionmaker(bind=engine)() as db:
        costo = lote.actuales(db, [SIN_SELL_IN])[SIN_SELL_IN]
    assert costo.fuente != lote.FUENTE_COSTO_SI and costo.costo is None and costo.costo_ars is None


def test_l21_a_product_with_a_sell_in_keeps_its_own_start(engine: Engine) -> None:
    """S2 unchanged: a first sell in before 11-01 (10-05) or after it (11-02, Alejandro's L1) stays the start."""
    _l1(engine)
    w.producto(engine, OTRA_MARCA, marca="OTRA")
    w.costo_lista(engine, OTRA_MARCA, datetime(2026, 9, 1), "100")
    w.factura(engine, OTRA_MARCA, date(2026, 10, 5), datetime(2026, 10, 5, 10), 10, "100", previo=0, pedido=11)
    w.sell_in_compra(engine, OTRA_MARCA, 11, "5", date(2026, 10, 5))

    _recalcular(engine, P)
    _recalcular(engine, OTRA_MARCA)

    assert w.pasos(engine, P)[0][:2] == ("inicio", date(2026, 11, 2))
    assert w.pasos(engine, OTRA_MARCA)[0][:2] == ("inicio", date(2026, 10, 5))


def test_l21_an_invoice_dated_before_11_01_entering_after_it_counts_as_start_stock(engine: Engine) -> None:
    """S2/S3 at L21's start: invoiced on 10-25 but received on 11-03, its 50 are stock at the start cost, never a
    purchase in the average (verifier probe A)."""
    w.producto(engine, SIN_SELL_IN)
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 10, 15, 9, 0), "25")
    w.factura(engine, SIN_SELL_IN, date(2026, 10, 25), datetime(2026, 11, 3, 10), 50, "30", previo=150)

    _recalcular(engine, SIN_SELL_IN)

    assert w.pasos(engine, SIN_SELL_IN) == [("inicio", date(2026, 11, 1), 200, 200, D("25.00000"), D("25.00000"))]


# --- L23: without any sell in, every list-cost change re-anchors the costo SI at 00:00 of the day it is in force -----


def test_l23_a_list_change_without_an_invoice_re_anchors_the_costo_si_from_that_day(engine: Engine) -> None:
    """L23 (4766): list 1014 on 11-01, then 1260 from 11-10 09:00 with no invoice: costo SI 1260 from 00:00 of
    11-11 (the S2 rule: the list in force at 00:00). A row repeating the price in force moves nothing."""
    from app.services.costo_si import lote

    w.producto(engine, SIN_SELL_IN)
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 10, 15, 9, 0), "1014")
    w.factura(engine, SIN_SELL_IN, date(2026, 10, 20), datetime(2026, 10, 20, 10), 50, "900", previo=150)
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 11, 5, 9, 0), "1014")
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 11, 10, 9, 0), "1260")

    resultado = _recalcular(engine, SIN_SELL_IN)

    assert w.pasos(engine, SIN_SELL_IN) == [
        ("inicio", date(2026, 11, 1), 200, 200, D("1014.00000"), D("1014.00000")),
        ("lista", date(2026, 11, 11), 200, 200, D("1260.00000"), D("1260.00000")),
    ]
    assert resultado.desde == date(2026, 11, 1)
    with sessionmaker(bind=engine)() as db:
        costo = lote.actuales(db, [SIN_SELL_IN], tipo_cambio=1000)[SIN_SELL_IN]
    assert (costo.fuente, costo.costo, costo.costo_si_desde) == (
        lote.FUENTE_COSTO_SI,
        D("1260.00000"),
        date(2026, 11, 11),
    )


def test_l23_a_change_after_midnight_is_in_force_the_next_day_only(engine: Engine) -> None:
    """The S2 cut is 00:00 local, naive like GBP's timestamps: a change at 01:00 of 11-11 is in force on 11-12, never
    on 11-11 itself (a timezone-aware cut would move it to 03:00 under a UTC session)."""
    w.producto(engine, SIN_SELL_IN)
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 10, 15, 9, 0), "1014")
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 11, 10, 9, 0), "1260")
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 11, 11, 1, 0), "1300")

    _recalcular(engine, SIN_SELL_IN)

    assert [(p[0], p[1], p[5]) for p in w.pasos(engine, SIN_SELL_IN)] == [
        ("inicio", date(2026, 11, 1), D("1014.00000")),
        ("lista", date(2026, 11, 11), D("1260.00000")),
        ("lista", date(2026, 11, 12), D("1300.00000")),
    ]


def test_l23_an_invoice_after_a_list_change_averages_from_the_re_anchored_cost(engine: Engine) -> None:
    """S4 after L23: list 25 -> 40 on 11-03 10:00 (in force 11-04), then 100 at 22 on 11-05 over the 200 in stock:
    (200 x 40 + 100 x 22) / 300 = 34."""
    _sin_sell_in(engine)
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 11, 3, 10, 0), "40")

    _recalcular(engine, SIN_SELL_IN)

    assert w.pasos(engine, SIN_SELL_IN) == [
        ("inicio", date(2026, 11, 1), 200, 200, D("25.00000"), D("25.00000")),
        ("lista", date(2026, 11, 4), 200, 200, D("40.00000"), D("40.00000")),
        ("compra", date(2026, 11, 5), 100, 200, D("22.00000"), D("34.00000")),
    ]


def test_l23_a_list_change_after_the_invoice_resets_its_average(engine: Engine) -> None:
    """The re-anchor wins over the average before it: invoice on 11-05 (average 24), list 30 from 11-08."""
    _sin_sell_in(engine)
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 11, 7, 18, 0), "30")

    _recalcular(engine, SIN_SELL_IN)

    assert [(p[0], p[1], p[5]) for p in w.pasos(engine, SIN_SELL_IN)] == [
        ("inicio", date(2026, 11, 1), D("25.00000")),
        ("compra", date(2026, 11, 5), D("24.00000")),
        ("lista", date(2026, 11, 8), D("30.00000")),
    ]


def test_l23_the_daily_pass_picks_up_a_list_change_and_re_costs_what_follows_from_its_day(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No new cron: the daily `encolar_vigentes` queues the product, the drain stores the re-anchor and hands what
    follows the average (`despues`) the day it is in force."""
    w.producto(engine, SIN_SELL_IN)
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 10, 15, 9, 0), "1014")
    w.factura(engine, SIN_SELL_IN, date(2026, 10, 20), datetime(2026, 10, 20, 10), 50, "900", previo=150)
    _recalcular(engine, SIN_SELL_IN)
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 11, 10, 9, 0), "1260")
    despachados = []
    monkeypatch.setattr(queue.despues, "despachar", lambda db, item_id, desde: despachados.append((item_id, desde)))
    with sessionmaker(bind=engine)() as db:
        queue.encolar_vigentes(db)
        db.commit()

    queue.drenar(
        sessionmaker(bind=engine, autoflush=False),
        datetime.now(UTC) + timedelta(minutes=1),
        is_transient=lambda exc: False,
    )

    assert [p[:2] for p in w.pasos(engine, SIN_SELL_IN)] == [
        ("inicio", date(2026, 11, 1)),
        ("lista", date(2026, 11, 11)),
    ]
    assert (SIN_SELL_IN, date(2026, 11, 11)) in despachados


def test_l23_a_product_with_a_sell_in_ignores_every_list_change(engine: Engine) -> None:
    """L23 is the no-sell-in scope only: a product with a sell in keeps averaging its invoices whatever its list does."""
    w.producto(engine, OTRA_MARCA, marca="OTRA")
    w.costo_lista(engine, OTRA_MARCA, datetime(2026, 9, 1), "100")
    w.factura(engine, OTRA_MARCA, date(2026, 10, 5), datetime(2026, 10, 5, 10), 10, "100", previo=0, pedido=11)
    w.sell_in_compra(engine, OTRA_MARCA, 11, "5", date(2026, 10, 5))
    w.costo_lista(engine, OTRA_MARCA, datetime(2026, 10, 20, 9, 0), "200")
    w.costo_lista(engine, OTRA_MARCA, datetime(2026, 11, 10, 9, 0), "300")

    _recalcular(engine, OTRA_MARCA)

    assert [p[0] for p in w.pasos(engine, OTRA_MARCA)] == ["inicio", "compra"]


# --- §7 at the start: a list row <= 0 is never a cost; the start takes the first list cost > 0 on or after it -------

TAPO = 5108


def test_a_start_at_a_zero_list_row_takes_the_first_positive_list_cost_after_it(engine: Engine) -> None:
    """The Tapo case (L24 check, items 4745-4751): a loyalty from 10-01 starts the product there, the list in force at
    that 00:00 is a 0.00 row and the real price (74.95) comes on 10-13, with no invoice: the start is 74.95, never
    unknown, never 0."""
    w.producto(engine, TAPO)
    w.costo_lista(engine, TAPO, datetime(2026, 9, 30, 9, 0), "0")
    w.costo_lista(engine, TAPO, datetime(2026, 10, 13, 9, 0), "74.95")
    w.costo_lista(engine, TAPO, datetime(2026, 10, 20, 9, 0), "76.8667")
    w.factura(engine, TAPO, date(2026, 9, 25), datetime(2026, 9, 25, 10), 40, "70", previo=0)
    w.bono_marca(engine, "3", date(2026, 10, 1), date(2026, 12, 31))

    _recalcular(engine, TAPO)

    assert w.pasos(engine, TAPO) == [("inicio", date(2026, 10, 1), 40, 40, D("74.95000"), D("74.95000"))]


def test_a_no_sell_in_start_at_a_zero_list_row_takes_the_first_positive_list_cost_too(engine: Engine) -> None:
    """Same rule without sell in (L21): 0.00 in force on 11-01, 1014 from 11-05; the re-anchor (L23) to that same
    price adds no step."""
    w.producto(engine, SIN_SELL_IN)
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 10, 15, 9, 0), "0")
    w.costo_lista(engine, SIN_SELL_IN, datetime(2026, 11, 5, 9, 0), "1014")

    _recalcular(engine, SIN_SELL_IN)

    assert [(p[0], p[1], p[5]) for p in w.pasos(engine, SIN_SELL_IN)] == [
        ("inicio", date(2026, 11, 1), D("1014.00000"))
    ]


def test_a_start_with_no_positive_list_cost_yet_stays_unknown_and_is_logged(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    """§7: only 0.00 rows and no invoice: no average (never 0), and the product is logged so someone loads a cost."""
    w.producto(engine, TAPO)
    w.costo_lista(engine, TAPO, datetime(2026, 9, 30, 9, 0), "0")
    w.costo_lista(engine, TAPO, datetime(2026, 10, 13, 9, 0), "0")
    w.bono_marca(engine, "3", date(2026, 10, 1), date(2026, 12, 31))

    with caplog.at_level("WARNING", logger="app.services.costo_si.fuentes"):
        _recalcular(engine, TAPO)

    assert [p[5] for p in w.pasos(engine, TAPO)] in ([], [None])
    assert any(str(TAPO) in r.getMessage() and "no list cost" in r.getMessage() for r in caplog.records)


# --- L22: a PC never has a history of its own; its cost is its components' sum, read at read time ------------------

PC_L22, PC_L22_SIN_BOM = 5106, 5107


def test_l22_the_engine_never_computes_a_pc_history_with_or_without_components(engine: Engine) -> None:
    """With a bill of materials or without one, no sell in and a list cost on 11-01: no history of its own (L21's
    start would freeze it at the 11-01 list), and the components keep theirs."""
    _sin_sell_in(engine)
    for pc in (PC_L22, PC_L22_SIN_BOM):
        w.producto(engine, pc, cat_id=47)
        w.costo_lista(engine, pc, datetime(2026, 10, 15, 9, 0), "360")
    w.run(
        engine,
        "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :p, 2)",
        c=PC_L22,
        p=SIN_SELL_IN,
    )

    for item in (SIN_SELL_IN, PC_L22, PC_L22_SIN_BOM):
        _recalcular(engine, item)

    assert w.pasos(engine, PC_L22) == [] and w.pasos(engine, PC_L22_SIN_BOM) == []
    assert w.pasos(engine, SIN_SELL_IN)[-1][5] == D("24.00000")
    with sessionmaker(bind=engine)() as db:
        assert fuentes.inicio_de(db, PC_L22) is None and fuentes.inicio_de(db, PC_L22_SIN_BOM) is None
        assert lectura_costo(db, PC_L22) == (D("48.00000"), "USD")  # 2 x 24, at read time


def lectura_costo(db, item_id: int):
    from app.services.costo_si import lectura

    leido = lectura.leer(db, item_id, HOY)
    return leido.costo_si_usd, leido.moneda


def test_l22_a_component_change_re_costs_the_pcs_that_contain_it(engine: Engine) -> None:
    """The callbacks re-cost a combo when a component's cost changes (`lote.combos_con`): a PC now too."""
    from app.services.costo_si import lote

    w.producto(engine, SIN_SELL_IN)
    w.producto(engine, PC_L22, cat_id=47)
    w.run(
        engine,
        "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :p, 1)",
        c=PC_L22,
        p=SIN_SELL_IN,
    )

    with sessionmaker(bind=engine)() as db:
        assert lote.combos_con(db, [SIN_SELL_IN]) == {SIN_SELL_IN: [PC_L22]}
