"""`sell_in_bono_dirty` triggers (sell-in-sell-out T3c-3): a change that can
move a brand bonus's generated purchases queues its key and notifies
`sell_in_bono_dirty`, ONLY when an active bonus can care about it; changes that
cannot move them queue nothing. With no active bonus the queue stays empty.

Postgres only (plpgsql triggers, `pg_notify`). Runs in a throwaway schema.
"""

from __future__ import annotations

import select
from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text

from app.services.sell_in import bono_queue
from tests.services.sell_in import _bono_world as b

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bono_queue") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)


@pytest.fixture()
def bono(engine: Engine) -> int:
    """An active TP-LINK bonus over October 2026, with its own queue row cleared."""
    bono_id = b.bono(engine)
    b.clear_queue(engine)
    return bono_id


def _sql(engine: Engine, statement: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(statement), params)


@pytest.mark.postgres
class TestGate:
    def test_without_any_bonus_nothing_is_ever_queued(self, engine: Engine) -> None:
        pedido = b.pedido(engine, {2964: 3})
        b.set_lineas(engine, pedido, {2964: 1, 950: 2})
        b.update_pedido(engine, pedido, estado="cancelado", fecha_factura=D(2026, 10, 11))
        _sql(engine, "UPDATE productos_erp SET marca = 'OTRA' WHERE item_id = 2964")
        _sql(engine, "DELETE FROM pedidos_compra WHERE id = :p", p=pedido)

        assert b.queued(engine) == []

    def test_a_voided_bonus_gates_nothing_in(self, engine: Engine) -> None:
        b.bono(engine, estado="anulada")

        b.pedido(engine, {2964: 3})

        assert b.queued(engine) == []

    def test_an_operation_invoiced_outside_every_active_range_is_not_queued(self, engine: Engine, bono: int) -> None:
        fuera = b.pedido(engine, {2964: 3}, D(2026, 11, 1))
        b.pedido(engine, {2964: 3}, None)

        b.update_pedido(engine, fuera, estado="cancelado")

        assert b.queued(engine) == []


@pytest.mark.postgres
class TestLineasTrigger:
    def test_new_changed_and_removed_invoiced_units_queue_the_operation(self, engine: Engine, bono: int) -> None:
        pedido = b.pedido(engine, {2964: 3})
        assert b.queued(engine) == [("pedido", pedido)]

        b.clear_queue(engine)
        b.set_lineas(engine, pedido, {2964: 2})
        assert b.queued(engine) == [("pedido", pedido)]

        b.clear_queue(engine)
        b.set_lineas(engine, pedido, {})
        assert b.queued(engine) == [("pedido", pedido)]

    def test_rewriting_the_same_units_queues_nothing(self, engine: Engine, bono: int) -> None:
        pedido = b.pedido(engine, {2964: 3})
        b.clear_queue(engine)

        b.set_lineas(engine, pedido, {2964: 3})  # the T3c-2 upsert rewrites every row on each sync

        assert b.queued(engine) == []

    def test_a_requeue_resets_a_failed_row(self, engine: Engine, bono: int) -> None:
        pedido = b.pedido(engine, {2964: 3})
        _sql(engine, "UPDATE sell_in_bono_dirty SET attempts = 5, last_error = 'boom'")

        b.set_lineas(engine, pedido, {2964: 1})

        assert b.queue_rows(engine) == [("pedido", pedido, 0, None)]


