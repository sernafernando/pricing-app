"""Tests for `ejemplos_service.capturar_correccion` (tickets-triage-feedback
PR3, design "Best-effort correction capture behind a flag"). Capture-only —
this PR ships no retrieval.

Covers:
- Flag off (default): confirming a correction does not call `embed_passage`
  and writes no row.
- Flag on + embed succeeds: exactly one `EjemploCorreccion` row for that
  `(propuesta_id, campo)`.
- Ratifying confirm / discard never schedule capture at all.
- Capture never fails a confirm — flag on with embed returning `None`, or
  the capture hook raising, both still leave the confirm HTTP response and
  the committed proposal state untouched.

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_ejemplos_service.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.models.ejemplo_correccion import EjemploCorreccion
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow
from app.tickets.services import confirmacion_service, ejemplos_service

_seq = [0]


class _FakeBackgroundDb:
    """Mirrors `test_confirmacion_service.py`'s own fixture — reuses the
    test's transactional `db` session instead of a real second connection."""

    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._db.commit()
        else:
            self._db.rollback()
        return False


def _patch_background_db(db):
    return patch("app.tickets.services.ejemplos_service.get_background_db", return_value=_FakeBackgroundDb(db))


def _make_sector(db) -> Sector:
    _seq[0] += 1
    s = Sector(codigo=f"EJEMPLOS_SECT_{_seq[0]}", nombre="Sector Ejemplos Test", activo=True, configuracion={})
    db.add(s)
    db.flush()
    return s


def _make_tipo_y_estado(db, sector: Sector) -> tuple[TipoTicket, EstadoTicket]:
    workflow = Workflow(sector_id=sector.id, nombre="WF Ejemplos Test", es_default=True, activo=True)
    db.add(workflow)
    db.flush()

    estado = EstadoTicket(
        workflow_id=workflow.id, codigo="abierto", nombre="Abierto", orden=1, es_inicial=True, es_final=False
    )
    db.add(estado)
    db.flush()

    tipo = TipoTicket(sector_id=sector.id, codigo="bug", nombre="Bug", workflow_id=workflow.id)
    db.add(tipo)
    db.flush()
    return tipo, estado


