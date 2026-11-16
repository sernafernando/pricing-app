"""Migration `20261119_vpf_offsets_sell_pdf` (VPF T4: S15, S18, L15).

Owner (L15, Q4): "Borrarlos y recalcular desde el PDF". The migration stops the GBP sync from feeding sell in / sell
out (drops its `fuera` triggers), deletes every consumption computed from it (`sell_in_consumos`,
`sell_in_bono_consumos`, `sell_out_consumos` and `sell_dirty` with canal `fuera`, group / individual offset
consumptions `fuera_ml`) and queues what must be recomputed from the PDF lines: every PDF line with a product, one
sale line of each product that lost consumptions, and every campaign that lost rows. ML and TN rows are untouched.
The purge is idempotent and runs in the migration's single transaction.

Real Postgres; the tables start as before the migration (no `item_id` on the lines, canal CHECKs with `fuera`, the
GBP triggers in place). Invented data only (the repo is public).
"""

from __future__ import annotations

import importlib.util
import os
from datetime import date
from typing import Iterator, List

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.models.offset_grupo_consumo import OffsetGrupoConsumo
from app.models.offset_individual_consumo import OffsetIndividualConsumo
from app.services.sell import queue
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _world as sell_in_world
from tests.services.sell_out import _world as sell_out_world

pytestmark = pytest.mark.postgres

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", "20261119_vpf_offsets_sell_pdf.py")
_CHECKS = {
    "sell_dirty": "ck_sell_dirty_canal",
    "sell_in_consumos": "ck_sell_in_consumos_canal",
    "sell_in_bono_consumos": "ck_sell_in_bono_consumos_canal",
    "sell_out_consumos": "ck_sell_out_consumos_canal",
}
_TABLES = list(
    dict.fromkeys(
        sell_in_world.TABLES + sell_out_world.TABLES + [OffsetGrupoConsumo.__table__, OffsetIndividualConsumo.__table__]
    )
)
_STUBS = sell_in_world.STUBS + ["CREATE TABLE offsets_ganancia (id INTEGER PRIMARY KEY)"]
# Before the migration: the GBP triggers (frozen copies of what main had) and a stand-in for the sell out function.
_ANTES = [
    *[sql for sql in queue.UPGRADE_SQL if "sell_dirty_enqueue_venta()" in sql and "FUNCTION" in sql],
    "CREATE OR REPLACE FUNCTION sell_out_enqueue_ventas() RETURNS TRIGGER AS $$ BEGIN RETURN NULL; END $$ "
    "LANGUAGE plpgsql",
    "CREATE TRIGGER trg_sell_out_fuera_update AFTER UPDATE ON ventas_fuera_ml_metricas "
    "REFERENCING OLD TABLE AS viejas NEW TABLE AS nuevas FOR EACH STATEMENT EXECUTE FUNCTION "
    "sell_out_enqueue_ventas('fuera')",
    "CREATE TRIGGER trg_sell_dirty_fuera_insert_delete AFTER INSERT OR DELETE ON ventas_fuera_ml_metricas "
    "FOR EACH ROW EXECUTE FUNCTION sell_dirty_enqueue_venta('fuera')",
    "CREATE TRIGGER trg_sell_dirty_tn_insert_delete AFTER INSERT OR DELETE ON ventas_tienda_nube_metricas "
    "FOR EACH ROW EXECUTE FUNCTION sell_dirty_enqueue_venta('tn')",
]


def _module():
    spec = importlib.util.spec_from_file_location("vpf_offsets_sell_pdf_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str, module=None) -> None:
    module = module or _module()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


def _sql(engine: Engine, sql: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def _filas(engine: Engine, sql: str, **params) -> List[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql), params)]