@pytest.mark.postgres
@pytest.mark.parametrize("via", ["pedido", "bono", "producto"])
def test_every_trigger_requeue_resets_a_failed_row(engine: Engine, bono: int, via: str) -> None:
    """A new change is a fresh chance: attempts and the last error go back to zero."""
    pedido = b.pedido(engine, {2964: 3})
    _sql(engine, "UPDATE sell_in_bono_dirty SET attempts = 5, last_error = 'boom'")
    b.update_bono(engine, bono, monto_unit=Decimal("7.00"))  # queues the bonus too
    _sql(engine, "UPDATE sell_in_bono_dirty SET attempts = 5, last_error = 'boom'")

    if via == "pedido":
        b.update_pedido(engine, pedido, proveedor_id=32)
    elif via == "producto":
        _sql(engine, "UPDATE productos_erp SET marca = 'OTRA' WHERE item_id = 2964")
    else:
        b.update_bono(engine, bono, monto_unit=Decimal("8.00"))

    rows = {(tipo, ref): (attempts, error) for tipo, ref, attempts, error in b.queue_rows(engine)}
    assert rows[("bono", bono) if via == "bono" else ("pedido", pedido)] == (0, None)


@pytest.mark.postgres
class TestPedidosTrigger:
    @pytest.mark.parametrize(
        "cambio",
        [
            {"fecha_factura": D(2026, 10, 20)},
            {"fecha_factura": None},  # unlinked: the old date was covered
            {"fecha_factura": D(2026, 11, 20)},  # leaves the range: the old date was covered
            {"estado": "cancelado"},
            {"tipo_cambio": Decimal("1500")},
            {"proveedor_id": 32},
        ],
    )
    def test_a_change_the_bonus_reads_queues_the_operation(self, engine: Engine, bono: int, cambio: dict) -> None:
        pedido = b.pedido(engine, {})
        b.clear_queue(engine)

        b.update_pedido(engine, pedido, **cambio)

        assert b.queued(engine) == [("pedido", pedido)]

    def test_an_operation_entering_the_range_is_queued(self, engine: Engine, bono: int) -> None:
        pedido = b.pedido(engine, {}, None)
        assert b.queued(engine) == []

        b.update_pedido(engine, pedido, fecha_factura=D(2026, 10, 3))

        assert b.queued(engine) == [("pedido", pedido)]

    def test_other_changes_and_same_value_rewrites_queue_nothing(self, engine: Engine, bono: int) -> None:
        pedido = b.pedido(engine, {})
        b.clear_queue(engine)

        b.update_pedido(engine, pedido, observaciones="llamar al proveedor", fecha_factura=D(2026, 10, 10))

        assert b.queued(engine) == []

    def test_a_covered_operation_queues_on_insert_and_delete_an_uninvoiced_one_does_not(
        self, engine: Engine, bono: int
    ) -> None:
        facturado = b.pedido(engine, {})
        sin_factura = b.pedido(engine, {}, None)
        assert b.queued(engine) == [("pedido", facturado)]

        b.clear_queue(engine)
        _sql(engine, "DELETE FROM pedidos_compra WHERE id IN (:a, :b)", a=facturado, b=sin_factura)

        assert b.queued(engine) == [("pedido", facturado)]


@pytest.mark.postgres
class TestBonosTrigger:
    def test_a_new_active_bonus_and_a_change_to_what_it_pays_queue_it(self, engine: Engine) -> None:
        bono = b.bono(engine)
        assert b.queued(engine) == [("bono", bono)]

        for cambio in (
            {"monto_unit": Decimal("3.00")},
            {"marca": b.MERCUSYS},
            {"moneda": "ARS"},
            {"fecha_desde": D(2026, 9, 1)},
            {"fecha_hasta": D(2026, 12, 1)},
            {"usuario_id": 8},
            {"estado": "anulada"},  # the void itself is queued: what it generated must go
        ):
            b.clear_queue(engine)
            b.update_bono(engine, bono, **cambio)
            assert b.queued(engine) == [("bono", bono)], cambio

    def test_a_voided_bonus_is_not_queued_again(self, engine: Engine) -> None:
        bono = b.bono(engine, estado="anulada")
        assert b.queued(engine) == []

        b.update_bono(engine, bono, monto_unit=Decimal("9.00"))

        assert b.queued(engine) == []

    def test_a_description_only_edit_queues_nothing(self, engine: Engine, bono: int) -> None:
        b.update_bono(engine, bono, descripcion="Acuerdo Q4")

        assert b.queued(engine) == []


