"""Migration `20261118_ventas_fuera_pdf_operaciones` (ventas por fuera from PDF, T1: S13, S18).

Creates the upload, operation and line tables and seeds `ventas_fuera.subir_pdf` and `ventas_fuera.ver_metricas_pdf`.
Owner's decision (L7): both go to every role that today has `ventas_fuera.ver_dashboard`. Upgrade, re-run of the
seed and downgrade on a real Postgres with the ORM's own permission tables.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, bindparam, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.rol import Rol
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", "20261118_ventas_fuera_pdf_operaciones.py")
_NUEVOS = ("ventas_fuera.subir_pdf", "ventas_fuera.ver_metricas_pdf")
_TABLAS = {
    "ventas_fuera_pdf_cargas",
    "ventas_fuera_operaciones",
    "ventas_fuera_operacion_lineas",
    "ventas_fuera_pdf_alcances",
    "ventas_fuera_pdf_resumen_documentos",
}
_STUBS = ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)", "INSERT INTO usuarios VALUES (7)"]
_ROLES = text("""
    SELECT p.codigo, r.codigo FROM roles_permisos_base rp
    JOIN roles r ON r.id = rp.rol_id JOIN permisos p ON p.id = rp.permiso_id
    WHERE p.codigo LIKE 'ventas_fuera.%' ORDER BY p.codigo, r.codigo
""")


def _module():
    spec = importlib.util.spec_from_file_location("ventas_fuera_pdf_operaciones_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    module = _module()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


def _seed(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO roles (id, codigo, nombre, es_sistema, orden, activo) VALUES
                (1, 'ADMIN', 'Admin', true, 1, true), (2, 'VENTAS', 'Ventas', false, 5, true),
                (3, 'PRICING', 'Pricing', false, 4, true)
            """)
        )
        conn.execute(
            text("""
                INSERT INTO permisos (id, codigo, nombre, categoria, orden, es_critico)
                VALUES (100, 'ventas_fuera.ver_dashboard', 'Ver dashboard Fuera ML', 'ventas_fuera', 20, false)
            """)
        )
        conn.execute(text("INSERT INTO roles_permisos_base (rol_id, permiso_id) VALUES (1, 100), (2, 100)"))


@pytest.fixture
def engine() -> Iterator[Engine]:
    tables = [Rol.__table__, Permiso.__table__, RolPermisoBase.__table__, UsuarioPermisoOverride.__table__]
    with throwaway_schema("vf_pdf_migration", tables, _STUBS, after=_seed) as engine:
        yield engine


def test_revision_chain() -> None:
    module = _module()

    assert module.revision == "20261118_ventas_fuera_pdf_operaciones"
    assert module.down_revision == "20261118_tn_medidas_maestro"


def test_upgrade_creates_the_tables(engine: Engine) -> None:
    _step(engine, "upgrade")

    assert _TABLAS <= set(inspect(engine).get_table_names())


def test_upgrade_grants_both_permissions_to_the_roles_with_ver_dashboard(engine: Engine) -> None:
    _step(engine, "upgrade")

    with engine.connect() as conn:
        grants = conn.execute(_ROLES).all()
        categorias = (
            conn.execute(
                text("SELECT DISTINCT categoria FROM permisos WHERE codigo IN :c").bindparams(
                    bindparam("c", expanding=True)
                ),
                {"c": list(_NUEVOS)},
            )
            .scalars()
            .all()
        )

    assert grants == [
        ("ventas_fuera.subir_pdf", "ADMIN"),
        ("ventas_fuera.subir_pdf", "VENTAS"),
        ("ventas_fuera.ver_dashboard", "ADMIN"),
        ("ventas_fuera.ver_dashboard", "VENTAS"),
        ("ventas_fuera.ver_metricas_pdf", "ADMIN"),
        ("ventas_fuera.ver_metricas_pdf", "VENTAS"),
    ]
    assert categorias == ["ventas_fuera"]


def test_the_seed_can_run_twice_without_duplicates(engine: Engine) -> None:
    _step(engine, "upgrade")
    module = _module()
    with engine.begin() as conn:
        module.seed_permisos(conn)

    with engine.connect() as conn:
        assert len(conn.execute(_ROLES).all()) == 6
        assert conn.execute(text("SELECT COUNT(*) FROM permisos")).scalar_one() == 3


def test_one_document_per_company_and_lines_go_with_their_document(engine: Engine) -> None:
    _step(engine, "upgrade")
    doc = """
        INSERT INTO ventas_fuera_operaciones (carga_id, empresa, vendedor, cliente, tipo, letra, punto_venta, numero,
            fecha, importe, saldo, total_lineas, recargo_financiero)
        VALUES (1, :empresa, 'V', 'C', 'Fc', 'A', 3, 1, '2026-10-01', 121, 0, 100, 0)
    """
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO ventas_fuera_pdf_cargas (id, empresa, desde, hasta, archivo_detallado, documentos,
                    reemplazados, avisos, usuario_id)
                VALUES (1, 'GRUPO GAUSS SRL', '2026-10-01', '2026-10-31', 'd.pdf', 1, 0, '[]', 7)
            """)
        )
        conn.execute(text(doc), {"empresa": "GRUPO GAUSS SRL"})
        conn.execute(text(doc), {"empresa": "PASTORIZA"})
        conn.execute(
            text("""
                INSERT INTO ventas_fuera_operacion_lineas (operacion_id, renglon, articulo, cantidad, moneda, precio,
                    precio_costo, precio_costo_pp)
                SELECT id, 1, 'A', 1, 'ARS', 100, 80, 80 FROM ventas_fuera_operaciones
            """)
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(doc), {"empresa": "GRUPO GAUSS SRL"})

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ventas_fuera_operaciones WHERE empresa = 'PASTORIZA'"))
        assert conn.execute(text("SELECT COUNT(*) FROM ventas_fuera_operacion_lineas")).scalar_one() == 1


def test_one_scope_per_company_salesperson_and_range_todos_included(engine: Engine) -> None:
    _step(engine, "upgrade")
    alcance = """
        INSERT INTO ventas_fuera_pdf_alcances (empresa, vendedor, desde, hasta, avisos)
        VALUES ('GRUPO GAUSS SRL', :vendedor, '2026-10-01', '2026-10-31', '[]')
    """
    with engine.begin() as conn:
        conn.execute(text(alcance), {"vendedor": None})
        conn.execute(text(alcance), {"vendedor": "Carla Ejemplo"})

    for vendedor in (None, "Carla Ejemplo"):
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(alcance), {"vendedor": vendedor})


def test_downgrade_removes_only_what_it_added(engine: Engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido)
                SELECT 7, id, true FROM permisos WHERE codigo = 'ventas_fuera.subir_pdf'
            """)
        )

    _step(engine, "downgrade")

    with engine.connect() as conn:
        assert conn.execute(_ROLES).all() == [
            ("ventas_fuera.ver_dashboard", "ADMIN"),
            ("ventas_fuera.ver_dashboard", "VENTAS"),
        ]
        assert conn.execute(text("SELECT COUNT(*) FROM usuarios_permisos_override")).scalar_one() == 0
        assert conn.execute(text("SELECT codigo FROM permisos")).scalars().all() == ["ventas_fuera.ver_dashboard"]
    assert not _TABLAS & set(inspect(engine).get_table_names())