def _como_antes(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_ventas_fuera_operacion_lineas_item_id"))
        conn.execute(text("ALTER TABLE ventas_fuera_operacion_lineas DROP COLUMN item_id"))
        for tabla, nombre in _CHECKS.items():
            conn.execute(text(f"ALTER TABLE {tabla} DROP CONSTRAINT {nombre}"))
            conn.execute(text(f"ALTER TABLE {tabla} ADD CONSTRAINT {nombre} CHECK (canal IN ('ml', 'fuera', 'tn'))"))
        for sql in _ANTES:
            conn.execute(text(sql))
        conn.execute(
            text(
                "INSERT INTO productos_erp (item_id, codigo, descripcion) VALUES (2964, 'C2964', 'P'), "
                "(2270, 'C2270', 'P'), (950, 'C950', 'P'), (777, 'C777', 'P')"
            )
        )


@pytest.fixture
def engine() -> Iterator[Engine]:
    with throwaway_schema("vpf_t4_migration", _TABLES, _STUBS, after=_como_antes) as engine:
        yield engine


def _linea_pdf(engine: Engine, ref: int, codigo, dia: date = date(2026, 10, 3)) -> None:
    """A PDF document with one line, inserted as #2291 left it (no item_id)."""
    with engine.begin() as conn:
        carga = conn.execute(
            text(
                "INSERT INTO ventas_fuera_pdf_cargas (empresa, desde, hasta, documentos, reemplazados, avisos) "
                "VALUES ('EMPRESA DEMO SRL', :d, :d, 1, 0, '[]') RETURNING id"
            ),
            {"d": dia},
        ).scalar()
        op = conn.execute(
            text(
                "INSERT INTO ventas_fuera_operaciones (carga_id, empresa, vendedor, cliente, tipo, letra, punto_venta, "
                "numero, fecha, importe, saldo, total_lineas, recargo_financiero) "
                "VALUES (:c, 'EMPRESA DEMO SRL', 'Vendedor Demo', 'Cliente Demo', 'Fc', 'A', 9, :n, :d, 100, 0, 100, 0) "
                "RETURNING id"
            ),
            {"c": carga, "n": ref, "d": dia},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO ventas_fuera_operacion_lineas (id, operacion_id, renglon, codigo, articulo, cantidad, "
                "moneda, precio, precio_costo, precio_costo_pp) VALUES (:id, :o, 1, :cod, 'Articulo', 1, 'ARS', 100, "
                "80, 81)"
            ),
            {"id": ref, "o": op, "cod": codigo},
        )


def _sembrar(engine: Engine) -> dict:
    """GBP-derived (`fuera`) and ML / TN consumptions of every kind, a campaign with each, PDF lines and the
    unrelated sales that can requeue a product. FKs off while seeding: only the canal matters here."""
    campana_fuera = sell_out_world.campana(engine, [])
    campana_ml = sell_out_world.campana(engine, [])
    _linea_pdf(engine, 900_001, "C2964")
    _linea_pdf(engine, 900_002, "SIN-CODIGO-ERP")
    _linea_pdf(engine, 900_003, None)
    ml_2270 = sell_in_world.venta(engine, "ml", 2270, 1, date(2026, 10, 2))
    _sql(engine, "DELETE FROM sell_dirty")  # the seed's own queueing is not what is tested
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        for canal, ref, item in (
            ("fuera", 1, 2964),
            ("fuera", 2, 2270),
            ("fuera", 3, 777),
            ("ml", 4, 2964),
            ("tn", 5, 950),
        ):
            conn.execute(
                text(
                    "INSERT INTO sell_in_consumos (compra_item_id, canal, venta_ref, item_id, fecha_venta, unidades, "
                    "descuento_ars) VALUES (1, :c, :r, :i, '2026-10-02', 1, 10)"
                ),
                {"c": canal, "r": ref, "i": item},
            )
            conn.execute(
                text(
                    "INSERT INTO sell_in_bono_consumos (bono_id, canal, venta_ref, item_id, fecha_venta, unidades, "
                    "descuento_ars) VALUES (1, :c, :r, :i, '2026-10-02', 1, 5)"
                ),
                {"c": canal, "r": ref, "i": item},
            )
            conn.execute(
                text(
                    "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
                    "VALUES (:k, :c, :r, :i, '2026-11-02', 1, 10)"
                ),
                {"k": campana_fuera if canal == "fuera" else campana_ml, "c": canal, "r": ref, "i": item},
            )
            conn.execute(
                text("INSERT INTO sell_dirty (canal, venta_ref, item_id) VALUES (:c, :r, :i)"),
                {"c": canal, "r": ref + 100, "i": item},
            )
        for tipo in ("fuera_ml", "ml", "tienda_nube"):
            conn.execute(
                text(
                    "INSERT INTO offset_grupo_consumo (grupo_id, tipo_venta, fecha_venta, item_id, cantidad, offset_id, "
                    "monto_offset_aplicado) VALUES (1, :t, now(), 2964, 1, 1, 10)"
                ),
                {"t": tipo},
            )
            conn.execute(
                text(
                    "INSERT INTO offset_individual_consumo (offset_id, tipo_venta, fecha_venta, item_id, cantidad, "
                    "monto_offset_aplicado) VALUES (1, :t, now(), 2964, 1, 10)"
                ),
                {"t": tipo},
            )
    return {"campana_fuera": campana_fuera, "campana_ml": campana_ml, "ml_2270": ml_2270}


_CONSUMOS = (
    "SELECT 'in', canal, venta_ref FROM sell_in_consumos UNION ALL "
    "SELECT 'bono', canal, venta_ref FROM sell_in_bono_consumos UNION ALL "
    "SELECT 'out', canal, venta_ref FROM sell_out_consumos ORDER BY 1, 2, 3"
)


class TestPurga:
    def test_deletes_every_gbp_consumption_and_keeps_ml_and_tn(self, engine: Engine) -> None:
        _sembrar(engine)

        _step(engine, "upgrade")

        assert _filas(engine, _CONSUMOS) == [
            ("bono", "ml", 4), ("bono", "tn", 5), ("in", "ml", 4), ("in", "tn", 5), ("out", "ml", 4), ("out", "tn", 5),
        ]  # fmt: skip
        assert ("fuera",) not in _filas(engine, "SELECT DISTINCT canal FROM sell_dirty")
        assert _filas(engine, "SELECT tipo_venta FROM offset_grupo_consumo ORDER BY 1") == [("ml",), ("tienda_nube",)]
        assert _filas(engine, "SELECT tipo_venta FROM offset_individual_consumo ORDER BY 1") == [
            ("ml",),
            ("tienda_nube",),
        ]

    def test_queues_the_pdf_lines_the_products_and_the_campaigns_that_lost_rows(self, engine: Engine) -> None:
        ids = _sembrar(engine)

        _step(engine, "upgrade")

        # 2964: its PDF line; 2270: its ML line (no PDF line); 777: no sale left anywhere, nothing to queue.
        assert _filas(engine, "SELECT canal, venta_ref, item_id FROM sell_dirty ORDER BY 1, 2") == [
            ("ml", 104, 2964),
            ("ml", ids["ml_2270"], 2270),
            ("pdf", 900_001, 2964),
            ("tn", 105, 950),
        ]
        assert _filas(engine, "SELECT campana_id FROM sell_out_dirty") == [(ids["campana_fuera"],)]

    def test_running_it_again_changes_nothing(self, engine: Engine) -> None:
        _sembrar(engine)
        _step(engine, "upgrade")
        antes = (
            _filas(engine, _CONSUMOS),
            _filas(engine, "SELECT canal, venta_ref, item_id FROM sell_dirty ORDER BY 1, 2"),
            _filas(engine, "SELECT id, item_id FROM ventas_fuera_operacion_lineas ORDER BY 1"),
        )

        _step(engine, "upgrade")

        assert (
            _filas(engine, _CONSUMOS),
            _filas(engine, "SELECT canal, venta_ref, item_id FROM sell_dirty ORDER BY 1, 2"),
            _filas(engine, "SELECT id, item_id FROM ventas_fuera_operacion_lineas ORDER BY 1"),
        ) == antes

    def test_a_failure_leaves_everything_as_it_was(self, engine: Engine) -> None:
        _sembrar(engine)
        antes = _filas(engine, _CONSUMOS)
        module = _module()
        module.UPGRADE_SQL = [*module.UPGRADE_SQL, "SELECT 1 / 0"]

        with pytest.raises(DBAPIError):
            _step(engine, "upgrade", module)

        assert _filas(engine, _CONSUMOS) == antes
        assert _filas(engine, "SELECT count(*) FROM offset_grupo_consumo WHERE tipo_venta = 'fuera_ml'") == [(1,)]


class TestEsquema:
    def test_backfills_the_product_of_each_pdf_line(self, engine: Engine) -> None:
        _sembrar(engine)

        _step(engine, "upgrade")

        assert _filas(engine, "SELECT id, item_id FROM ventas_fuera_operacion_lineas ORDER BY 1") == [
            (900_001, 2964),
            (900_002, None),
            (900_003, None),
        ]

    def test_the_gbp_sync_queues_nothing_and_a_new_pdf_line_queues_itself(self, engine: Engine) -> None:
        _step(engine, "upgrade")
        _sql(engine, "DELETE FROM sell_dirty")

        sell_in_world.venta(engine, "fuera", 2964, 1, date(2026, 10, 2))
        _linea_pdf(engine, 900_010, "C2964")
        _sql(engine, "UPDATE ventas_fuera_operacion_lineas SET item_id = 2964 WHERE id = 900_010")

        assert _filas(engine, "SELECT canal, venta_ref FROM sell_dirty") == [("pdf", 900_010)]
        assert (
            _filas(
                engine,
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'ventas_fuera_ml_metricas'::regclass AND NOT tgisinternal",
            )
            == []
        )

    @pytest.mark.parametrize("tabla", sorted(_CHECKS))
    def test_the_canal_check_takes_pdf_instead_of_fuera(self, engine: Engine, tabla: str) -> None:
        _step(engine, "upgrade")

        [(definicion,)] = _filas(
            engine,
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint AS c "
            "WHERE c.conname = :n AND c.conrelid = CAST(:t AS regclass)",
            n=_CHECKS[tabla],
            t=tabla,
        )
        assert "'pdf'" in definicion and "'fuera'" not in definicion

    def test_downgrade_restores_the_gbp_triggers_and_drops_the_pdf_ones(self, engine: Engine) -> None:
        _sembrar(engine)
        _step(engine, "upgrade")

        _step(engine, "downgrade")

        assert _filas(engine, "SELECT count(*) FROM sell_dirty WHERE canal = 'pdf'") == [(0,)]
        assert _filas(
            engine,
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'ventas_fuera_operacion_lineas' "
            "AND column_name = 'item_id' AND table_schema = current_schema()",
        ) == [(0,)]
        _sql(engine, "DELETE FROM sell_dirty")
        ref = sell_in_world.venta(engine, "fuera", 2964, 1, date(2026, 10, 2))
        assert _filas(engine, "SELECT canal, venta_ref FROM sell_dirty") == [("fuera", ref)]
