"""Migration `20261129_costo_si_compras_sospechosas` (owner L29).

The upgrade creates the review table and its requeue trigger, seeds `costo_si.revisar` for ADMIN, and queues the
products whose stored history already holds an out-of-range purchase. The downgrade removes all of it. Tested on a
real Postgres in a throwaway schema, with invented data.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, text

from app.models.costo_si import CostoSiDirty, CostoSiPaso
from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.rol import Rol
from app.services.costo_si import queue, sospechas
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", "20261129_costo_si_compras_sospechosas.py")
_CODIGO = "costo_si.revisar"
_STUBS = ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)", "INSERT INTO usuarios VALUES (7)"]
SOSPECHOSO, NORMAL = 23, 24


def _module():
    spec = importlib.util.spec_from_file_location("costo_si_compras_sospechosas_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    module = _module()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


def _paso(conn, item_id: int, orden: int, tipo: str, neto: str, promedio: str) -> None:
    conn.execute(
        text(
            "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, ct_transaction, cantidad, costo_neto_usd, "
            "costo_neto_neto_usd, stock_antes, stock_base, stock_despues, promedio_usd) "
            "VALUES (:i, :o, :t, :f, :ct, 10, :n, :n, 0, 0, 10, :p)"
        ),
        {
            "i": item_id,
            "o": orden,
            "t": tipo,
            "f": date(2026, 10, 1 + orden),
            "ct": None if orden == 0 else 900 + orden,
            "n": Decimal(neto),
            "p": Decimal(promedio),
        },
    )


def _seed(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(queue._ENCOLAR))
        conn.execute(
            text(
                "INSERT INTO roles (id, codigo, nombre, es_sistema, orden, activo) "
                "VALUES (1, 'ADMIN', 'Admin', true, 1, true), (2, 'VENTAS', 'Ventas', false, 5, true)"
            )
        )
        # Item 23: a purchase at 0.00971 after an average of 13.5355 (prod's invoice 00128199), stored before L29.
        _paso(conn, SOSPECHOSO, 0, "inicio", "13.5355", "13.5355")
        _paso(conn, SOSPECHOSO, 1, "compra", "0.00971", "3.29267")
        # Item 24: exactly 10x and 1/10 its previous averages: not suspicious.
        _paso(conn, NORMAL, 0, "inicio", "5", "5")
        _paso(conn, NORMAL, 1, "compra", "50", "50")
        _paso(conn, NORMAL, 2, "compra", "5", "5")


@pytest.fixture
def engine() -> Iterator[Engine]:
    tables = [
        Rol.__table__,
        Permiso.__table__,
        RolPermisoBase.__table__,
        UsuarioPermisoOverride.__table__,
        CostoSiPaso.__table__,
        CostoSiDirty.__table__,
    ]
    with throwaway_schema("costo_si_sospechosas_mig", tables, _STUBS, after=_seed) as engine:
        yield engine


def _scalar(engine: Engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def test_its_trigger_sql_is_the_services_own() -> None:
    module = _module()

    assert (module.UPGRADE_SQL, module.DOWNGRADE_SQL) == (sospechas.UPGRADE_SQL, sospechas.DOWNGRADE_SQL)


def test_upgrade_queues_only_the_products_with_a_stored_out_of_range_purchase(engine: Engine) -> None:
    _step(engine, "upgrade")

    with engine.connect() as conn:
        assert conn.execute(text("SELECT item_id, desde FROM costo_si_dirty")).all() == [(SOSPECHOSO, None)]


def test_upgrade_grants_the_review_permission_to_admin_only(engine: Engine) -> None:
    _step(engine, "upgrade")

    roles = _scalar(
        engine,
        "SELECT string_agg(r.codigo, ',' ORDER BY r.codigo) FROM roles_permisos_base rp JOIN roles r ON r.id = rp.rol_id "
        "JOIN permisos p ON p.id = rp.permiso_id WHERE p.codigo = :c",
        c=_CODIGO,
    )
    assert (_scalar(engine, "SELECT categoria FROM permisos WHERE codigo = :c", c=_CODIGO), roles) == (
        "productos",
        "ADMIN",
    )


def test_a_change_of_state_requeues_the_product_from_the_invoice_date(engine: Engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM costo_si_dirty"))
        conn.execute(
            text(
                "INSERT INTO costo_si_compras_sospechosas (item_id, ct_transaction, fecha, cantidad, precio, moneda, "
                "referencia, fuente_ref, ratio) VALUES (23, 901, '2026-10-27', 312, 0.00971, 'USD', 13.5355, "
                "'costo_si', 0.000717)"
            )
        )
        insertada = conn.execute(text("SELECT count(*) FROM costo_si_dirty")).scalar()
        conn.execute(text("UPDATE costo_si_compras_sospechosas SET nota = 'x'"))
        sin_cambio = conn.execute(text("SELECT count(*) FROM costo_si_dirty")).scalar()
        conn.execute(text("UPDATE costo_si_compras_sospechosas SET estado = 'aceptada', revisado_por = 7"))
        encolado = conn.execute(text("SELECT item_id, desde FROM costo_si_dirty")).all()

    assert (insertada, sin_cambio, encolado) == (0, 0, [(23, date(2026, 10, 27))])


def test_an_unknown_state_is_refused(engine: Engine) -> None:
    _step(engine, "upgrade")

    with pytest.raises(Exception, match="ck_costo_si_compras_sospechosas_estado"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO costo_si_compras_sospechosas (item_id, ct_transaction, fecha, cantidad, precio, "
                    "moneda, referencia, fuente_ref, ratio, estado) VALUES (23, 901, '2026-10-27', 1, 1, 'USD', 1, "
                    "'costo_si', 1, 'otro')"
                )
            )


def test_downgrade_removes_the_table_trigger_and_permission_and_requeues_excluded_histories(engine: Engine) -> None:
    _step(engine, "upgrade")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido) "
                "SELECT 7, id, true FROM permisos WHERE codigo = :c"
            ),
            {"c": _CODIGO},
        )
        conn.execute(text("DELETE FROM costo_si_dirty"))
        conn.execute(text("UPDATE costo_si_pasos SET tipo = 'excluido' WHERE item_id = 23 AND orden = 1"))

    _step(engine, "downgrade")

    assert _scalar(engine, "SELECT to_regclass('costo_si_compras_sospechosas')") is None
    assert _scalar(engine, "SELECT count(*) FROM pg_proc WHERE proname = 'costo_si_trg_sospechosa'") == 0
    assert _scalar(engine, "SELECT count(*) FROM permisos WHERE codigo = :c", c=_CODIGO) == 0
    assert _scalar(engine, "SELECT count(*) FROM usuarios_permisos_override") == 0
    # The product with an 'excluido' step goes back to averaging every purchase.
    assert _scalar(engine, "SELECT string_agg(item_id::text, ',') FROM costo_si_dirty") == "23"
