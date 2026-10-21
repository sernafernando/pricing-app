"""The `sell_out_dirty` row triggers (sell-in-sell-out T7 S4): the changes the
app's own writers (`sell.drain`, the campaigns API, BNA) never see, and which
campaigns each one queues.

Postgres only. Runs in a throwaway schema (`_world`) with ONLY these triggers
installed (no `sell_dirty` triggers), so every queued row comes from them.
"""

from __future__ import annotations

import select
from datetime import date
from typing import Iterator, List

import pytest
from sqlalchemy import Engine

from app.services.sell_out import triggers
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

D = date
TPLINK_ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}  # reaches 2964 only
MERCUSYS = {"marca": "MERCUSYS"}  # reaches 950 only
PORCENTAJE_COSTO = {"tipo": "porcentaje", "monto_unit": None, "porcentaje": "2.0000", "base_porcentaje": "costo"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_triggers") as engine:
        with engine.begin() as conn:
            for statement in triggers.UPGRADE_SQL:
                conn.exec_driver_sql(statement)
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)
    w.execute(engine, "DELETE FROM productos_erp WHERE item_id NOT IN (2964, 2270, 950)")
    w.execute(
        engine,
        "UPDATE productos_erp SET marca = 'TP-LINK', categoria = 'Routers', subcategoria_id = 11, iva = 21 WHERE item_id = 2964",
    )  # noqa: E501
    w.execute(
        engine,
        "UPDATE productos_erp SET marca = 'TP-LINK', categoria = 'Switches', subcategoria_id = 12, iva = 10.5 WHERE item_id = 2270",
    )  # noqa: E501
    w.execute(
        engine,
        "UPDATE productos_erp SET marca = 'MERCUSYS', categoria = 'Routers', subcategoria_id = 11, iva = 21 WHERE item_id = 950",
    )  # noqa: E501
    w.clear_queue(engine)


def _ids(engine: Engine) -> List[int]:
    return [cid for cid, _, _ in w.queued(engine)]


def _consumo(engine: Engine, campana_id: int, canal: str, ref: int, item_id: int, dia: date) -> None:
    w.execute(
        engine,
        "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
        "VALUES (:c, :canal, :ref, :i, :d, 1, 10)",
        c=campana_id,
        canal=canal,
        ref=ref,
        i=item_id,
        d=dia,
    )


class TestGroupFilters:
    """Reach changes made through the offsets API group filters (`offset_grupo_filtros`)."""

    def test_adding_a_filter_queues_the_active_campaigns_of_that_group_only(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TPLINK_ROUTERS])
        activa = w.campana(engine, [routers])
        w.campana(engine, [routers], estado="anulada")
        w.campana(engine, [w.grupo(engine, [MERCUSYS])])  # another group
        w.clear_queue(engine)

        w.execute(engine, "INSERT INTO offset_grupo_filtros (grupo_id, item_id) VALUES (:g, 2270)", g=routers)

        assert _ids(engine) == [activa]

    def test_changing_a_filter_queues_its_campaigns(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TPLINK_ROUTERS])
        cid = w.campana(engine, [routers])
        w.clear_queue(engine)

        w.execute(engine, "UPDATE offset_grupo_filtros SET categoria = 'Switches' WHERE grupo_id = :g", g=routers)

        assert _ids(engine) == [cid]

    def test_moving_a_filter_to_another_group_queues_the_campaigns_of_both(self, engine: Engine) -> None:
        origen = w.grupo(engine, [TPLINK_ROUTERS])
        destino = w.grupo(engine, [MERCUSYS])
        de_origen = w.campana(engine, [origen])
        de_destino = w.campana(engine, [destino])
        w.clear_queue(engine)

        w.execute(engine, "UPDATE offset_grupo_filtros SET grupo_id = :d WHERE grupo_id = :o", d=destino, o=origen)

        assert _ids(engine) == sorted([de_origen, de_destino])

    def test_deleting_a_filter_queues_its_campaigns(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TPLINK_ROUTERS, MERCUSYS])
        cid = w.campana(engine, [routers])
        w.clear_queue(engine)

        w.execute(engine, "DELETE FROM offset_grupo_filtros WHERE grupo_id = :g AND marca = 'MERCUSYS'", g=routers)

        assert _ids(engine) == [cid]

    def test_rewriting_a_filter_with_the_same_values_queues_nothing(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TPLINK_ROUTERS])
        w.campana(engine, [routers])
        w.clear_queue(engine)

        w.execute(
            engine,
            "UPDATE offset_grupo_filtros SET grupo_id = grupo_id, marca = marca, categoria = categoria, "
            "subcategoria_id = subcategoria_id, item_id = item_id, created_at = now() WHERE grupo_id = :g",
            g=routers,
        )

        assert _ids(engine) == []