def _make_usuario(db, rol: Rol) -> Usuario:
    _seq[0] += 1
    usuario = Usuario(
        username=f"ejemplos_user_{_seq[0]}",
        email=f"ejemplos_{_seq[0]}@test.com",
        nombre="Ejemplos Test User",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _make_ticket(db, rol: Rol, texto_original: str = "El login no funciona desde ayer a la tarde") -> Ticket:
    sector = _make_sector(db)
    tipo, estado = _make_tipo_y_estado(db, sector)
    creador = _make_usuario(db, rol)
    ticket = Ticket(
        titulo="Ticket para captura de ejemplos",
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        campos_metadata={},
        texto_original=texto_original,
    )
    db.add(ticket)
    db.flush()
    return ticket


def _make_propuesta(
    db, ticket: Ticket, campo: str = "severidad", valor="mayor", estado: str = "pendiente"
) -> PropuestaIA:
    propuesta = PropuestaIA(
        ticket_id=ticket.id,
        campo=campo,
        valor_propuesto={"valor": valor},
        estado=estado,
    )
    db.add(propuesta)
    db.flush()
    return propuesta


@pytest.fixture
def rol(db):
    _seq[0] += 1
    r = Rol(codigo=f"VENTAS_EJ_{_seq[0]}", nombre="Ventas", es_sistema=False, orden=10, activo=True)
    db.add(r)
    db.flush()
    return r


class TestCapturarCorreccionDirect:
    """Direct unit tests of `capturar_correccion`, independent of the HTTP
    endpoint (mirrors `TestFewshotCapture`'s own AsyncMock-based style)."""

    def test_flag_off_does_not_embed_or_insert(self, db, rol, monkeypatch) -> None:
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_EJEMPLOS_CAPTURE", False)
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")
        confirmacion_service.confirmar(db, propuesta.id, usuario, valor_corregido="menor")
        assert propuesta.estado == "corregida"

        embed_passage = AsyncMock(return_value=[0.1] * 384)
        with (
            _patch_background_db(db),
            patch("app.tickets.services.ejemplos_service.embed_passage", new=embed_passage),
        ):
            asyncio.run(ejemplos_service.capturar_correccion(propuesta.id))

        embed_passage.assert_not_called()
        assert db.query(EjemploCorreccion).count() == 0

    def test_flag_on_and_embed_ok_inserts_one_row(self, db, rol, monkeypatch) -> None:
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_EJEMPLOS_CAPTURE", True)
        ticket = _make_ticket(db, rol, texto_original="El sistema no permite facturar desde esta mañana")
        usuario = _make_usuario(db, rol)
        propuesta = _make_propuesta(db, ticket, campo="urgencia", valor="baja")
        confirmacion_service.confirmar(db, propuesta.id, usuario, valor_corregido="alta")
        assert propuesta.estado == "corregida"

        embed_passage = AsyncMock(return_value=[0.1] * 384)
        with (
            _patch_background_db(db),
            patch("app.tickets.services.ejemplos_service.embed_passage", new=embed_passage),
        ):
            asyncio.run(ejemplos_service.capturar_correccion(propuesta.id))

        embed_passage.assert_called_once()
        filas = db.query(EjemploCorreccion).filter_by(propuesta_id=propuesta.id, campo="urgencia").all()
        assert len(filas) == 1
        fila = filas[0]
        assert fila.ticket_id == ticket.id
        assert fila.valor_ia == "baja"
        assert fila.valor_corregido == "alta"
        assert fila.texto == "El sistema no permite facturar desde esta mañana"
        assert fila.active is True

    def test_ratifying_confirm_never_schedules_capture(self, db, rol) -> None:
        """A plain ratification (`es_ia_auto_sin_revisar`, no correction)
        resolves `estado='confirmada'`, never `'corregida'` — the endpoint's
        gate must never even schedule capture for this shape."""
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor", estado="confirmada")
        propuesta.confirmado_por_id = None
        db.flush()

        resultado = confirmacion_service.confirmar(db, propuesta.id, usuario)
        assert resultado.estado == "confirmada"

    def test_discard_never_schedules_capture(self, db, rol) -> None:
        """`descartar()` never returns `estado='corregida'` — proven by
        construction (it only ever sets `descartada`), so the endpoint gate
        (`resultado.estado == 'corregida'`) can never fire for a discard."""
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")
        resultado = confirmacion_service.descartar(db, propuesta.id, usuario)
        assert resultado.estado == "descartada"


def _give_permiso(db, usuario: Usuario, codigo: str = "tickets.triage.confirmar") -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not permiso:
        permiso = Permiso(codigo=codigo, nombre=codigo, categoria="tickets")
        db.add(permiso)
        db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=usuario.id, permiso_id=permiso.id, concedido=True))
    db.flush()


def _headers(usuario: Usuario) -> dict:
    token = create_access_token(data={"sub": usuario.username})
    return {"Authorization": f"Bearer {token}"}


class TestCaptureNeverFailsAConfirm:
    """Capture failure must never propagate into (or affect the outcome of)
    a confirm that has already committed — exercised through the real HTTP
    endpoint (`propuestas.py::confirmar_propuesta`) via the shared `client`
    fixture, whose `BackgroundTasks` run synchronously under `TestClient`."""

    def test_embed_returns_none_confirm_still_succeeds(self, client, db, rol, monkeypatch) -> None:
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_EJEMPLOS_CAPTURE", True)
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        embed_passage = AsyncMock(return_value=None)
        with (
            _patch_background_db(db),
            patch("app.tickets.services.ejemplos_service.embed_passage", new=embed_passage),
        ):
            response = client.post(
                f"/api/tickets/propuestas/{propuesta.id}/confirmar",
                json={"valor_corregido": "menor"},
                headers=_headers(usuario),
            )

        assert response.status_code == 200
        db.refresh(propuesta)
        assert propuesta.estado == "corregida"
        assert propuesta.valor_corregido == "menor"
        assert db.query(EjemploCorreccion).count() == 0

    def test_capture_hook_raises_confirm_still_succeeds_and_logs(self, client, db, rol, monkeypatch, caplog) -> None:
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_EJEMPLOS_CAPTURE", True)
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        embed_passage = AsyncMock(side_effect=RuntimeError("embedder unreachable"))
        with (
            caplog.at_level("WARNING"),
            _patch_background_db(db),
            patch("app.tickets.services.ejemplos_service.embed_passage", new=embed_passage),
        ):
            response = client.post(
                f"/api/tickets/propuestas/{propuesta.id}/confirmar",
                json={"valor_corregido": "menor"},
                headers=_headers(usuario),
            )

        assert response.status_code == 200
        db.refresh(propuesta)
        assert propuesta.estado == "corregida"
        assert propuesta.valor_corregido == "menor"
        assert db.query(EjemploCorreccion).count() == 0
        assert any("correction capture failed" in record.message for record in caplog.records)
