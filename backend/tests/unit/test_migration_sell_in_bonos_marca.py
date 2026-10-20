"""Migration `20261107_sell_in_bonos_marca`: the brand bonus table, the origin
columns of `sell_in_compras` and the bonus queue with its triggers.

The parity with the ORM is proven by `tests/models/test_sell_in_schema_postgres.py`
(which runs this migration after `20261024_sell_in_tables`); this module proves the
chain, the database rules a generated purchase relies on and the full downgrade.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.models import test_sell_in_schema_postgres as base

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REVISION = "20261107_sell_in_bonos_marca"
_INSERT_BONO = (
    "INSERT INTO sell_in_bonos_marca (marca, monto_unit, moneda, fecha_desde, fecha_hasta, usuario_id) "
    "VALUES ('TP-LINK', 2, 'USD', DATE '2026-10-01', DATE '2026-10-31', 7) RETURNING id"
)
_INSERT_GENERADA = (
    "INSERT INTO sell_in_compras (fecha_compra, moneda, monto_total, tipo_cambio, usuario_id, origen, bono_id, "
    "bono_pedido_id) VALUES (DATE '2026-10-10', 'USD', 2, 1450, 7, :origen, :bono, :pedido) RETURNING id"
)


def _scripts() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _step(engine: Engine, path: Path, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(base._load_migration(path), step)()


@pytest.fixture()
def engine() -> Iterator[Engine]:
    with base._throwaway_schema("si_bono_mig", lambda eng: base._run(eng, "upgrade")) as eng:
        yield eng


def _names(engine: Engine, sql: str) -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text(sql))}


_TRIGGERS = "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid WHERE c.relnamespace = current_schema()::regnamespace AND NOT t.tgisinternal"  # noqa: E501
_FUNCTIONS = "SELECT proname FROM pg_proc WHERE pronamespace = current_schema()::regnamespace"
_COMPRA_COLUMNS = (
    "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
    "AND table_name = 'sell_in_compras'"
)


class TestMigrationGraph:
    def test_single_head_is_this_revision_chained_on_the_previous_head(self) -> None:
        scripts = _scripts()
        assert scripts.get_heads() == [_REVISION]
        assert scripts.get_revision(_REVISION).down_revision == "20261106_ml_payments_shipment_fanout"


@pytest.mark.postgres
class TestSellInBonosMarcaMigration:
    def test_existing_purchases_become_manual_and_a_manual_one_cannot_carry_a_bonus(self, engine: Engine) -> None:
        with engine.begin() as conn:
            bono = conn.execute(text(_INSERT_BONO)).scalar_one()
            manual = conn.execute(text(base._INSERT_COMPRA), base._compra()).scalar_one()
            origen = conn.execute(text("SELECT origen FROM sell_in_compras WHERE id = :i"), {"i": manual}).scalar()
        assert origen == "manual"
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(_INSERT_GENERADA), {"origen": "manual", "bono": bono, "pedido": None})
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(_INSERT_GENERADA), {"origen": "bono_marca", "bono": None, "pedido": 900})

    def test_one_generated_purchase_per_bonus_and_operation(self, engine: Engine) -> None:
        with engine.begin() as conn:
            bono = conn.execute(text(_INSERT_BONO)).scalar_one()
            conn.execute(text(_INSERT_GENERADA), {"origen": "bono_marca", "bono": bono, "pedido": 900})
            # orphans (operation deleted: NULL) never collide
            conn.execute(text(_INSERT_GENERADA), {"origen": "bono_marca", "bono": bono, "pedido": None})
            conn.execute(text(_INSERT_GENERADA), {"origen": "bono_marca", "bono": bono, "pedido": None})
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(_INSERT_GENERADA), {"origen": "bono_marca", "bono": bono, "pedido": 900})

    def test_deleting_the_operation_leaves_the_purchase_as_an_orphan(self, engine: Engine) -> None:
        with engine.begin() as conn:
            bono = conn.execute(text(_INSERT_BONO)).scalar_one()
            compra = conn.execute(
                text(_INSERT_GENERADA), {"origen": "bono_marca", "bono": bono, "pedido": 900}
            ).scalar_one()
            conn.execute(text("DELETE FROM pedidos_compra WHERE id = 900"))
            pedido = conn.execute(
                text("SELECT bono_pedido_id FROM sell_in_compras WHERE id = :i"), {"i": compra}
            ).scalar_one()
        assert pedido is None

    def test_the_triggers_queue_nothing_while_no_bonus_is_active(self, engine: Engine) -> None:
        """Inert on its own: until an active bonus exists the queue never grows, consumer or not."""
        with engine.begin() as conn:
            conn.execute(text("UPDATE pedidos_compra SET fecha_factura = DATE '2026-10-10' WHERE id = 900"))
            conn.execute(text("INSERT INTO productos_erp (item_id, marca) VALUES (1, 'TP-LINK')"))
            conn.execute(
                text("INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id, cantidad) VALUES (900, 1, 5)")
            )
            conn.execute(
                text(
                    "INSERT INTO sell_in_bonos_marca (marca, monto_unit, moneda, fecha_desde, fecha_hasta, usuario_id, "
                    "estado) VALUES ('TP-LINK', 2, 'USD', DATE '2026-10-01', DATE '2026-10-31', 7, 'anulada')"
                )
            )
            conn.execute(text("UPDATE pedidos_compra SET estado = 'cancelado' WHERE id = 900"))
            conn.execute(text("UPDATE productos_erp SET marca = 'OTRA' WHERE item_id = 1"))
            queued = conn.execute(text("SELECT count(*) FROM sell_in_bono_dirty")).scalar_one()
        assert queued == 0

    def test_the_bonus_queue_triggers_are_installed_and_fire(self, engine: Engine) -> None:
        with engine.begin() as conn:
            bono = conn.execute(text(_INSERT_BONO)).scalar_one()
            conn.execute(text("UPDATE pedidos_compra SET fecha_factura = DATE '2026-10-10' WHERE id = 900"))
            queued = {tuple(r) for r in conn.execute(text("SELECT tipo, ref FROM sell_in_bono_dirty"))}
        assert queued == {("bono", bono), ("pedido", 900)}

    def test_downgrade_removes_everything_it_created(self, engine: Engine) -> None:
        antes = _names(engine, _TRIGGERS)

        _step(engine, base._MIGRATIONS[1], "downgrade")

        tables = _names(engine, "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
        assert not ({"sell_in_bonos_marca", "sell_in_bono_dirty"} & tables)
        assert not ({"origen", "bono_id", "bono_pedido_id"} & _names(engine, _COMPRA_COLUMNS))
        assert not {t for t in _names(engine, _TRIGGERS) if "bono" in t}
        assert not {f for f in _names(engine, _FUNCTIONS) if "bono" in f}
        assert {t for t in antes if "bono" in t}, "the triggers existed before the downgrade"
        # The previous state still works: a purchase loads as before.
        with engine.begin() as conn:
            conn.execute(text(base._INSERT_COMPRA), base._compra())