class TestProducts:
    """`productos_erp` brand or category changes (and the rest of what the allocation reads of a product)."""

    def test_a_brand_change_queues_the_campaigns_reaching_the_old_and_the_new_brand(self, engine: Engine) -> None:
        tplink = w.campana(engine, [w.grupo(engine, [{"marca": "TP-LINK"}])])
        mercusys = w.campana(engine, [w.grupo(engine, [MERCUSYS])])
        w.campana(engine, [w.grupo(engine, [{"marca": "NETGEAR"}])])  # neither side
        w.campana(engine, [w.grupo(engine, [{"marca": "TP-LINK"}])], estado="anulada")
        w.clear_queue(engine)

        w.execute(engine, "UPDATE productos_erp SET marca = 'MERCUSYS' WHERE item_id = 2270")

        assert _ids(engine) == sorted([tplink, mercusys])

    @pytest.mark.parametrize(
        "columna, nuevo, filtro",
        [
            ("categoria", "Switches", {"marca": "TP-LINK", "categoria": "Routers"}),
            ("subcategoria_id", 12, {"subcategoria_id": 11}),
        ],
    )
    def test_a_category_change_queues_the_campaigns_it_leaves(self, engine: Engine, columna, nuevo, filtro) -> None:
        cid = w.campana(engine, [w.grupo(engine, [filtro])])
        w.clear_queue(engine)

        w.execute(engine, f"UPDATE productos_erp SET {columna} = :v WHERE item_id = 2964", v=nuevo)

        assert _ids(engine) == [cid]

    def test_a_vat_change_queues_only_the_campaigns_whose_amount_depends_on_it(self, engine: Engine) -> None:
        tplink = w.grupo(engine, [{"marca": "TP-LINK"}])
        con_iva = w.campana(engine, [tplink], monto_incluye_iva=True)
        precio_neto = w.campana(engine, [tplink], **{**PORCENTAJE_COSTO, "base_porcentaje": "precio_neto"})
        w.campana(engine, [tplink])  # per unit, without VAT
        w.campana(engine, [tplink], **PORCENTAJE_COSTO)  # cost base: the sale's cost is already without VAT
        w.clear_queue(engine)

        w.execute(engine, "UPDATE productos_erp SET iva = 10.5 WHERE item_id = 2964")

        assert _ids(engine) == sorted([con_iva, precio_neto])

    def test_a_new_or_deleted_product_queues_the_campaigns_reaching_it(self, engine: Engine) -> None:
        cid = w.campana(engine, [w.grupo(engine, [{"marca": "TP-LINK"}])])
        w.campana(engine, [w.grupo(engine, [MERCUSYS])])
        w.clear_queue(engine)

        w.execute(
            engine,
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, iva) "
            "VALUES (4000, 'C4000', 'Nuevo', 'TP-LINK', 'Routers', 21)",
        )
        assert _ids(engine) == [cid]

        w.clear_queue(engine)
        w.execute(engine, "DELETE FROM productos_erp WHERE item_id = 4000")
        assert _ids(engine) == [cid]

    def test_rewriting_a_product_with_the_same_values_or_other_columns_queues_nothing(self, engine: Engine) -> None:
        w.campana(engine, [w.grupo(engine, [{"marca": "TP-LINK"}])], monto_incluye_iva=True)
        w.clear_queue(engine)

        w.execute(
            engine,
            "UPDATE productos_erp SET marca = marca, categoria = categoria, subcategoria_id = subcategoria_id, "
            "iva = iva, descripcion = 'Otra descripción' WHERE item_id = 2964",
        )

        assert _ids(engine) == []

    def test_with_no_campaign_reaching_it_nothing_is_queued(self, engine: Engine) -> None:
        w.execute(engine, "UPDATE productos_erp SET marca = 'MERCUSYS', iva = 10.5 WHERE item_id = 2270")

        assert _ids(engine) == []


