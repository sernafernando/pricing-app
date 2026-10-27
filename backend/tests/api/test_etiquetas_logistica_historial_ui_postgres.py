"""History of a label's logistics and undo of the last change (flex-logistica-historial T4, S4-S6).

`GET /etiquetas-envio/{shipping_id}/logistica/historial` lists the changes newest first with names and colors and
says whether the last one can be undone; `POST /etiquetas-envio/{shipping_id}/logistica/deshacer` puts back the
previous logistics of the latest change (origen "deshacer"), or answers 409 without touching the label.

The endpoints run on a throwaway Postgres schema holding the tables they read (built from the ORM, without foreign
keys) and the `20261203_etiquetas_logistica_historial` migration installed on top, so the history rows come from
the real trigger.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator, Optional

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import HTTPException
from sqlalchemy import Engine, Enum, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateTable

from app.api.endpoints import etiquetas_assignments, etiquetas_shared
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.operador import Operador
from app.models.transporte import Transporte
from app.models.usuario import Usuario
from tests.conftest import _patch_pg_types_for_sqlite, _restore_pristine_pg_types
from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MIGRATION = os.path.join(_BACKEND_ROOT, "alembic", "versions", "20261203_etiquetas_logistica_historial.py")
_TABLES = [Logistica.__table__, Transporte.__table__, Operador.__table__, EtiquetaEnvio.__table__, Usuario.__table__]
_USUARIO_ID = 7
_OPERADOR_ID = 12

_UNO = {"id": 1, "nombre": "Uno", "color": "#111111"}
_DOS = {"id": 2, "nombre": "Dos", "color": "#222222"}
_TRES = {"id": 3, "nombre": "Tres", "color": None}


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
    "INSERT INTO logisticas (id, nombre, activa, color, pistoleado_asigna) VALUES "
    "(1, 'Uno', true, '#111111', false), (2, 'Dos', true, '#222222', false), (3, 'Tres', true, NULL, false), "
    "(4, 'Vieja', false, '#444444', false)",
    f"INSERT INTO operadores (id, pin, nombre, activo) VALUES ({_OPERADOR_ID}, '1234', 'Op', true)",
    f"INSERT INTO usuarios (id, nombre, activo) VALUES ({_USUARIO_ID}, 'Ana Panel', true)",
    "INSERT INTO etiquetas_envio (shipping_id, fecha_envio, logistica_id, es_manual) VALUES "
    "('S1', '2026-10-27', 1, false), ('S2', '2026-10-27', NULL, false), ('S3', '2026-10-27', 4, false)",
]


@pytest.fixture()
def publicados(monkeypatch) -> list:
    eventos: list = []
    monkeypatch.setattr(etiquetas_assignments, "sse_publish_bg", lambda *a, **k: eventos.append(a))
    return eventos


@pytest.fixture()
def engine(monkeypatch, publicados) -> Iterator[Engine]:
    monkeypatch.setattr(etiquetas_shared, "verificar_permiso", lambda db, user, codigo: True)
    with throwaway_schema("etq_log_ui", [], after=_create_tables) as engine:
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


def _cambiar(
    engine: Engine,
    shipping_id: str,
    logistica_id: Optional[int],
    origen: str,
    usuario_id: Optional[int] = None,
    operador_id: Optional[int] = None,
) -> None:
    """One logistics change in its own transaction, recorded by the real trigger."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "SELECT set_config('app.logistica_usuario_id', :u, true), "
                "set_config('app.logistica_operador_id', :o, true), set_config('app.logistica_origen', :origen, true)"
            ),
            {
                "u": "" if usuario_id is None else str(usuario_id),
                "o": "" if operador_id is None else str(operador_id),
                "origen": origen,
            },
        )
        conn.execute(
            text("UPDATE etiquetas_envio SET logistica_id = :l WHERE shipping_id = :s"),
            {"l": logistica_id, "s": shipping_id},
        )


def _logistica_actual(engine: Engine, shipping_id: str) -> Optional[int]:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT logistica_id FROM etiquetas_envio WHERE shipping_id = :s"), {"s": shipping_id}
        ).scalar()