@pytest.mark.postgres
class TestProductosTrigger:
    def test_a_brand_change_queues_the_operations_invoicing_the_product(self, engine: Engine, bono: int) -> None:
        uno, otro = b.pedido(engine, {2964: 1}), b.pedido(engine, {2964: 2, 950: 1})
        b.pedido(engine, {950: 1})
        b.pedido(engine, {2964: 1}, D(2026, 12, 1))  # out of the bonus's range
        b.clear_queue(engine)

        _sql(engine, "UPDATE productos_erp SET marca = 'OTRA' WHERE item_id = 2964")  # leaves TP-LINK

        assert b.queued(engine) == [("pedido", uno), ("pedido", otro)]

    def test_a_brand_change_between_brands_without_bonus_queues_nothing(self, engine: Engine, bono: int) -> None:
        b.pedido(engine, {950: 1})
        b.clear_queue(engine)

        _sql(engine, "UPDATE productos_erp SET marca = 'OTRA' WHERE item_id = 950")  # MERCUSYS has no bonus

        assert b.queued(engine) == []

    def test_a_product_rewrite_without_brand_change_queues_nothing(self, engine: Engine, bono: int) -> None:
        b.pedido(engine, {2964: 1})
        b.clear_queue(engine)

        _sql(engine, "UPDATE productos_erp SET marca = 'TP-LINK', costo = 50 WHERE item_id = 2964")

        assert b.queued(engine) == []

    def test_a_product_arriving_after_its_invoice_queues_its_operations(self, engine: Engine, bono: int) -> None:
        pedido = b.pedido(engine, {4001: 7})  # the catalog sync has not brought 4001 yet
        b.clear_queue(engine)

        _sql(
            engine, "INSERT INTO productos_erp (item_id, codigo, descripcion, marca) VALUES (4001, 'N', 'N', 'TP-LINK')"
        )

        assert b.queued(engine) == [("pedido", pedido)]
        _sql(engine, "DELETE FROM productos_erp WHERE item_id = 4001")

    def test_a_product_without_brand_queues_nothing_while_another_brand_has_a_bonus(
        self, engine: Engine, bono: int
    ) -> None:
        """A NULL brand is no brand: it must not read as "any brand" in the gate."""
        b.pedido(engine, {4006: 1, 4007: 1})  # 4006 and 4007 arrive later
        b.pedido(engine, {950: 1})
        b.clear_queue(engine)

        _sql(engine, "INSERT INTO productos_erp (item_id, codigo, descripcion) VALUES (4006, 'N', 'N')")
        _sql(engine, "INSERT INTO productos_erp (item_id, codigo, descripcion, marca) VALUES (4007, 'N', 'N', NULL)")
        _sql(engine, "UPDATE productos_erp SET marca = NULL WHERE item_id = 950")  # MERCUSYS has no bonus
        _sql(engine, "UPDATE productos_erp SET marca = 'MERCUSYS' WHERE item_id = 950")
        _sql(engine, "DELETE FROM productos_erp WHERE item_id IN (4006, 4007)")

        assert b.queued(engine) == []

    def test_a_product_leaving_a_bonus_brand_for_none_still_queues(self, engine: Engine, bono: int) -> None:
        pedido = b.pedido(engine, {2964: 1})
        b.clear_queue(engine)

        _sql(engine, "UPDATE productos_erp SET marca = NULL WHERE item_id = 2964")

        assert b.queued(engine) == [("pedido", pedido)]

    def test_a_product_removed_from_the_catalog_queues_the_operations_invoicing_it(
        self, engine: Engine, bono: int
    ) -> None:
        """The deleted product no longer matches its old brand: the operation must be reconciled."""
        _sql(
            engine, "INSERT INTO productos_erp (item_id, codigo, descripcion, marca) VALUES (4002, 'N', 'N', 'TP-LINK')"
        )
        _sql(
            engine,
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca) VALUES (4003, 'N', 'N', 'MERCUSYS')",
        )
        uno = b.pedido(engine, {4002: 2, 950: 1})
        b.pedido(engine, {4003: 1})  # MERCUSYS has no bonus
        b.pedido(engine, {4002: 1}, D(2026, 12, 1))  # out of the bonus's range
        b.clear_queue(engine)

        _sql(engine, "DELETE FROM productos_erp WHERE item_id IN (4002, 4003)")

        assert b.queued(engine) == [("pedido", uno)]


