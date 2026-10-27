"""Who and source of a logistics change (flex-logistica-historial T3, S2): each write path of
`etiquetas_envio.logistica_id` sets the transaction-local settings the history trigger reads, so the row it
records carries the panel user, the operator and the source (asignar / masivo / pistoleado / manual).

The endpoints run on a throwaway Postgres schema holding the real tables they touch (built from the ORM, without
foreign keys) and the `20261203_etiquetas_logistica_historial` migration installed on top. Each test also pins
the response the endpoint returned before this change.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import date
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import BackgroundTasks
from sqlalchemy import Engine, Enum, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateTable

from app.api.endpoints import (
    etiquetas_assignments,
    etiquetas_manual,
    etiquetas_pistoleado,
    etiquetas_shared,
)
from app.models.codigo_postal_cordon import CodigoPostalCordon
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.operador import Operador
from app.models.operador_actividad import OperadorActividad
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_status import SaleOrderStatus
from app.models.transporte import Transporte
from app.models.usuario import Usuario
from tests.conftest import _patch_pg_types_for_sqlite, _restore_pristine_pg_types
from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MIGRATION = os.path.join(_BACKEND_ROOT, "alembic", "versions", "20261203_etiquetas_logistica_historial.py")
_TABLES = [
    Logistica.__table__,
    Transporte.__table__,
    Operador.__table__,
    OperadorActividad.__table__,
    EtiquetaEnvio.__table__,
    MercadoLibreOrderShipping.__table__,
    CodigoPostalCordon.__table__,
    SaleOrderHeader.__table__,
    SaleOrderStatus.__table__,
    Usuario.__table__,
]
_USUARIO_ID = 7
_OPERADOR_ID = 12


def _create_tables(engine: Engine) -> None:
    # Without foreign keys: the endpoints only need these tables, not everything they point to.
    _restore_pristine_pg_types(_TABLES)
    try:
        with engine.begin() as conn:
            for table in _TABLES:
                for column in table.columns:
                    if isinstance(column.type, Enum):
                        column.type.create(bind=conn, checkfirst=True)
                conn.execute(CreateTable(table, include_foreign_key_constraints=[]))
    finally:
        _patch_pg_types_for_sqlite()


def _install_history(engine: Engine) -> None:
    spec = importlib.util.spec_from_file_location("etiquetas_logistica_historial_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            module.upgrade()


_SEED = [
    "INSERT INTO logisticas (id, nombre, activa, pistoleado_asigna) VALUES (1, 'Uno', true, false), "
    "(2, 'Dos', true, true), (3, 'Tres', true, false)",
    f"INSERT INTO operadores (id, pin, nombre, activo) VALUES ({_OPERADOR_ID}, '1234', 'Op', true)",
    "INSERT INTO etiquetas_envio (shipping_id, fecha_envio, logistica_id, es_manual) VALUES "
    "('S1', '2026-10-27', 1, false), ('S2', '2026-10-27', 1, false), ('S3', '2026-10-27', NULL, false)",
    "INSERT INTO etiquetas_envio (shipping_id, fecha_envio, logistica_id, es_manual, manual_receiver_name, "
    "manual_street_name, manual_street_number, manual_zip_code, manual_city_name, manual_status) VALUES "
    "('MAN_1', '2026-10-27', 1, true, 'Ana', 'Calle', '10', '1000', 'Ciudad', 'ready_to_ship')",
]


@pytest.fixture()
def engine(monkeypatch) -> Iterator[Engine]:
    monkeypatch.setattr(etiquetas_shared, "verificar_permiso", lambda db, user, codigo: True)
    for module in (etiquetas_assignments, etiquetas_pistoleado, etiquetas_manual):
        monkeypatch.setattr(module, "sse_publish_bg", lambda *a, **k: None)
    with throwaway_schema("etq_log_origen", [], after=_create_tables) as engine:
        _install_history(engine)
        with engine.begin() as conn:
            for statement in _SEED:
                conn.execute(text(statement))
        yield engine


@pytest.fixture()
def db(engine: Engine) -> Iterator[Session]:
    # Same session settings as production (`SessionLocal`): nothing is flushed before the commit.
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


def _user() -> Usuario:
    user = Usuario()
    user.id = _USUARIO_ID
    return user


def _historial(engine: Engine) -> list[tuple]:
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT shipping_id, logistica_anterior_id, logistica_nueva_id, usuario_id, operador_id, origen "
                    "FROM etiquetas_envio_logistica_historial ORDER BY shipping_id, id"
                )
            )
        ]


@pytest.mark.postgres
class TestOrigenPorEndpoint:
    def test_asignar_logistica_records_the_user_and_asignar(self, engine: Engine, db: Session) -> None:
        payload = etiquetas_assignments.AsignarLogisticaRequest(logistica_id=2)

        respuesta = etiquetas_assignments.asignar_logistica("S1", payload, db=db, current_user=_user())

        assert respuesta == {"ok": True, "shipping_id": "S1", "logistica_id": 2}
        assert _historial(engine) == [("S1", 1, 2, _USUARIO_ID, None, "asignar")]

    def test_asignar_masivo_records_the_user_and_masivo_per_changed_label(self, engine: Engine, db: Session) -> None:
        payload = etiquetas_assignments.AsignarMasivoRequest(shipping_ids=["S1", "S2", "S3"], logistica_id=2)

        respuesta = etiquetas_assignments.asignar_masivo(payload, db=db, current_user=_user())

        assert respuesta == {"ok": True, "actualizadas": 3, "logistica_id": 2, "logistica_nombre": "Dos"}
        assert _historial(engine) == [
            ("S1", 1, 2, _USUARIO_ID, None, "masivo"),
            ("S2", 1, 2, _USUARIO_ID, None, "masivo"),
            ("S3", None, 2, _USUARIO_ID, None, "masivo"),
        ]

    def test_pistoleado_reassignment_records_user_operator_and_pistoleado(self, engine: Engine, db: Session) -> None:
        # Logistics 2 has pistoleado_asigna: scanning S1 (logistics 1) for it reassigns the label.
        payload = etiquetas_shared.PistolearRequest(
            shipping_id="S1", caja="CAJA 1", logistica_id=2, operador_id=_OPERADOR_ID
        )

        respuesta = etiquetas_pistoleado.pistolear_etiqueta(payload, db=db, current_user=_user())

        assert (respuesta.ok, respuesta.shipping_id, respuesta.caja, respuesta.operador) == (
            True,
            "S1",
            "CAJA 1",
            "Op",
        )
        assert _historial(engine) == [("S1", 1, 2, _USUARIO_ID, _OPERADOR_ID, "pistoleado")]

    def test_pistoleado_forced_assignment_records_pistoleado(self, engine: Engine, db: Session) -> None:
        # Logistics 3 has no pistoleado_asigna: an unassigned label only takes it on the confirmed double scan.
        payload = etiquetas_shared.PistolearRequest(
            shipping_id="S3", caja="CAJA 1", logistica_id=3, operador_id=_OPERADOR_ID, forzar_asignacion=True
        )

        etiquetas_pistoleado.pistolear_etiqueta(payload, db=db, current_user=_user())

        assert _historial(engine) == [("S3", None, 3, _USUARIO_ID, _OPERADOR_ID, "pistoleado")]

    def test_editar_envio_manual_records_user_operator_and_manual(self, engine: Engine, db: Session) -> None:
        payload = etiquetas_shared.CrearEnvioManualRequest(
            fecha_envio=date(2026, 10, 27),
            receiver_name="Ana",
            street_name="Calle",
            street_number="10",
            zip_code="1000",
            city_name="Ciudad",
            status="ready_to_ship",
            logistica_id=3,
            operador_id=_OPERADOR_ID,
        )

        respuesta = etiquetas_manual.editar_envio_manual(
            "MAN_1", payload, background_tasks=BackgroundTasks(), db=db, current_user=_user()
        )

        assert respuesta == {"ok": True, "shipping_id": "MAN_1", "cordon": None, "mensaje": "Envío MAN_1 actualizado"}
        assert _historial(engine) == [("MAN_1", 1, 3, _USUARIO_ID, _OPERADOR_ID, "manual")]