def _historial(engine: Engine, shipping_id: str) -> list[tuple]:
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT logistica_anterior_id, logistica_nueva_id, usuario_id, operador_id, origen "
                    "FROM etiquetas_envio_logistica_historial WHERE shipping_id = :s ORDER BY id"
                ),
                {"s": shipping_id},
            )
        ]


def _ver(db: Session, shipping_id: str) -> dict:
    return etiquetas_assignments.historial_logistica(shipping_id, db=db, current_user=_user()).model_dump()


def _deshacer(db: Session, shipping_id: str, operador_id: Optional[int] = None) -> dict:
    payload = etiquetas_shared.DeshacerLogisticaRequest(operador_id=operador_id)
    return etiquetas_assignments.deshacer_logistica(shipping_id, payload, db=db, current_user=_user())


@pytest.mark.postgres
class TestHistorial:
    def test_lists_changes_newest_first_with_names_colors_origin_and_who(self, engine: Engine, db: Session) -> None:
        _cambiar(engine, "S1", 2, "asignar", usuario_id=_USUARIO_ID)
        _cambiar(engine, "S1", 3, "pistoleado", usuario_id=_USUARIO_ID, operador_id=_OPERADOR_ID)
        _cambiar(engine, "S1", None, "masivo")

        respuesta = _ver(db, "S1")

        cambios = respuesta.pop("cambios")
        assert respuesta == {"shipping_id": "S1", "logistica_actual": None, "puede_deshacer": True, "deshacer_a": _TRES}
        assert [
            (c["origen"], c["anterior"], c["nueva"], c["usuario_nombre"], c["operador_nombre"]) for c in cambios
        ] == [
            ("masivo", _TRES, None, None, None),
            ("pistoleado", _DOS, _TRES, "Ana Panel", "Op"),
            ("asignar", _UNO, _DOS, "Ana Panel", None),
        ]
        assert all(isinstance(c["id"], int) and c["cambiado_en"] for c in cambios)
        assert cambios[0]["id"] > cambios[1]["id"] > cambios[2]["id"]

    def test_empty_history(self, engine: Engine, db: Session) -> None:
        assert _ver(db, "S1") == {
            "shipping_id": "S1",
            "logistica_actual": _UNO,
            "puede_deshacer": False,
            "deshacer_a": None,
            "cambios": [],
        }

    def test_missing_label_is_404(self, engine: Engine, db: Session) -> None:
        with pytest.raises(HTTPException) as exc:
            _ver(db, "NO_EXISTE")
        assert exc.value.status_code == 404

    def test_cannot_undo_when_the_label_changed_after_the_last_record(self, engine: Engine, db: Session) -> None:
        _cambiar(engine, "S1", 2, "asignar", usuario_id=_USUARIO_ID)
        # A write that bypasses the trigger leaves the label out of step with its last history row.
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE etiquetas_envio DISABLE TRIGGER trg_etiquetas_envio_logistica_historial"))
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = 3 WHERE shipping_id = 'S1'"))
            conn.execute(text("ALTER TABLE etiquetas_envio ENABLE TRIGGER trg_etiquetas_envio_logistica_historial"))

        respuesta = _ver(db, "S1")

        assert (respuesta["logistica_actual"], respuesta["puede_deshacer"]) == (_TRES, False)

    def test_cannot_undo_back_to_an_inactive_logistica(self, engine: Engine, db: Session) -> None:
        _cambiar(engine, "S3", 1, "asignar", usuario_id=_USUARIO_ID)

        respuesta = _ver(db, "S3")

        assert respuesta["puede_deshacer"] is False
        assert respuesta["cambios"][0]["anterior"] == {"id": 4, "nombre": "Vieja", "color": "#444444"}

    def test_can_undo_back_to_unassigned(self, engine: Engine, db: Session) -> None:
        _cambiar(engine, "S2", 2, "asignar", usuario_id=_USUARIO_ID)

        respuesta = _ver(db, "S2")

        assert (respuesta["puede_deshacer"], respuesta["deshacer_a"]) == (True, None)