@pytest.mark.postgres
class TestProductosCostoTrigger:
    """T25b2: a % of the sale's cost bonus (`base = 'costo_venta'`) has no invoice to gate on: a product whose `marca`
    or `categoria` changes, or that arrives or leaves the catalog, queues `('bono', id)` for every active cost bonus
    reaching it on its old or new side; an `iva` change alone queues the ones loaded with VAT (`incluye_iva`), the
    only ones whose amount reads it."""

    def test_a_brand_change_queues_the_cost_bonuses_of_the_old_and_the_new_brand(self, engine: Engine) -> None:
        tplink = b.bono_costo(engine, marca=b.TPLINK)
        mercusys = b.bono_costo(engine, marca=b.MERCUSYS)
        b.bono_costo(engine, marca="OTRA MARCA")
        b.bono_costo(engine, marca=b.TPLINK, estado="anulada")
        b.clear_queue(engine)

        _sql(engine, "UPDATE productos_erp SET marca = :m WHERE item_id = 2964", m=b.MERCUSYS)

        assert b.queued(engine) == sorted([("bono", tplink), ("bono", mercusys)])

    def test_a_brand_change_still_queues_the_invoice_operations_and_never_an_invoice_bonus(
        self, engine: Engine
    ) -> None:
        factura = b.bono(engine)
        pedido = b.pedido(engine, {2964: 1})
        costo = b.bono_costo(engine)
        b.clear_queue(engine)

        _sql(engine, "UPDATE productos_erp SET marca = 'OTRA' WHERE item_id = 2964")

        assert b.queued(engine) == [("bono", costo), ("pedido", pedido)]
        assert ("bono", factura) not in b.queued(engine)

    def test_a_category_change_queues_the_cost_bonuses_of_the_old_and_the_new_category(self, engine: Engine) -> None:
        routers = b.bono_costo(engine, alcance="categoria", categoria="Routers")
        switches = b.bono_costo(engine, alcance="categoria", categoria="Switches")
        _sql(engine, "UPDATE productos_erp SET categoria = 'Routers' WHERE item_id = 2964")
        b.clear_queue(engine)

        _sql(engine, "UPDATE productos_erp SET categoria = 'Switches' WHERE item_id = 2964")

        assert b.queued(engine) == sorted([("bono", routers), ("bono", switches)])

    def test_a_vat_change_queues_the_cost_bonuses_loaded_with_vat_reaching_the_product(self, engine: Engine) -> None:
        con_iva = b.bono_costo(engine, incluye_iva=True)
        b.bono_costo(engine)  # without VAT: its amount never reads the rate
        modelo = b.bono_costo(engine, alcance="modelos", modelos=(2964,), incluye_iva=True)
        b.bono_costo(engine, alcance="modelos", modelos=(950,), incluye_iva=True)  # does not reach 2964
        b.bono(engine)
        b.pedido(engine, {2964: 1})  # an invoice bonus does not read the VAT rate
        b.set_iva(engine, 2964, 21.0)
        b.clear_queue(engine)

        b.set_iva(engine, 2964, 10.5)

        assert b.queued(engine) == sorted([("bono", con_iva), ("bono", modelo)])

    def test_an_unrelated_change_or_a_same_value_rewrite_queues_nothing(self, engine: Engine) -> None:
        b.bono_costo(engine, incluye_iva=True)
        b.set_iva(engine, 2964, 21.0)
        b.clear_queue(engine)

        _sql(engine, "UPDATE productos_erp SET costo = 50, descripcion = 'Otra' WHERE item_id = 2964")
        _sql(engine, "UPDATE productos_erp SET marca = 'TP-LINK', categoria = NULL, iva = 21.0 WHERE item_id = 2964")

        assert b.queued(engine) == []

    def test_a_product_arriving_or_leaving_the_catalog_queues_the_cost_bonuses_reaching_it(
        self, engine: Engine
    ) -> None:
        costo = b.bono_costo(engine)
        b.bono_costo(engine, marca=b.MERCUSYS)
        b.clear_queue(engine)

        _sql(
            engine, "INSERT INTO productos_erp (item_id, codigo, descripcion, marca) VALUES (4011, 'N', 'N', 'TP-LINK')"
        )
        assert b.queued(engine) == [("bono", costo)]

        b.clear_queue(engine)
        _sql(engine, "DELETE FROM productos_erp WHERE item_id = 4011")
        assert b.queued(engine) == [("bono", costo)]

    def test_a_brand_change_notifies_the_channel(self, engine: Engine) -> None:
        b.bono_costo(engine)
        b.clear_queue(engine)
        raw = engine.raw_connection()
        try:
            raw.driver_connection.autocommit = True
            cursor = raw.cursor()
            cursor.execute(f"LISTEN {bono_queue.CHANNEL}")
            cursor.execute("UPDATE productos_erp SET marca = 'OTRA' WHERE item_id = 2964")
            select.select([raw.driver_connection], [], [], 5)
            raw.driver_connection.poll()
            channels = [n.channel for n in raw.driver_connection.notifies]
        finally:
            raw.invalidate()  # never hand an autocommit connection back to the pool

        assert bono_queue.CHANNEL in channels


