"""Migration `20261120_vpf_operaciones_overrides` (vpf-operaciones S3a, S3b, S3c, S4-L2 storage).

Adds `precio_costo_pdf` (backfilled = precio_costo), `item_origen` and `override_estado` to the PDF lines, creates
the overrides and mappings tables and re-resolves the lines loaded "sin producto" with the load's rules: code trimmed
on both sides against productos_erp, then tb_item; a line without code by the first token of its article; ambiguous
= unresolved (S3c: "report how many get fixed"). The UPDATE fires T4's sell_dirty trigger, so every line that gets a
product is queued for offsets and sell in / sell out.

Real Postgres; the tables start as before the migration (ORM tables without the new columns and tables, T4's trigger
installed). Every code, article and amount is INVENTED.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from app.models.producto import ProductoERP
from app.models.sell_dirty import SellDirty
from app.models.tb_item import TBItem
from app.models.venta_fuera_pdf import VentaFueraOperacion, VentaFueraOperacionLinea, VentaFueraPdfCarga
from app.services.sell import queue
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "alembic",
    "versions",
    "20261120_vpf_operaciones_overrides.py",
)
_NUEVAS = ("precio_costo_pdf", "item_origen", "override_estado")
_STUBS = ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)"]


def _module():
    spec = importlib.util.spec_from_file_location("vpf_operaciones_overrides_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _antes(engine: Engine) -> None:
    with engine.begin() as conn:
        for columna in _NUEVAS:
            conn.execute(text(f"ALTER TABLE ventas_fuera_operacion_lineas DROP COLUMN {columna}"))
        for sql in queue.UPGRADE_SQL:
            if "sell_dirty_enqueue_pdf_linea" in sql:
                conn.execute(text(sql))


@pytest.fixture
def engine() -> Iterator[Engine]:
    tablas = [
        VentaFueraPdfCarga.__table__,
        VentaFueraOperacion.__table__,
        VentaFueraOperacionLinea.__table__,
        ProductoERP.__table__,
        TBItem.__table__,
        SellDirty.__table__,
    ]
    with throwaway_schema("vpf_ops_overrides_mig", tablas, _STUBS, after=_antes) as engine:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO productos_erp (item_id, codigo) VALUES (501, '7790000000017    '), "
                    "(502, 'PCEJ4-8U'), (509, '7790000000099')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO tb_item (comp_id, item_id, item_code) VALUES (1, 601, 'CODEJ-100'), "
                    "(2, 601, 'CODEJ-100 '), (1, 603, 'nbej5-8'), (1, 604, 'CTEJ-1200'), (1, 605, 'CTEJ-1200')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO ventas_fuera_pdf_cargas (id, empresa, desde, hasta, documentos, reemplazados, avisos) "
                    "VALUES (1, 'EMPRESA EJEMPLO SA', '2026-10-01', '2026-10-31', 1, 0, '[]')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO ventas_fuera_operaciones (id, carga_id, empresa, vendedor, cliente, tipo, letra, "
                    "punto_venta, numero, fecha, importe, saldo, total_lineas, recargo_financiero) "
                    "VALUES (1, 1, 'EMPRESA EJEMPLO SA', 'Vendedor Uno', 'CLIENTE', 'Fc', 'A', 9, 1, '2026-10-05', "
                    "1, 0, 1, 0)"
                )
            )
            filas = [
                (1, "7790000000099", "YA CON PRODUCTO", 509, "500"),
                (2, "7790000000017", "MONITOR PADDED", None, "800"),
                (3, "CODEJ-100", "CABLE TB_ITEM", None, "100"),
                (4, None, "pcej4-8u PC Ejemplo", None, "0"),
                (5, None, "NBEJ5-8 Notebook Ejemplo", None, "0"),
                (6, None, "CTEJ-1200 Ambiguo", None, "0"),
                (7, None, "Servicio Tecnico (Manual)", None, "0"),
                (8, "7790000088888", "CODIGO DESCONOCIDO", None, "0"),
            ]
            for renglon, codigo, articulo, item_id, costo in filas:
                conn.execute(
                    text(
                        "INSERT INTO ventas_fuera_operacion_lineas (id, operacion_id, renglon, codigo, item_id, "
                        "articulo, cantidad, moneda, precio, precio_costo, precio_costo_pp) "
                        "VALUES (:r, 1, :r, :c, :i, :a, 1, 'ARS', 1000, :costo, :costo)"
                    ),
                    {"r": renglon, "c": codigo, "i": item_id, "a": articulo, "costo": costo},
                )
            conn.execute(text("DELETE FROM sell_dirty"))
        yield engine


def _lineas(engine: Engine) -> dict:
    with engine.connect() as conn:
        return {
            f[0]: tuple(f[1:])
            for f in conn.execute(
                text(
                    "SELECT renglon, item_id, item_origen, precio_costo_pdf::text, override_estado "
                    "FROM ventas_fuera_operacion_lineas"
                )
            ).all()
        }


def test_revision_chain() -> None:
    module = _module()

    assert module.revision == "20261120_vpf_operaciones_overrides"
    assert module.down_revision == "20261122_producto_stock_diario"


def test_upgrade_reresolves_sin_producto_lines_backfills_and_logs_the_count(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="alembic.runtime.migration"):
        _step(engine, "upgrade")

    assert _lineas(engine) == {
        1: (509, "codigo", "500.00", None),
        2: (501, "codigo", "800.00", None),
        3: (601, "codigo", "100.00", None),
        4: (502, "prefijo", "0.00", None),
        5: (603, "prefijo", "0.00", None),
        6: (None, None, "0.00", None),
        7: (None, None, "0.00", None),
        8: (None, None, "0.00", None),
    }
    assert "4 of 7 'sin producto' lines got a product" in caplog.text
    # T4's trigger queued the four lines that got a product.
    with engine.connect() as conn:
        assert sorted(conn.execute(text("SELECT venta_ref, item_id FROM sell_dirty")).all()) == [
            (2, 501),
            (3, 601),
            (4, 502),
            (5, 603),
        ]
    tablas = set(inspect(engine).get_table_names())
    assert {"ventas_fuera_linea_overrides", "ventas_fuera_codigo_mapeos"} <= tablas


def test_the_new_tables_keep_one_override_per_line_and_one_mapping_per_key(engine: Engine) -> None:
    _step(engine, "upgrade")

    unicos = {
        tabla: {tuple(u["column_names"]) for u in inspect(engine).get_unique_constraints(tabla)}
        for tabla in ("ventas_fuera_linea_overrides", "ventas_fuera_codigo_mapeos")
    }

    assert ("empresa", "tipo", "letra", "punto_venta", "numero", "renglon") in unicos["ventas_fuera_linea_overrides"]
    assert ("clave",) in unicos["ventas_fuera_codigo_mapeos"]


def test_downgrade_restores_the_pdf_cost_clears_manual_products_and_drops_everything(engine: Engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(text("UPDATE ventas_fuera_operacion_lineas SET precio_costo = 1234 WHERE renglon = 2"))
        conn.execute(
            text("UPDATE ventas_fuera_operacion_lineas SET item_id = 509, item_origen = 'manual' WHERE renglon = 7")
        )

    _step(engine, "downgrade")

    columnas = {c["name"] for c in inspect(engine).get_columns("ventas_fuera_operacion_lineas")}
    assert not set(_NUEVAS) & columnas
    assert not {"ventas_fuera_linea_overrides", "ventas_fuera_codigo_mapeos"} & set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        filas = dict(
            conn.execute(
                text("SELECT renglon, (item_id, precio_costo::text)::text FROM ventas_fuera_operacion_lineas")
            ).all()
        )
    assert (filas[2], filas[4], filas[7]) == ("(501,800.00)", "(502,0.00)", "(,0.00)")


def test_upgrade_is_one_head() -> None:
    import ast
    import glob

    versiones = os.path.dirname(_PATH)
    revisiones, padres = set(), set()
    padres_de: dict[str, list[str]] = {}
    for ruta in glob.glob(os.path.join(versiones, "*.py")):
        valores = {}
        for nodo in ast.parse(open(ruta, encoding="utf-8").read()).body:
            destino = getattr(nodo, "target", None) or (getattr(nodo, "targets", None) or [None])[0]
            if isinstance(destino, ast.Name) and destino.id in ("revision", "down_revision") and nodo.value:
                valores[destino.id] = ast.literal_eval(nodo.value)
        if "revision" in valores:
            revisiones.add(valores["revision"])
            padre = valores.get("down_revision")
            padres_de[valores["revision"]] = [padre] if isinstance(padre, str) else list(padre or [])
            padres.update(padres_de[valores["revision"]])

    # One head (alembic did not fork) that descends from this revision; not "this revision IS the head", so a
    # later migration on top keeps it green.
    heads = revisiones - padres
    assert len(heads) == 1, f"alembic forked: {heads}"
    pendientes, vistos = list(heads), set()
    while pendientes:
        actual = pendientes.pop()
        if actual in vistos:
            continue
        vistos.add(actual)
        pendientes.extend(padres_de.get(actual, []))
    assert "20261120_vpf_operaciones_overrides" in vistos