@pytest.mark.postgres
class TestDeshacer:
    def test_restores_the_previous_logistica_and_records_deshacer(
        self, engine: Engine, db: Session, publicados: list
    ) -> None:
        _cambiar(engine, "S1", 2, "asignar", usuario_id=_USUARIO_ID)

        respuesta = _deshacer(db, "S1", operador_id=_OPERADOR_ID)

        assert respuesta == {"ok": True, "shipping_id": "S1", "logistica_id": 1}
        assert _logistica_actual(engine, "S1") == 1
        assert _historial(engine, "S1")[-1] == (2, 1, _USUARIO_ID, _OPERADOR_ID, "deshacer")
        assert publicados == [("etiquetas:changed", {"hint": "reload"})]

    def test_undo_back_to_unassigned(self, engine: Engine, db: Session) -> None:
        _cambiar(engine, "S2", 2, "asignar", usuario_id=_USUARIO_ID)

        respuesta = _deshacer(db, "S2")

        assert respuesta == {"ok": True, "shipping_id": "S2", "logistica_id": None}
        assert _logistica_actual(engine, "S2") is None
        assert _historial(engine, "S2")[-1] == (2, None, _USUARIO_ID, None, "deshacer")

    def test_undoing_twice_toggles(self, engine: Engine, db: Session) -> None:
        _cambiar(engine, "S1", 2, "asignar", usuario_id=_USUARIO_ID)

        _deshacer(db, "S1")
        respuesta = _deshacer(db, "S1")

        assert respuesta["logistica_id"] == 2
        assert [fila[:2] for fila in _historial(engine, "S1")] == [(1, 2), (2, 1), (1, 2)]

    def test_missing_label_is_404(self, engine: Engine, db: Session) -> None:
        with pytest.raises(HTTPException) as exc:
            _deshacer(db, "NO_EXISTE")
        assert exc.value.status_code == 404

    def test_no_history_is_409_and_changes_nothing(self, engine: Engine, db: Session, publicados: list) -> None:
        with pytest.raises(HTTPException) as exc:
            _deshacer(db, "S1")

        assert (exc.value.status_code, exc.value.detail) == (
            409,
            "La etiqueta no tiene cambios de logística para deshacer.",
        )
        assert (_logistica_actual(engine, "S1"), _historial(engine, "S1"), publicados) == (1, [], [])

    def test_label_changed_after_the_last_record_is_409(self, engine: Engine, db: Session, publicados: list) -> None:
        _cambiar(engine, "S1", 2, "asignar", usuario_id=_USUARIO_ID)
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE etiquetas_envio DISABLE TRIGGER trg_etiquetas_envio_logistica_historial"))
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = 3 WHERE shipping_id = 'S1'"))
            conn.execute(text("ALTER TABLE etiquetas_envio ENABLE TRIGGER trg_etiquetas_envio_logistica_historial"))

        with pytest.raises(HTTPException) as exc:
            _deshacer(db, "S1")

        assert (exc.value.status_code, exc.value.detail) == (
            409,
            "La logística cambió desde el último registro; recargá el historial.",
        )
        assert (_logistica_actual(engine, "S1"), len(_historial(engine, "S1")), publicados) == (3, 1, [])

    def test_inactive_target_is_409(self, engine: Engine, db: Session, publicados: list) -> None:
        _cambiar(engine, "S3", 1, "asignar", usuario_id=_USUARIO_ID)

        with pytest.raises(HTTPException) as exc:
            _deshacer(db, "S3")

        assert (exc.value.status_code, exc.value.detail) == (409, "La logística anterior está inactiva.")
        assert (_logistica_actual(engine, "S3"), len(_historial(engine, "S3")), publicados) == (1, 1, [])

    def test_unknown_operador_is_404_and_changes_nothing(self, engine: Engine, db: Session, publicados: list) -> None:
        _cambiar(engine, "S1", 2, "asignar", usuario_id=_USUARIO_ID)

        with pytest.raises(HTTPException) as exc:
            _deshacer(db, "S1", operador_id=_OPERADOR_ID + 999)

        assert (exc.value.status_code, exc.value.detail) == (404, "Operador no encontrado o inactivo")
        assert (_logistica_actual(engine, "S1"), len(_historial(engine, "S1")), publicados) == (2, 1, [])