class TestSaleCustomer:
    """A customer-only change on fuera sales: it moves which earlier sale a return reverses
    (`costing.resolver_objetivos`), and a return only counts inside a campaign's range."""

    def test_it_queues_the_campaigns_reaching_the_product_that_end_on_or_after_the_sale(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TPLINK_ROUTERS])
        cubre = w.campana(engine, [routers])  # November
        posterior = w.campana(engine, [routers], desde=D(2026, 12, 1), hasta=D(2026, 12, 31))  # a later return
        w.campana(engine, [routers], desde=D(2026, 10, 1), hasta=D(2026, 10, 31))  # ended before the sale
        w.campana(engine, [w.grupo(engine, [MERCUSYS])])  # another product
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 10))
        w.clear_queue(engine)

        w.execute(engine, "UPDATE ventas_fuera_ml_metricas SET cust_id = 999 WHERE it_transaction = :r", r=ref)

        assert _ids(engine) == sorted([cubre, posterior])

    def test_it_queues_a_campaign_holding_the_sale_even_if_it_no_longer_reaches_it(self, engine: Engine) -> None:
        cid = w.campana(engine, [w.grupo(engine, [MERCUSYS])])
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 10))
        _consumo(engine, cid, "fuera", ref, 2964, D(2026, 11, 10))
        w.clear_queue(engine)

        w.execute(engine, "UPDATE ventas_fuera_ml_metricas SET cust_id = 999 WHERE it_transaction = :r", r=ref)

        assert _ids(engine) == [cid]

    def test_rewriting_the_same_customer_or_another_column_queues_nothing(self, engine: Engine) -> None:
        w.campana(engine, [w.grupo(engine, [TPLINK_ROUTERS])], **PORCENTAJE_COSTO)
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 10))
        w.clear_queue(engine)

        w.execute(
            engine,
            "UPDATE ventas_fuera_ml_metricas SET cust_id = cust_id, costo_total = costo_total, cliente = 'Otro' "
            "WHERE it_transaction = :r",
            r=ref,
        )

        assert _ids(engine) == []


class TestSaleCost:
    """A `costo_total` change without `costo_unitario` (`sell_dirty` only watches the latter): it is the
    base of a percentage campaign on cost (`alcance.ventas`)."""

    @pytest.mark.parametrize(
        "canal, tabla", [("fuera", "ventas_fuera_ml_metricas"), ("tn", "ventas_tienda_nube_metricas")]
    )
    def test_it_queues_the_cost_percentage_campaigns_covering_the_sale(self, engine: Engine, canal, tabla) -> None:
        routers = w.grupo(engine, [TPLINK_ROUTERS])
        porcentaje = w.campana(engine, [routers], **PORCENTAJE_COSTO)
        w.campana(engine, [routers])  # per unit: the cost does not move it
        w.campana(engine, [routers], **{**PORCENTAJE_COSTO, "base_porcentaje": "precio_neto"})
        w.campana(engine, [routers], desde=D(2026, 12, 1), hasta=D(2026, 12, 31), **PORCENTAJE_COSTO)  # after
        ref = w.venta(engine, canal, 2964, 1, D(2026, 11, 10))
        w.clear_queue(engine)

        w.execute(engine, f"UPDATE {tabla} SET costo_total = 41081.90 WHERE it_transaction = :r", r=ref)

        assert _ids(engine) == [porcentaje]

    def test_without_an_active_campaign_nothing_is_queued(self, engine: Engine) -> None:
        w.campana(engine, [w.grupo(engine, [TPLINK_ROUTERS])], estado="anulada", **PORCENTAJE_COSTO)
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 10))
        w.clear_queue(engine)

        w.execute(
            engine, "UPDATE ventas_fuera_ml_metricas SET costo_total = 1, cust_id = 1 WHERE it_transaction = :r", r=ref
        )  # noqa: E501

        assert _ids(engine) == []


class TestQueueSemantics:
    def test_a_trigger_resets_a_parked_campaign_and_notifies_at_commit(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TPLINK_ROUTERS])
        cid = w.campana(engine, [routers])
        w.execute(engine, "INSERT INTO sell_out_dirty (campana_id, attempts, last_error) VALUES (:c, 5, 'roto')", c=cid)
        listener = engine.raw_connection()
        try:
            listener.driver_connection.autocommit = True
            listener.cursor().execute("LISTEN sell_out_dirty")

            w.execute(engine, "UPDATE offset_grupo_filtros SET marca = 'MERCUSYS' WHERE grupo_id = :g", g=routers)

            select.select([listener.driver_connection], [], [], 2)
            listener.driver_connection.poll()
            assert [n.channel for n in listener.driver_connection.notifies] == ["sell_out_dirty"]
        finally:
            listener.invalidate()
        assert w.queued(engine) == [(cid, 0, None)]

    def test_a_change_that_queues_nothing_does_not_notify(self, engine: Engine) -> None:
        listener = engine.raw_connection()
        try:
            listener.driver_connection.autocommit = True
            listener.cursor().execute("LISTEN sell_out_dirty")

            w.execute(engine, "UPDATE productos_erp SET marca = 'NETGEAR' WHERE item_id = 950")

            select.select([listener.driver_connection], [], [], 0.5)
            listener.driver_connection.poll()
            assert listener.driver_connection.notifies == []
        finally:
            listener.invalidate()