@pytest.mark.postgres
def test_the_trigger_notifies_the_channel(engine: Engine) -> None:
    raw = engine.raw_connection()
    try:
        raw.driver_connection.autocommit = True
        cursor = raw.cursor()
        cursor.execute(f"LISTEN {bono_queue.CHANNEL}")
        b.bono(engine)
        select.select([raw.driver_connection], [], [], 5)
        raw.driver_connection.poll()
        channels = [n.channel for n in raw.driver_connection.notifies]
    finally:
        raw.invalidate()  # never hand an autocommit connection back to the pool

    assert bono_queue.CHANNEL in channels


@pytest.mark.postgres
class TestAlcance:
    """T3e: a bonus may reach a category, some models (`sell_in_bono_items`) or one invoice, and pay a
    percentage of the invoiced net. The gate follows each scope's own field."""

    def _categoria(self, engine: Engine, item_id: int, categoria) -> None:
        _sql(engine, "UPDATE productos_erp SET categoria = :c WHERE item_id = :i", c=categoria, i=item_id)

    def test_a_product_entering_or_leaving_a_bonus_category_queues_the_operations_invoicing_it(
        self, engine: Engine
    ) -> None:
        b.bono_alcance(engine, "categoria", categoria="Switches")
        pedido = b.pedido(engine, {2964: 3})
        b.clear_queue(engine)

        self._categoria(engine, 2964, "Switches")
        assert b.queued(engine) == [("pedido", pedido)]

        b.clear_queue(engine)
        self._categoria(engine, 2964, "Routers")
        assert b.queued(engine) == [("pedido", pedido)]

    def test_a_category_change_between_categories_without_bonus_queues_nothing(self, engine: Engine) -> None:
        b.bono_alcance(engine, "categoria", categoria="Switches")
        b.pedido(engine, {2964: 3})
        b.clear_queue(engine)

        self._categoria(engine, 2964, "Routers")
        self._categoria(engine, 2964, "Cables")

        assert b.queued(engine) == []

    def test_a_category_rewrite_with_the_same_value_queues_nothing(self, engine: Engine) -> None:
        b.bono_alcance(engine, "categoria", categoria="Switches")
        self._categoria(engine, 2964, "Switches")
        b.pedido(engine, {2964: 3})
        b.clear_queue(engine)

        self._categoria(engine, 2964, "Switches")

        assert b.queued(engine) == []

    def test_adding_or_removing_a_model_queues_its_active_bonus_only(self, engine: Engine) -> None:
        activo = b.bono_alcance(engine, "modelos", modelos=(2964,))
        anulado = b.bono_alcance(engine, "modelos", estado="anulada")
        b.clear_queue(engine)

        _sql(
            engine,
            "INSERT INTO sell_in_bono_items (bono_id, item_id) VALUES (:b, 2270), (:x, 2270)",
            b=activo,
            x=anulado,
        )
        assert b.queued(engine) == [("bono", activo)]

        b.clear_queue(engine)
        _sql(engine, "DELETE FROM sell_in_bono_items WHERE item_id = 2964")
        assert b.queued(engine) == [("bono", activo)]

    def test_a_listed_model_arriving_in_the_catalog_queues_the_operations_invoicing_it(self, engine: Engine) -> None:
        b.bono_alcance(engine, "modelos", modelos=(7777,))
        pedido = b.pedido(engine, {7777: 3})
        otro = b.pedido(engine, {7778: 3})
        b.clear_queue(engine)

        _sql(
            engine,
            "INSERT INTO productos_erp (item_id, codigo, descripcion) VALUES (7777, 'C7777', 'P'), (7778, 'C7778', 'P')",
        )

        assert b.queued(engine) == [("pedido", pedido)]
        assert ("pedido", otro) not in b.queued(engine)

    def test_a_product_arriving_on_an_invoice_bonus_operation_queues_that_operation_only(self, engine: Engine) -> None:
        pedido = b.pedido(engine, {7777: 3})
        otro = b.pedido(engine, {7777: 1})
        b.bono_alcance(engine, "factura", pedido_id=pedido, tipo="porcentaje", porcentaje="2")
        b.clear_queue(engine)

        _sql(engine, "INSERT INTO productos_erp (item_id, codigo, descripcion) VALUES (7777, 'C7777', 'P')")

        assert b.queued(engine) == [("pedido", pedido)]
        assert ("pedido", otro) not in b.queued(engine)

    def test_a_change_of_invoiced_amount_or_currency_queues_the_operation(self, engine: Engine) -> None:
        b.bono_alcance(engine, "categoria", categoria="Switches", tipo="porcentaje", porcentaje="2")
        pedido = b.pedido(engine, {2964: 3})
        for cambio in ("importe_neto = 1000.00, moneda = 'USD'", "importe_neto = 900.00", "moneda = 'ARS'"):
            b.clear_queue(engine)
            _sql(engine, f"UPDATE pedido_compra_lineas_facturadas SET {cambio} WHERE pedido_id = :p", p=pedido)
            assert b.queued(engine) == [("pedido", pedido)], cambio

    @pytest.mark.parametrize(
        "cambio",
        [
            {"categoria": "Routers"},
            {"tipo": "porcentaje", "monto_unit": None, "porcentaje": Decimal("3")},
        ],
    )
    def test_a_change_to_a_scope_or_kind_field_queues_the_bonus(self, engine: Engine, cambio: dict) -> None:
        bono_id = b.bono_alcance(engine, "categoria", categoria="Switches")
        b.clear_queue(engine)

        b.update_bono(engine, bono_id, **cambio)

        assert b.queued(engine) == [("bono", bono_id)]

    def test_deleting_the_operation_of_an_invoice_bonus_queues_the_bonus(self, engine: Engine) -> None:
        pedido = b.pedido(engine, {2964: 3})
        bono_id = b.bono_alcance(engine, "factura", pedido_id=pedido)
        b.clear_queue(engine)

        _sql(engine, "DELETE FROM pedido_compra_lineas_facturadas WHERE pedido_id = :p", p=pedido)
        _sql(engine, "DELETE FROM pedidos_compra WHERE id = :p", p=pedido)

        assert ("bono", bono_id) in b.queued(engine)  # its pedido_id went NULL: the worker voids what it generated
