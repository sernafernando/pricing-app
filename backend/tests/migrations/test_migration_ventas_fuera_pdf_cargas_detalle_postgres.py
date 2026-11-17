"""Migration `20261119_ventas_fuera_pdf_cargas_detalle` (vpf-metricas-canal-fe S8: "Additive migration").

Nullable per-upload columns on `ventas_fuera_pdf_cargas`, filled at upload for the upload history (C2): a row loaded
before the migration keeps them NULL ('—' on screen). No data change; downgrade drops only those columns. Real
Postgres, on the tables of the parent migration `20261118_ventas_fuera_pdf_operaciones`.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.rol import Rol
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

_VERSIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "alembic", "versions"
)
_PATH = os.path.join(_VERSIONS, "20261119_ventas_fuera_pdf_cargas_detalle.py")
_PARENT = os.path.join(_VERSIONS, "20261118_ventas_fuera_pdf_operaciones.py")
_COLUMNAS = {
    "vendedores",
    "lineas",
    "unidades",
    "total_lineas",
    "sin_producto_lineas",
    "sin_producto_monto",
    "recargo_financiero",
    "documentos_por_tipo",
    "control",
    "control_estado",
    "carga_anterior_at",
}
_STUBS = ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)", "INSERT INTO usuarios VALUES (7)"]


def _module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, path: str, step: str) -> None:
    module = _module(path, f"migration_{os.path.basename(path)[:-3]}")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


def _columnas(engine: Engine) -> dict:
    return {c["name"]: c for c in inspect(engine).get_columns("ventas_fuera_pdf_cargas")}


@pytest.fixture
def engine() -> Iterator[Engine]:
    tables = [Rol.__table__, Permiso.__table__, RolPermisoBase.__table__, UsuarioPermisoOverride.__table__]
    with throwaway_schema("vf_pdf_detalle_migration", tables, _STUBS) as engine:
        _step(engine, _PARENT, "upgrade")
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO ventas_fuera_pdf_cargas (id, empresa, vendedor, desde, hasta, archivo_detallado,
                        documentos, reemplazados, avisos, usuario_id)
                    VALUES (1, 'EMPRESA EJEMPLO SA', NULL, '2025-01-01', '2025-01-31', 'detallada.pdf', 3, 0, '[]', 7)
                """)
            )
        yield engine


def test_revision_chain() -> None:
    module = _module(_PATH, "detalle_chain")

    assert module.revision == "20261119_ventas_fuera_pdf_cargas_detalle"
    # Release order #2300 -> T4 (#2302) -> this.
    assert module.down_revision == "20261119_vpf_offsets_sell_pdf"


def test_upgrade_adds_nullable_columns_and_leaves_existing_rows_null(engine: Engine) -> None:
    _step(engine, _PATH, "upgrade")

    columnas = _columnas(engine)
    assert _COLUMNAS <= set(columnas)
    assert all(columnas[nombre]["nullable"] for nombre in _COLUMNAS)
    with engine.connect() as conn:
        fila = conn.execute(text("SELECT * FROM ventas_fuera_pdf_cargas WHERE id = 1")).mappings().one()
    assert {nombre: fila[nombre] for nombre in _COLUMNAS} == dict.fromkeys(_COLUMNAS)
    assert (fila["empresa"], fila["documentos"], fila["archivo_detallado"]) == (
        "EMPRESA EJEMPLO SA",
        3,
        "detallada.pdf",
    )


def test_downgrade_drops_only_the_added_columns(engine: Engine) -> None:
    antes = set(_columnas(engine))
    _step(engine, _PATH, "upgrade")

    _step(engine, _PATH, "downgrade")

    assert set(_columnas(engine)) == antes
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM ventas_fuera_pdf_cargas")).scalar_one() == 1
